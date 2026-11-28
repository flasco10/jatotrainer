"""Marathon export: join osu!mania charts into one chart, one audio file and a collage background."""
import math
import shutil
import subprocess
import sys
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from pack_backend import background_path, plain_title, safe_source, validate_settings

SIZE = (1920, 1080)
SAMPLE_RATE = 44100
MAX_BACKGROUND_BYTES = 2_500_000  # osu! ranking criteria background limit


# --------------------------------------------------------------------------- #
# Background collage
# --------------------------------------------------------------------------- #
def auto_weights(lengths):
    """Slot size per map: 1 for a typical map, 2-4 for maps 2-4x longer than the median."""
    if not lengths:
        return []
    median = sorted(lengths)[len(lengths) // 2] or 1
    return [max(1, min(4, round(length / median))) for length in lengths]


def auto_row_count(total_weight, per_row=4):
    """Fill rows of side-by-side strips, starting a new row past `per_row` slots (None = one row)."""
    return 1 if per_row is None else max(1, math.ceil(round(total_weight, 6) / per_row))


def _balanced_rows(weights, rows):
    """Split maps, in order, into `rows` nonempty rows with totals as even as possible."""
    n = len(weights)
    rows = max(1, min(rows, n))
    prefix = [0.0]
    for weight in weights:
        prefix.append(prefix[-1] + weight)
    target = prefix[-1] / rows
    best = [[math.inf] * (n + 1) for _ in range(rows + 1)]
    cut = [[0] * (n + 1) for _ in range(rows + 1)]
    best[0][0] = 0
    for r in range(1, rows + 1):
        for j in range(r, n + 1):
            for i in range(r - 1, j):
                cost = best[r - 1][i] + (prefix[j] - prefix[i] - target) ** 2
                if cost <= best[r][j]:  # on ties, later cuts put more maps on the upper rows
                    best[r][j], cut[r][j] = cost, i
    groups, j = [], n
    for r in range(rows, 0, -1):
        i = cut[r][j]
        groups.append(list(range(i, j)))
        j = i
    return groups[::-1]


def collage_layout(weights, rows=None, size=SIZE, gap=4, per_row=4):
    """Return one (x, y, w, h) tile per map.

    `rows` is a list with a 1-based row number per map, or None for "Auto".
    All-auto rows are balanced automatically; once any map has a row, auto maps
    stay on the row of the map before them.
    """
    n = len(weights)
    if n == 0:
        return []
    weights = [max(0.1, float(w)) for w in weights]
    rows = list(rows or [None] * n)
    if all(r is None for r in rows):
        groups = _balanced_rows(weights, auto_row_count(sum(weights), per_row))
    else:
        current, numbered = 1, {}
        for i, row in enumerate(rows):
            current = row if row is not None else current
            numbered.setdefault(current, []).append(i)
        groups = [numbered[key] for key in sorted(numbered)]
    width, height = size
    rects = [None] * n
    half = gap // 2
    for r, group in enumerate(groups):
        y0, y1 = round(r * height / len(groups)), round((r + 1) * height / len(groups))
        total, running = sum(weights[i] for i in group), 0.0
        for i in group:
            x0 = round(running / total * width)
            running += weights[i]
            x1 = round(running / total * width)
            left = x0 + (half if x0 > 0 else 0)
            right = x1 - (gap - half if x1 < width else 0)
            top = y0 + (half if y0 > 0 else 0)
            bottom = y1 - (gap - half if y1 < height else 0)
            rects[i] = (left, top, max(1, right - left), max(1, bottom - top))
    return rects


def crop_box(image_size, tile_size, fx=0.5, fy=0.5, zoom=1.0):
    """Region of the image that fills the tile: covers it at `zoom`, panned by fx/fy (0 = left/top, 1 = right/bottom)."""
    (iw, ih), (w, h) = image_size, tile_size
    if iw / ih > w / h:
        cw, ch = ih * w / h, ih
    else:
        cw, ch = iw, iw * h / w
    cw, ch = cw / max(1.0, zoom), ch / max(1.0, zoom)
    fx, fy = min(1.0, max(0.0, fx)), min(1.0, max(0.0, fy))
    left, top = (iw - cw) * fx, (ih - ch) * fy
    return left, top, left + cw, top + ch


def _crop_settings(value):
    """Accept a bare horizontal focus number or an (fx, fy, zoom) tuple."""
    if isinstance(value, (int, float)):
        return float(value), 0.5, 1.0
    fx, fy, zoom = (tuple(value) + (0.5, 0.5, 1.0)[len(value):])[:3]
    return float(fx), float(fy), float(zoom)


def render_collage(images, rects, size=SIZE, focus=None, resample=Image.Resampling.LANCZOS):
    """Crop each image into its tile on a black canvas; missing images become gray tiles.

    focus: per image, a horizontal focus (0 = left, 0.5 = center, 1 = right) or (fx, fy, zoom).
    """
    canvas = Image.new("RGB", size, "#000000")
    focus = focus or [0.5] * len(rects)
    for image, (x, y, w, h), setting in zip(images, rects, focus):
        if image is None:
            tile = Image.new("RGB", (w, h), "#2a2f3d")
        else:
            tile = image.resize((w, h), resample, box=crop_box(image.size, (w, h), *_crop_settings(setting)))
        canvas.paste(tile, (x, y))
    return canvas


def save_background(image, path):
    for quality in (92, 85, 78, 70, 60):
        image.save(path, "JPEG", quality=quality, optimize=True)
        if path.stat().st_size <= MAX_BACKGROUND_BYTES:
            return
    raise ValueError("The collage background could not be compressed under 2.5 MB.")


# --------------------------------------------------------------------------- #
# Chart helpers
# --------------------------------------------------------------------------- #
def object_span(core, sections):
    """(first start, last end) in ms of a chart's hit objects."""
    times = []
    for line in core.sec(sections, "HitObjects"):
        p = line.split(",")
        if len(p) < 5:
            continue
        start = int(float(p[2]))
        end = int(float(p[5].split(":", 1)[0])) if int(p[3]) & 128 and len(p) > 5 else start
        times += [start, end]
    if not times:
        raise ValueError("Chart has no hit objects.")
    return min(times), max(times)


def chart_length_ms(core, path, rate=1.0):
    _, sections = core.parse_osu(path)
    first, last = object_span(core, sections)
    return (last - first) / rate


def _shift_field(value, ms):
    return str(int(round(float(value))) + ms)


def _shift_timing(lines, ms, floor):
    out = []
    for line in lines:
        p = line.split(",")
        if len(p) < 2 or not line.strip():
            continue
        # A point placed before this song (negative offset) must not retime the previous song.
        p[0] = str(max(int(round(float(p[0]))) + ms, floor))
        out.append(",".join(p))
    return out


def _shift_objects(lines, ms):
    out = []
    for line in lines:
        p = line.split(",")
        if len(p) < 5:
            continue
        p[2] = _shift_field(p[2], ms)
        if int(p[3]) & 128 and len(p) > 5:
            parts = p[5].split(":")
            parts[0] = _shift_field(parts[0], ms)
            if len(parts) > 5:
                parts[-1] = ""  # custom hitsound files are not copied into the marathon
            p[5] = ":".join(parts)
        elif len(p) > 5:
            parts = p[5].split(":")
            if len(parts) > 4:
                parts[-1] = ""
            p[5] = ":".join(parts)
        out.append(",".join(p))
    return out


def _shift_breaks(core, lines, rate, ms):
    out = []
    for line in core.scale_events([l for l in lines if l.split(",")[0].strip() in ("2", "Break")], rate):
        p = line.split(",")
        p[1], p[2] = _shift_field(p[1], ms), _shift_field(p[2], ms)
        out.append(",".join(p))
    return out


# --------------------------------------------------------------------------- #
# Audio
# --------------------------------------------------------------------------- #
def _decode(core, ffmpeg, source, destination, rate, pitch):
    flt = "aresample=44100" if rate == 1 else core.rate_filter(rate, pitch) + ",aresample=44100"
    cmd = [ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-i", str(source), "-map", "0:a:0", "-vn",
           "-filter:a", flt, "-ac", "2", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", "-f", "wav", str(destination)]
    flags = 0x08000000 if sys.platform == "win32" else 0
    result = subprocess.run(cmd, capture_output=True, check=False, creationflags=flags)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip() or f"FFmpeg could not decode {source.name}")


def _join_wavs(parts, destination):
    """Write the parts back to back; each part is (wav path or None, silence frames). Returns start frame per part."""
    starts, position = [], 0
    with wave.open(str(destination), "wb") as out:
        out.setnchannels(2); out.setsampwidth(2); out.setframerate(SAMPLE_RATE)
        for path, silence in parts:
            starts.append(position)
            if path is not None:
                with wave.open(str(path), "rb") as part:
                    while chunk := part.readframes(1 << 18):
                        out.writeframesraw(chunk)
                    position += part.getnframes()
            remaining = silence
            while remaining > 0:
                frames = min(remaining, 1 << 18)
                out.writeframesraw(b"\0" * frames * 4)
                remaining -= frames
            position += silence
    return starts


# --------------------------------------------------------------------------- #
# Marathon
# --------------------------------------------------------------------------- #
def build_marathon(core, songs, name, creator, od, hp, entries, ffmpeg, bitrate=192, version="Marathon",
                   weights=None, rows=None, gap=4, per_row=4, focus=None, report=lambda *args: None):
    """Create Songs/<Various Artists - name>/ with one .osu, audio.mp3 and a collage background.

    entries: dicts with path, rate, pitch, break_after (seconds of silence after that song)
    and optionally background (an image path that replaces the map's own background).
    """
    name, creator, od, hp, folder_name = validate_settings(core, name, creator, od, hp)
    version = version.strip() or "Marathon"
    if any(c in version for c in "\r\n"):
        raise ValueError("Difficulty name must be on a single line.")
    if len(entries) < 2:
        raise ValueError("Add at least two charts to make a marathon.")
    if not ffmpeg:
        raise ValueError("FFmpeg is required to join the songs.")
    songs = Path(songs).resolve()
    if not songs.is_dir():
        raise ValueError("Choose your osu! Songs folder.")
    destination = songs / folder_name
    if destination.exists():
        raise ValueError(f"Folder already exists: {folder_name}. Choose a new marathon name.")

    charts, keys = [], None
    for entry in entries:
        path = Path(entry["path"]).resolve()
        header, sections = core.parse_osu(str(path))
        general, meta = core.sec(sections, "General"), core.sec(sections, "Metadata")
        title = core.kv(meta, "Title") or path.stem
        if core.kv(general, "Mode") != "3":
            raise ValueError(f"{title}: marathons support osu!mania charts only.")
        chart_keys = core.kv(core.sec(sections, "Difficulty"), "CircleSize")
        if keys is None:
            keys = chart_keys
        elif chart_keys != keys:
            raise ValueError(f"{title} is {chart_keys}K but the marathon is {keys}K. All charts need the same key count.")
        rate = float(entry.get("rate", 1))
        if rate != 1:
            core.validate_rate(rate)
        brk = float(entry.get("break_after", 0))
        if not math.isfinite(brk) or not 0 <= brk <= 600:
            raise ValueError(f"{title}: break must be between 0 and 600 seconds.")
        audio = safe_source(path.parent, core.kv(general, "AudioFilename") or "")
        try:
            # A picture the user chose for this tile replaces the map's own background.
            bg = entry.get("background") or background_path(core, {"path": str(path)})
        except ValueError:
            bg = None
        charts.append(dict(path=path, sections=sections, title=title, artist=core.kv(meta, "Artist") or "",
                           rate=rate, pitch=bool(entry.get("pitch", True)), break_after=brk, audio=audio, bg=bg))

    with tempfile.TemporaryDirectory(prefix="jatotrainer-marathon-") as temporary:
        work = Path(temporary)
        stage = work / "stage"
        stage.mkdir()
        report(0.02, "Decoding songs…")
        wavs = [work / f"part{i}.wav" for i in range(len(charts))]
        with ThreadPoolExecutor(max_workers=min(len(charts), 8)) as pool:
            jobs = [pool.submit(_decode, core, ffmpeg, c["audio"], wav, c["rate"], c["pitch"]) for c, wav in zip(charts, wavs)]
            for done, job in enumerate(jobs, 1):
                job.result()
                report(0.02 + 0.5 * done / len(jobs), f"Decoded {done}/{len(jobs)} songs")
        last = len(charts) - 1
        starts = _join_wavs([(wav, 0 if i == last else round(c["break_after"] * SAMPLE_RATE))
                             for i, (wav, c) in enumerate(zip(wavs, charts))], work / "marathon.wav")
        offsets = [round(frame * 1000 / SAMPLE_RATE) for frame in starts]
        report(0.6, "Encoding marathon audio…")
        core.make_audio(ffmpeg, str(work / "marathon.wav"), str(stage / "audio.mp3"), 1, False,
                        bitrate=bitrate, allow_original=True)

        report(0.85, "Merging charts…")
        timing, objects, breaks, spans = [], [], [], []
        for i, (chart, offset) in enumerate(zip(charts, offsets)):
            sections, rate = chart["sections"], chart["rate"]
            floor = spans[-1][1] + 1 if spans else 0
            timing += _shift_timing(core.scale_timing(core.sec(sections, "TimingPoints"), rate), offset, floor)
            shifted = _shift_objects(core.scale_objects(core.sec(sections, "HitObjects"), rate), offset)
            objects += shifted
            breaks += _shift_breaks(core, core.sec(sections, "Events"), rate, offset)
            spans.append(object_span(core, [("HitObjects", shifted)]))
        for (_, end), (start, _) in zip(spans, spans[1:]):
            # Mark the gap between songs as a break when it is long enough to be one.
            if start - end >= 3000:
                breaks.append(f"2,{end + 1000},{start - 1000}")
        timing.sort(key=lambda line: int(line.split(",")[0]))

        report(0.9, "Building background…")
        images = []
        for chart in charts:
            try:
                with Image.open(chart["bg"]) as image:
                    images.append(image.convert("RGB"))
            except (OSError, TypeError, AttributeError):
                images.append(None)
        if weights is None:
            weights = auto_weights([s[1] - s[0] for s in spans])
        rects = collage_layout(weights, rows, SIZE, gap, per_row)
        save_background(render_collage(images, rects, SIZE, focus), stage / "background.jpg")

        first = charts[0]["sections"]
        preview = core.kv(core.sec(first, "General"), "PreviewTime")
        preview = core.tm(preview, charts[0]["rate"]) if preview and preview != "-1" else "-1"
        titles = " ".join(dict.fromkeys(c["title"] for c in charts))
        artists = " ".join(dict.fromkeys(c["artist"] for c in charts if c["artist"]))
        tags = " ".join(f"{titles} {artists} marathon jatotrainer".split())
        sections_out = [
            ("General", ["AudioFilename: audio.mp3", "AudioLeadIn: 0", f"PreviewTime: {preview}", "Countdown: 0",
                         "SampleSet: Normal", "StackLeniency: 0.7", "Mode: 3", "LetterboxInBreaks: 0",
                         "SpecialStyle: 0", "WidescreenStoryboard: 0"]),
            ("Editor", ["Bookmarks: " + ",".join(str(o) for o in offsets), "DistanceSpacing: 1", "BeatDivisor: 4",
                        "GridSize: 4", "TimelineZoom: 1"]),
            ("Metadata", [f"Title:{plain_title(name)}", f"TitleUnicode:{name}", "Artist:Various Artists",
                          "ArtistUnicode:Various Artists", f"Creator:{creator}", f"Version:{version}", "Source:",
                          f"Tags:{tags}", "BeatmapID:0", "BeatmapSetID:-1"]),
            ("Difficulty", [f"HPDrainRate:{format(hp, 'g')}", f"CircleSize:{keys}", f"OverallDifficulty:{format(od, 'g')}",
                            "ApproachRate:5", "SliderMultiplier:1.4", "SliderTickRate:1"]),
            ("Events", ["//Background and Video events", '0,0,"background.jpg",0,0', "//Break Periods", *breaks]),
            ("TimingPoints", timing),
            ("HitObjects", objects),
        ]
        text = "osu file format v14\r\n" + "".join(f"\r\n[{n}]\r\n" + "\r\n".join(lines) + "\r\n" for n, lines in sections_out)
        filename = core.safe_name(f"Various Artists - {plain_title(name)} ({creator}) [{version}]") + ".osu"
        (stage / filename).write_bytes(text.encode("utf-8"))

        # Exclusive directory creation prevents overwriting an existing set.
        destination.mkdir()
        try:
            for file in stage.iterdir():
                shutil.copyfile(file, destination / file.name)
        except BaseException:
            shutil.rmtree(destination)
            raise
    report(1, f"Created {destination}")
    return str(destination), offsets
