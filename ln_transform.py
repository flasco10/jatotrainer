"""Bidirectional osu!mania Long Note (LN) <-> tap Note conversion."""
import bisect
import math

LN_MODES = ("off", "ln_to_notes", "notes_to_ln")
LN_MODE_LABELS = {
    "off": "Off",
    "ln_to_notes": "LN → Notes",
    "notes_to_ln": "Notes → LN",
}
LN_LABEL_TO_MODE = {label: key for key, label in LN_MODE_LABELS.items()}

SNAP_DENOMINATORS = {
    "1/1": 1,
    "1/2": 2,
    "1/3": 3,
    "1/4": 4,
    "1/6": 6,
    "1/8": 8,
}

LN_DENSITIES = ("head", "head_tail", "1/1", "1/2", "1/3", "1/4", "1/6", "1/8")
LN_DENSITY_LABELS = {
    "head": "Head only",
    "head_tail": "Head + Tail",
    "1/1": "1/1 beat",
    "1/2": "1/2 beat",
    "1/3": "1/3 beat",
    "1/4": "1/4 beat",
    "1/6": "1/6 beat",
    "1/8": "1/8 beat",
}
LN_LABEL_TO_DENSITY = {label: key for key, label in LN_DENSITY_LABELS.items()}

LN_GAPS = ("1/1", "1/2", "1/3", "1/4", "1/6", "1/8")
LN_GAP_LABELS = {key: f"{key} beat" for key in LN_GAPS}
LN_LABEL_TO_GAP = {label: key for key, label in LN_GAP_LABELS.items()}

DEFAULT_MODE = "off"
DEFAULT_DENSITY = "head"
DEFAULT_GAP = "1/4"

MIN_HOLD_MS = 15
MIN_NOTE_GAP_MS = 5
DEFAULT_BEAT_MS = 500.0


def validate_options(mode=DEFAULT_MODE, density=DEFAULT_DENSITY, gap=DEFAULT_GAP):
    """Validate and normalize LN conversion options."""
    mode = DEFAULT_MODE if mode is None else mode
    density = DEFAULT_DENSITY if density is None else density
    gap = DEFAULT_GAP if gap is None else gap
    if mode not in LN_MODES:
        raise ValueError(f"Unsupported LN conversion mode: {mode}")
    if density not in LN_DENSITIES:
        raise ValueError(f"Unsupported LN->Notes density: {density}")
    if gap not in LN_GAPS:
        raise ValueError(f"Unsupported Notes->LN release gap: {gap}")
    return mode, density, gap


def mode_tag(mode=DEFAULT_MODE, density=DEFAULT_DENSITY, gap=DEFAULT_GAP):
    """Short difficulty-name tag describing the active LN conversion."""
    mode, density, gap = validate_options(mode, density, gap)
    if mode == "off":
        return ""
    if mode == "ln_to_notes":
        if density == "head":
            return "NoLN"
        if density == "head_tail":
            return "NoLN H+T"
        return f"NoLN {density}"
    return f"FullLN {gap}"


def parse_red_timing_points(timing_lines):
    """Return sorted (time_ms, beat_length_ms) pairs for uninherited timing points."""
    points = []
    for line in timing_lines:
        parts = line.split(",")
        if len(parts) < 2 or not line.strip():
            continue
        try:
            tp_time = float(parts[0])
            beat_length = float(parts[1])
        except ValueError:
            continue
        uninherited = parts[6].strip() != "0" if len(parts) > 6 else beat_length > 0
        if uninherited and math.isfinite(tp_time) and math.isfinite(beat_length) and beat_length > 0:
            points.append((tp_time, beat_length))
    points.sort(key=lambda item: item[0])
    return points


def beat_length_at(red_points, time_ms):
    """Active beat length (ms) at `time_ms`, falling back to first point or 120 BPM."""
    if not red_points:
        return DEFAULT_BEAT_MS
    idx = bisect.bisect_right(red_points, (time_ms, math.inf)) - 1
    if idx < 0:
        return red_points[0][1]
    return red_points[idx][1]


def parse_breaks(event_lines):
    """Return sorted (start_ms, end_ms) break intervals from [Events]."""
    breaks = []
    for line in event_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        parts = stripped.split(",")
        kind = parts[0].strip(" _")
        if kind in ("2", "Break") and len(parts) >= 3:
            try:
                start_ms = int(round(float(parts[1])))
                end_ms = int(round(float(parts[2])))
            except ValueError:
                continue
            breaks.append((start_ms, end_ms))
    breaks.sort()
    return breaks


def _column(x, keys):
    return max(0, min(keys - 1, int(math.floor(x * keys / 512))))


def _parse_hit_object(line, keys):
    parts = line.split(",")
    if len(parts) < 5 or not line.strip():
        return None
    try:
        x = int(round(float(parts[0])))
        y = int(round(float(parts[1])))
        time = int(round(float(parts[2])))
        typ = int(parts[3])
        hitsound = int(parts[4])
    except ValueError:
        return None
    is_hold = bool(typ & 128)
    end_time = None
    hit_sample = "0:0:0:0:"
    if is_hold:
        if len(parts) > 5 and parts[5].strip():
            hold_parts = parts[5].split(":", 1)
            try:
                end_time = int(round(float(hold_parts[0])))
            except ValueError:
                return None
            hit_sample = hold_parts[1] if len(hold_parts) > 1 and hold_parts[1] else "0:0:0:0:"
        else:
            end_time = time
    elif len(parts) > 5 and parts[5].strip():
        hit_sample = ",".join(parts[5:])
    return {
        "x": x,
        "y": y,
        "time": time,
        "typ": typ,
        "hitsound": hitsound,
        "is_hold": is_hold,
        "end_time": end_time,
        "hit_sample": hit_sample,
        "col": _column(x, keys),
        "raw": line,
    }


def _format_tap(x, y, time, typ, hitsound, hit_sample):
    return f"{x},{y},{time},{typ},{hitsound},{hit_sample}"


def _format_hold(x, y, time, typ, hitsound, end_time, hit_sample):
    return f"{x},{y},{time},{typ},{hitsound},{end_time}:{hit_sample}"


def _has_close(sorted_times, target, min_gap=MIN_NOTE_GAP_MS):
    idx = bisect.bisect_left(sorted_times, target)
    if idx > 0 and target - sorted_times[idx - 1] < min_gap:
        return True
    if idx < len(sorted_times) and sorted_times[idx] - target < min_gap:
        return True
    return False


def _ln_to_notes(parsed, passthrough, red_points, density):
    occupied = {}
    for _, obj in parsed:
        occupied.setdefault(obj["col"], []).append(obj["time"])
    for times in occupied.values():
        times.sort()

    emitted = []
    seq = 0
    for order_idx, obj in parsed:
        if not obj["is_hold"]:
            emitted.append((obj["time"], obj["col"], seq, obj["raw"]))
            seq += 1
            continue

        head_typ = (obj["typ"] & ~128) | 1
        emitted.append((
            obj["time"],
            obj["col"],
            seq,
            _format_tap(obj["x"], obj["y"], obj["time"], head_typ, obj["hitsound"], obj["hit_sample"]),
        ))
        seq += 1

        end = obj["end_time"]
        start = obj["time"]
        if density == "head" or end is None or end <= start:
            continue

        candidates = []
        if density == "head_tail":
            candidates.append(end)
        else:
            denom = SNAP_DENOMINATORS[density]
            t = float(start) + max(1.0, beat_length_at(red_points, float(start)) / denom)
            prev_t = start
            while int(round(t)) <= end + 2:
                nt = min(end, int(round(t)))
                if nt > prev_t:
                    candidates.append(nt)
                    prev_t = nt
                t += max(1.0, beat_length_at(red_points, t) / denom)

        col_times = occupied[obj["col"]]
        for nt in candidates:
            if _has_close(col_times, nt, MIN_NOTE_GAP_MS):
                continue
            bisect.insort(col_times, nt)
            emitted.append((
                nt,
                obj["col"],
                seq,
                _format_tap(obj["x"], obj["y"], nt, 1, 0, "0:0:0:0:"),
            ))
            seq += 1

    emitted.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in emitted] + [line for _, line in passthrough]


def _notes_to_ln(parsed, passthrough, red_points, breaks, gap):
    denom = SNAP_DENOMINATORS[gap]
    by_col = {}
    for order_idx, obj in parsed:
        by_col.setdefault(obj["col"], []).append((order_idx, obj))

    emitted = []
    for col, items in by_col.items():
        items.sort(key=lambda pair: (pair[1]["time"], pair[0]))
        prev_end = -math.inf
        for i, (order_idx, obj) in enumerate(items):
            if obj["is_hold"]:
                emitted.append((obj["time"], col, order_idx, obj["raw"]))
                if obj["end_time"] is not None:
                    prev_end = max(prev_end, obj["end_time"])
                continue

            start = obj["time"]
            if start <= prev_end:
                emitted.append((start, col, order_idx, obj["raw"]))
                continue

            beat_ms = beat_length_at(red_points, start)
            gap_ms = beat_ms / denom
            if i + 1 < len(items):
                next_time = items[i + 1][1]["time"]
                end = int(round(next_time - gap_ms))
            else:
                end = int(round(start + beat_ms))

            for b_start, _ in breaks:
                if start < b_start < end:
                    end = b_start

            if end - start >= MIN_HOLD_MS:
                ln_typ = (obj["typ"] & ~3) | 128
                emitted.append((
                    start,
                    col,
                    order_idx,
                    _format_hold(obj["x"], obj["y"], start, ln_typ, obj["hitsound"], end, obj["hit_sample"]),
                ))
                prev_end = end
            else:
                emitted.append((start, col, order_idx, obj["raw"]))

    emitted.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in emitted] + [line for _, line in passthrough]


def transform_hit_objects(hit_lines, timing_lines, keys=4, mode=DEFAULT_MODE, density=DEFAULT_DENSITY, gap=DEFAULT_GAP, event_lines=None):
    """Transform [HitObjects] lines between tap notes and osu!mania long notes."""
    mode, density, gap = validate_options(mode, density, gap)
    if mode == "off":
        return list(hit_lines)

    key_count = max(1, int(round(float(keys or 4))))
    red_points = parse_red_timing_points(timing_lines)
    breaks = parse_breaks(event_lines or ())

    parsed = []
    passthrough = []
    for idx, line in enumerate(hit_lines):
        obj = _parse_hit_object(line, key_count)
        if obj is None:
            if line.strip():
                passthrough.append((idx, line))
        else:
            parsed.append((idx, obj))

    if mode == "ln_to_notes":
        return _ln_to_notes(parsed, passthrough, red_points, density)
    return _notes_to_ln(parsed, passthrough, red_points, breaks, gap)
