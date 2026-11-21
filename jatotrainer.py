#!/usr/bin/env python3
"""
jatotrainer - generate several rates of an osu!mania map at once,
with a custom difficulty-name format. Scans your Songs folder automatically.
"""
import json
import hashlib
import math
import tempfile
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import tkinter as tk
from tkinter import filedialog, ttk

from ffmpeg_setup import DOWNLOAD_URL, EXE_NAME, install_ffmpeg, managed_ffmpeg_path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk

APP_NAME = "jatotrainer"
GEN_TAG = "mmr-gen"  # added to Tags so generated maps are hidden from the list
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".mania_multirate.json")
AUDIO_CACHE_PATH = os.path.join(os.path.expanduser("~"), ".mania_multirate_audio_cache.json")
AUDIO_CACHE_LOCK = threading.RLock()
CACHE_PATH = os.path.join(os.path.expanduser("~"), ".mania_multirate_cache.json")

ACCENT = "#4387ff"
ACCENT_HOVER = "#6576ef"
BG_PANEL = "#0f1320"
BG_MAIN = "#080a12"

LIST_LIMIT = 3000  # max rows shown in the list (search/auto-select narrows it)
DEFAULT_FORMAT = "{diff} ({rate}x)"
FORMAT_PRESETS = [
    "{diff} x{rate} [{bpm}]",
    "{diff} x{rate}",
    "{diff} ({rate}x)",
    "{diff} {rate}x",
    "{rate}x {diff}",
    "{diff} [{bpm} BPM]",
    "{diff} - {rate}x ({bpm}bpm)",
    "{diff} {pct}%",
]
QUICK_RATES = [f"{x / 100:g}" for x in range(85, 141, 5) if x != 100]  # 0.85 ... 1.4 in 0.05 steps (1.0 = original)


# --------------------------------------------------------------------------- #
# Config / ffmpeg / Songs folder discovery
# --------------------------------------------------------------------------- #
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def find_ffmpeg():
    here = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    for p in (os.path.join(here, "ffmpeg.exe"), os.path.join(here, "build-tools", "audio", "ffmpeg.exe"),
              os.path.join(here, "ffmpeg"), str(managed_ffmpeg_path())):
        if os.path.isfile(p):
            return p
    p = shutil.which("ffmpeg")
    if p:
        return p
    return None


def _running_osu_dir():
    """Folder of the running osu!.exe (Windows only)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.startswith("osu!"):
                    pid = wintypes.DWORD()
                    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
                    if h:
                        size = wintypes.DWORD(1024)
                        pbuf = ctypes.create_unicode_buffer(1024)
                        if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
                            if os.path.basename(pbuf.value).lower() == "osu!.exe":
                                found.append(os.path.dirname(pbuf.value))
                        ctypes.windll.kernel32.CloseHandle(h)
            return True

        ctypes.windll.user32.EnumWindows(cb, 0)
        return found[0] if found else None
    except Exception:
        return None


def _registry_osu_dir():
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"osu\shell\open\command") as k:
            cmd = winreg.QueryValue(k, None)
        m = re.match(r'\s*"?([^"]+?osu!\.exe)', cmd, re.I)
        return os.path.dirname(m.group(1)) if m else None
    except Exception:
        return None


def songs_from_root(root):
    """Given an osu! install folder, return its Songs folder (honours BeatmapDirectory)."""
    songs = os.path.join(root, "Songs")
    try:
        for fn in os.listdir(root):
            if fn.startswith("osu!.") and fn.endswith(".cfg"):
                with open(os.path.join(root, fn), "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        m = re.match(r"\s*BeatmapDirectory\s*=\s*(.+?)\s*$", line)
                        if m:
                            d = m.group(1).strip().strip('"')
                            songs = d if os.path.isabs(d) else os.path.join(root, d)
    except Exception:
        pass
    return songs if os.path.isdir(songs) else None


def normalize_songs_dir(d):
    """If the user picked the osu! folder instead of Songs, descend into it."""
    if not d:
        return d
    sub = songs_from_root(d)
    if sub and not any(f.lower().endswith(".osu") for f in os.listdir(d)):
        # only treat as install root if it looks like one
        if os.path.isfile(os.path.join(d, "osu!.exe")) or os.path.isdir(os.path.join(d, "Songs")):
            return sub
    return d


def find_songs_folder():
    """osu!stable Songs folder: running process -> registry -> common locations -> drive scan."""
    roots = []
    for r in (_running_osu_dir(), _registry_osu_dir()):
        if r:
            roots.append(r)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(os.path.join(local, "osu!"))
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(env):
            roots.append(os.path.join(os.environ[env], "osu!"))
    roots.append(os.path.expanduser("~/osu!"))
    if sys.platform == "win32":
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            for sub in ("osu!", r"Games\osu!", "osu", r"Program Files\osu!"):
                roots.append(f"{letter}:\\{sub}")
    seen = set()
    for root in roots:
        if root in seen or not os.path.isdir(root):
            continue
        seen.add(root)
        songs = songs_from_root(root)
        if songs:
            return songs
    return None


def lazer_detected():
    base = os.environ.get("APPDATA")
    return bool(base and os.path.isfile(os.path.join(base, "osu", "client.realm")))


def osu_window_title():
    """Title of the running osu! stable window (Windows only), else None."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    titles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.startswith("osu!"):
                titles.append(buf.value)
        return True

    ctypes.windll.user32.EnumWindows(cb, 0)
    for t in titles:
        if " - " in t:
            return t
    return None


# --------------------------------------------------------------------------- #
# tosu / gosumemory client (reads the map selected in osu! via its local API)
# --------------------------------------------------------------------------- #
TOSU_URLS = ("http://127.0.0.1:24050/json/v2", "http://127.0.0.1:24050/json")


def fetch_tosu():
    """Return the parsed JSON from a running tosu/gosumemory, or None."""
    for url in TOSU_URLS:
        try:
            with urllib.request.urlopen(url, timeout=0.8) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception:
            continue
    return None


def current_selection():
    """Use the bundled reader, then tosu/gosumemory or the gameplay title."""
    from piotrekol_reader import reader
    selected = reader.poll()
    if selected:
        return selected
    selected = extract_selection(fetch_tosu())
    if selected:
        return selected
    match = re.match(r"^osu!\s*-\s*(.+?) - (.+) \[(.+)\]\s*$", osu_window_title() or "")
    if match:
        artist, title, version = match.groups()
        return dict(path=None,folder=None,file=None,songs=None,bid=0,artist=artist,title=title,
                    mapper=None,version=version,md5=None)
    return None


def _g(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def extract_selection(data):
    """Normalise tosu v2 / v1(gosumemory) JSON into a small dict."""
    if not isinstance(data, dict):
        return None
    sel = dict(path=None, folder=None, file=None, songs=None, bid=0, artist=None, title=None,
               mapper=None, version=None, md5=None)
    # v2
    sel["path"] = _g(data, "directPath", "beatmapFile")
    sel["folder"] = _g(data, "folders", "beatmap")
    sel["file"] = _g(data, "files", "beatmap")
    sel["songs"] = _g(data, "folders", "songs")
    bm = data.get("beatmap") if isinstance(data.get("beatmap"), dict) else {}
    sel["bid"] = bm.get("id") or 0
    sel["artist"], sel["title"] = bm.get("artist"), bm.get("title")
    sel["mapper"], sel["version"] = bm.get("mapper"), bm.get("version")
    sel["md5"] = bm.get("checksum") or bm.get("md5")
    # v1 / gosumemory
    bm1 = _g(data, "menu", "bm")
    if isinstance(bm1, dict):
        sel["folder"] = sel["folder"] or _g(bm1, "path", "folder")
        sel["file"] = sel["file"] or _g(bm1, "path", "file")
        sel["bid"] = sel["bid"] or bm1.get("id") or 0
        sel["md5"] = sel["md5"] or bm1.get("md5") or bm1.get("checksum")
        md = bm1.get("metadata") or {}
        sel["artist"] = sel["artist"] or md.get("artist")
        sel["title"] = sel["title"] or md.get("title")
        sel["mapper"] = sel["mapper"] or md.get("mapper")
        sel["version"] = sel["version"] or md.get("difficulty")
        sel["songs"] = sel["songs"] or _g(data, "settings", "folders", "songs")
    if not (sel["path"] or sel["file"] or sel["bid"] or (sel["title"] and sel["version"])):
        return None
    return sel


def _norm(p):
    return os.path.normcase(os.path.normpath(p)) if p else ""


def _simp(x):
    return re.sub(r"[\W_]+", "", (x or "").casefold())


def file_md5(path):
    try:
        import hashlib
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return None


def _pick(hits, sel):
    """Several candidates? Use the beatmap hash from osu! to find the exact file."""
    if len(hits) > 1 and sel.get("md5") and isinstance(sel["md5"], str) and len(sel["md5"]) == 32:
        exact = [m for m in hits if file_md5(m["path"]) == sel["md5"].lower()]
        if exact:
            return exact
    return hits


def match_selection(maps, sel, songs_dir):
    """Find the indexed map for tosu's selection. Returns (map or None, n_candidates)."""
    if not sel:
        return None, 0
    by_path = {_norm(m["path"]): m for m in maps}
    cands = []
    if sel["path"]:
        cands.append(sel["path"])
    if sel["file"] and sel["folder"]:
        for base in (sel["songs"], songs_dir):
            if base:
                cands.append(os.path.join(base, sel["folder"], sel["file"]))
        if os.path.isabs(sel["folder"]):
            cands.append(os.path.join(sel["folder"], sel["file"]))
    for c in cands:
        m = by_path.get(_norm(c))
        if m:
            return m, 1
    if sel["file"]:  # same filename (in a folder of the same name, if known)
        hits = [m for m in maps if os.path.basename(m["path"]).lower() == str(sel["file"]).lower()
                and (not sel["folder"] or os.path.basename(os.path.dirname(m["path"])).lower() == str(sel["folder"]).lower())]
        hits = _pick(hits, sel)
        if hits:
            return hits[0], len(hits)
    if sel["bid"]:
        hits = _pick([m for m in maps if m.get("bid") == sel["bid"]], sel)
        if hits and len(hits) == 1:
            return hits[0], 1
    # metadata: title + difficulty must match; artist / mapper / id raise the score
    ver, title = _simp(sel["version"]), _simp(sel["title"])
    if ver and title:
        scored = []
        for m in maps:
            if _simp(m["version"]) == ver and _simp(m["title"]) == title:
                score = (2 if sel["artist"] and _simp(m["artist"]) == _simp(sel["artist"]) else 0) \
                    + (1 if sel["mapper"] and _simp(m["creator"]) == _simp(sel["mapper"]) else 0) \
                    + (3 if sel["bid"] and m.get("bid") == sel["bid"] else 0) \
                    + (0 if m.get("gen") else 0.5)
                scored.append((score, m))
        if scored:
            best = max(s_ for s_, _ in scored)
            top = _pick([m for s_, m in scored if s_ == best], sel)
            return top[0], len(top)
    return None, 0


# --------------------------------------------------------------------------- #
# .osu parsing
# --------------------------------------------------------------------------- #
def kv(lines, key):
    for l in lines:
        if l.startswith(key + ":"):
            return l.split(":", 1)[1].strip()
    return None


def set_kv(lines, key, value):
    for i, l in enumerate(lines):
        if l.startswith(key + ":"):
            lines[i] = f"{key}: {value}" if key in ("AudioFilename", "PreviewTime") else f"{key}:{value}"
            return
    lines.append(f"{key}:{value}")


def fmt_rate(r):
    return repr(float(r)).removesuffix(".0")


def main_bpm(timing):
    for l in timing:
        p = l.split(",")
        if len(p) >= 2:
            try:
                beat = float(p[1])
            except ValueError:
                continue
            unin = p[6].strip() != "0" if len(p) > 6 else beat > 0
            if unin and beat > 0:
                return 60000.0 / beat
    return 0.0


def read_header_info(path):
    """Fast scan: returns dict for mania maps, None otherwise."""
    section, general, meta, diff, timing = None, [], [], [], []
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\r\n")
            m = re.match(r"^\[(.+)\]\s*$", line)
            if m:
                section = m.group(1)
                if section == "HitObjects":
                    break
                continue
            if section == "General":
                general.append(line)
            elif section == "Metadata":
                meta.append(line)
            elif section == "Difficulty":
                diff.append(line)
            elif section == "TimingPoints":
                timing.append(line)
    if kv(general, "Mode") != "3":
        return None
    tags = kv(meta, "Tags") or ""
    return dict(
        gen=GEN_TAG in tags.split(),
        path=path,
        artist=kv(meta, "Artist") or "?",
        title=kv(meta, "Title") or "?",
        creator=kv(meta, "Creator") or "?",
        version=kv(meta, "Version") or "?",
        bid=int(kv(meta, "BeatmapID") or 0) if (kv(meta, "BeatmapID") or "0").lstrip("-").isdigit() else 0,
        keys=int(float(kv(diff, "CircleSize") or 4)),
        od=kv(diff, "OverallDifficulty") or "?",
        bpm=int(round(main_bpm(timing))),
    )


def scan_songs(songs_dir, progress=None):
    """Returns (maps, stats). Looks in Songs/<set>/*.osu, exactly like osu! does."""
    cache = load_json(CACHE_PATH, {})
    if not isinstance(cache, dict):
        cache = {}
    new_cache, maps = {}, []
    stats = dict(files=0, mania=0, errors=0, folders=0)
    folders = [e.path for e in os.scandir(songs_dir) if e.is_dir()]
    stats["folders"] = len(folders)
    total = len(folders)

    def osu_files(folder):  # osu! stable only reads Songs/<set>/*.osu, not nested folders
        for e in os.scandir(folder):
            if e.is_file() and e.name.lower().endswith(".osu"):
                yield e

    for i, folder in enumerate(folders):
        try:
            for e in osu_files(folder):
                stats["files"] += 1
                st = e.stat()
                signature = [st.st_mtime_ns, st.st_ctime_ns, st.st_size]
                c = cache.get(e.path)
                if isinstance(c, dict) and c.get("signature") == signature and "info" in c and (c["info"] is None or "gen" in c["info"]):
                    info = c["info"]
                else:
                    try:
                        info = read_header_info(e.path)
                    except Exception:
                        info = None
                        stats["errors"] += 1
                new_cache[e.path] = {"signature": signature, "info": info}
                if info:
                    maps.append(info)
                    if not info.get("gen"):
                        stats["mania"] += 1
        except OSError:
            stats["errors"] += 1
        if progress and i % 50 == 0:
            progress(i, total)
    save_json(CACHE_PATH, new_cache)
    return maps, stats


# --------------------------------------------------------------------------- #
# Rate generation (mania)
# --------------------------------------------------------------------------- #
def parse_osu(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return parse_osu_text(f.read())


def parse_osu_text(text):
    """Parse chart text in memory without platform newline conversion."""
    lines = text.lstrip("\ufeff").splitlines()
    header = lines[0] if lines else "osu file format v14"
    sections, name, cur = [], None, []
    for line in lines[1:]:
        m = re.match(r"^\[(.+)\]\s*$", line)
        if m:
            if name is not None:
                while cur and not cur[-1].strip():
                    cur.pop()
                sections.append((name, cur))
            name, cur = m.group(1), []
        else:
            cur.append(line)
    if name is not None:
        while cur and not cur[-1].strip():
            cur.pop()
        sections.append((name, cur))
    return header, sections


def sec(sections, name):
    for n, l in sections:
        if n == name:
            return l
    return []


def tm(v, rate):
    return str(int(round(float(v) / rate)))


def scale_timing(lines, rate):
    out = []
    for l in lines:
        p = l.split(",")
        if len(p) < 2 or not l.strip():
            out.append(l)
            continue
        p[0] = tm(p[0], rate)
        beat = float(p[1])
        unin = p[6].strip() != "0" if len(p) > 6 else beat > 0
        if unin and beat > 0:
            p[1] = f"{beat / rate:.12g}"
        out.append(",".join(p))
    return out


def scale_events(lines, rate):
    """Scale event and storyboard times, including relative loop/trigger commands."""
    out = []
    for line in lines:
        # Split outside quoted filenames; preserve quotes and indentation.
        p = re.split(r',(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)', line)
        kind = p[0].strip(" _")
        indices = []
        if line.lstrip().startswith("//"):
            out.append(line)
            continue
        if kind in ("2", "Break"):
            indices = [1, 2]
        elif kind in ("1", "Video", "5", "Sample", "0", "Background"):
            indices = [1]
        elif kind == "L":
            indices = [1]  # loop count is not a timestamp
        elif kind == "T":
            indices = [2, 3]  # trigger name and group number are unchanged
        elif kind in ("F", "M", "MX", "MY", "S", "V", "R", "C", "P"):
            indices = [2, 3]  # easing is unchanged; empty end time is legal
        elif kind in ("Animation", "6"):
            indices = [7]  # frame delay
        for i in indices:
            if i < len(p) and p[i].strip():
                p[i] = tm(p[i], rate)
        out.append(",".join(p))
    return out


def scale_objects(lines, rate):
    out = []
    for l in lines:
        p = l.split(",")
        if len(p) < 5:
            out.append(l)
            continue
        p[2] = tm(p[2], rate)
        typ = int(p[3])
        if typ & 128 and len(p) > 5:  # mania hold: endTime:hitSample
            parts = p[5].split(":", 1)
            parts[0] = tm(parts[0], rate)
            p[5] = ":".join(parts)
        out.append(",".join(p))
    return out


def scale_od(od, rate):
    """Scale OD like DT/HT would (mania 300g window = 64 - 3*OD ms)."""
    w = (64 - 3 * float(od)) / rate
    return round(max(0, min(10, (64 - w) / 3)), 1)


def safe_name(s):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s).rstrip(" .")


def format_version(fmt, orig_ver, rate, orig_bpm, od):
    return fmt.format(
        diff=orig_ver, rate=fmt_rate(rate), bpm=int(round(orig_bpm * rate)),
        bpm_orig=int(round(orig_bpm)), od=od, pct=f"{int(round((rate - 1) * 100)):+d}",
    )


def build_rate(header, sections, rate, fmt, scale_od_flag, audio_name=None, od_override=None, hp_override=None):
    validate_rate(rate)
    secs = [(n, list(l)) for n, l in sections]
    gen, meta, diff, timing = sec(secs, "General"), sec(secs, "Metadata"), sec(secs, "Difficulty"), sec(secs, "TimingPoints")
    orig_bpm = main_bpm(timing)
    orig_ver = kv(meta, "Version") or "Unknown"
    audio = kv(gen, "AudioFilename") or "audio.mp3"
    new_audio = audio_name or f"{os.path.splitext(audio)[0]}_{fmt_rate(rate)}x.mp3"

    if od_override is not None:
        value = float(od_override)
        if not math.isfinite(value) or not 0 <= value <= 10:
            raise ValueError("OD must be between 0 and 10")
        set_kv(diff, "OverallDifficulty", format(value, "g"))
    elif scale_od_flag and kv(diff, "OverallDifficulty") is not None:
        set_kv(diff, "OverallDifficulty", scale_od(kv(diff, "OverallDifficulty"), rate))

    if hp_override is not None:
        value = float(hp_override)
        if not math.isfinite(value) or not 0 <= value <= 10:
            raise ValueError("HP must be between 0 and 10")
        set_kv(diff, "HPDrainRate", format(value, "g"))

    new_ver = format_version(fmt, orig_ver, rate, orig_bpm, kv(diff, "OverallDifficulty") or "?")
    set_kv(gen, "AudioFilename", new_audio)
    prev = kv(gen, "PreviewTime")
    if prev and prev != "-1":
        set_kv(gen, "PreviewTime", tm(prev, rate))
    lead = kv(gen, "AudioLeadIn")
    if lead:
        set_kv(gen, "AudioLeadIn", tm(lead, rate))
    set_kv(meta, "Version", new_ver)
    set_kv(meta, "BeatmapID", "0")
    tags = kv(meta, "Tags") or ""
    set_kv(meta, "Tags", (tags + " " + GEN_TAG).strip())

    editor = sec(secs, "Editor")
    bm = kv(editor, "Bookmarks")
    if bm:
        set_kv(editor, "Bookmarks", ",".join(tm(x, rate) for x in bm.split(",") if x.strip()))

    for n, l in secs:
        if n == "TimingPoints":
            l[:] = scale_timing(l, rate)
        elif n == "Events":
            l[:] = scale_events(l, rate)
        elif n == "HitObjects":
            l[:] = scale_objects(l, rate)

    text = header + "\r\n"
    for n, l in secs:
        text += f"\r\n[{n}]\r\n" + "\r\n".join(l) + ("\r\n" if l else "")
    return text, new_ver, audio, new_audio


def validate_rate(rate):
    if not math.isfinite(rate) or not 0.1 <= rate <= 5 or rate == 1:
        raise ValueError("Rate must be finite, between 0.1 and 5, and different from 1.")


def make_audio(ffmpeg, src, dst, rate, pitch, bitrate=320, allow_original=False):
    if rate != 1 or not allow_original:
        validate_rate(rate)
    if not isinstance(bitrate, int) or not 32 <= bitrate <= 320:
        raise ValueError("MP3 bitrate must be between 32 and 320 kbps")
    if pitch:
        # Normalize the input before changing its declared sample rate. This
        # gives the requested speed/pitch for both 44.1 and 48 kHz sources.
        flt = f"aresample=44100,asetrate=44100*{repr(rate)},aresample=44100"
    else:
        stages, r = [], rate
        while r > 2.0:
            stages.append("atempo=2.0"); r /= 2.0
        while r < 0.5:
            stages.append("atempo=0.5"); r /= 0.5
        stages.append(f"atempo={repr(r)}")
        flt = ",".join(stages)
    cmd = [ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-i", src,
           "-map", "0:a:0", "-vn", "-filter:a", flt,
           "-codec:a", "libmp3lame", "-b:a", f"{bitrate}k", "-ar", "44100",
           "-write_xing", "1", "-f", "mp3", dst]
    flags = 0x08000000 if sys.platform == "win32" else 0
    result = subprocess.run(cmd, capture_output=True, check=False, creationflags=flags)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip() or "FFmpeg failed")
    if not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        raise RuntimeError("FFmpeg produced no audio")


def _file_digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _publish_unique(folder, filename, data):
    """Exclusive creation never overwrites a map, even with simultaneous runs."""
    stem, ext = os.path.splitext(filename)
    for n in range(100000):
        candidate = filename if n == 0 else f"{stem} ({n + 1}){ext}"
        path = os.path.join(folder, candidate)
        try:
            f = open(path, "x", encoding="utf-8", newline="")
        except FileExistsError:
            # Exact repeats need no new difficulty, but keep existing bytes.
            with open(path, "r", encoding="utf-8", newline="") as old:
                if old.read() == data:
                    return candidate, False
            continue
        try:
            with f:
                f.write(data)
        except BaseException:
            os.unlink(path)
            raise
        return candidate, True
    raise RuntimeError("Too many output filename collisions")


def _audio_cache_key(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _load_audio_cache():
    records = load_json(AUDIO_CACHE_PATH, {})
    return records if isinstance(records, dict) else {}


def _save_audio_records(updates):
    """Merge and atomically replace the central cache; never silently drop errors."""
    with AUDIO_CACHE_LOCK:
        records = _load_audio_cache()
        records.update(updates)
        directory = os.path.dirname(os.path.abspath(AUDIO_CACHE_PATH))
        fd, temporary = tempfile.mkstemp(prefix=".mmr-cache-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(records, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, AUDIO_CACHE_PATH)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _verified_audio_record(path, record, identity=None):
    return (isinstance(record, dict) and isinstance(record.get("identity"), str)
            and record["identity"].startswith("mmr-audio-")
            and (identity is None or record["identity"] == identity)
            and os.path.isfile(path) and os.path.getsize(path) > 0
            and record.get("sha256") == _file_digest(path))


def _migrate_audio_sidecars(folder, log):
    """Remove only recognized, verified records after their cache write succeeds."""
    updates, migrated = {}, []
    for name in os.listdir(folder):
        if not name.lower().endswith(".mp3.json"):
            continue
        sidecar = os.path.join(folder, name)
        if os.path.islink(sidecar):
            continue
        record = load_json(sidecar, None)
        audio_path = sidecar[:-5]
        if _verified_audio_record(audio_path, record):
            updates[_audio_cache_key(audio_path)] = record
            migrated.append((sidecar, record))
    if not updates:
        return
    _save_audio_records(updates)
    for sidecar, record in migrated:
        # Leave files that another process/user changed during migration.
        if load_json(sidecar, None) == record:
            try:
                os.unlink(sidecar)
            except OSError as e:
                log(f"        cache migrated; could not remove {os.path.basename(sidecar)}: {e}")
    log(f"        migrated {len(migrated)} audio record(s) to the user cache")


def generate(info, rates, fmt, pitch, od_flag, log, ffmpeg, od_override=None, hp_override=None, result=None):
    path = info["path"]
    folder = os.path.dirname(os.path.abspath(path))
    header, sections = parse_osu(path)
    if kv(sec(sections, "General"), "Mode") != "3":
        raise ValueError("Select an osu!mania map")
    audio = kv(sec(sections, "General"), "AudioFilename")
    if not audio:
        raise ValueError("The source map has no AudioFilename")
    src_a = os.path.join(folder, audio)
    if not os.path.isfile(src_a):
        raise FileNotFoundError(f"Source audio missing: {audio}")
    rates = list(dict.fromkeys(rates))
    for rate in rates:
        validate_rate(rate)
    # Stable automatically loads shared .osb files for every difficulty.
    # Scaling that shared file would damage originals; fail rather than
    # silently produce a desynchronized storyboard.
    if any(name.lower().endswith(".osb") for name in os.listdir(folder)):
        raise ValueError("External .osb storyboards are not supported safely. "
                         "Use a separate copy of the beatmap set without the .osb file.")
    events = sec(sections, "Events")
    if any(re.match(r"\s*(?:1|Video)\s*,", line) for line in events):
        raise ValueError("Video playback cannot be rate-scaled by timestamp edits. "
                         "Use a separate copy of the set without its video event.")
    if sec(sections, "Variables") or any("$" in line for line in events):
        raise ValueError("Storyboard variables are not supported; expand them before generating rates.")
    _migrate_audio_sidecars(folder, log)
    audio_records = _load_audio_cache()
    source_hash = _file_digest(src_a)
    for rate in rates:
        identity = f"mmr-audio-v3-cbr320:{source_hash}:{repr(rate)}:{bool(pitch)}"
        original_stem = os.path.splitext(re.split(r"[/\\]", audio)[-1])[0]
        audio_stem = safe_name(original_stem)[:140] or "audio"
        preferred_audio = f"{audio_stem} x{fmt_rate(rate)} mmr"
        # Readable names can collide between pitch modes, source revisions,
        # or different source extensions. Verify each candidate before reuse.
        for number in range(100000):
            suffix = "" if number == 0 else f" ({number + 1})"
            new_audio = f"{preferred_audio}{suffix}.mp3"
            dst_a = os.path.join(folder, new_audio)
            manifest_path = dst_a + ".json"
            manifest = audio_records.get(_audio_cache_key(dst_a), {})
            reusable = _verified_audio_record(dst_a, manifest, identity)
            if reusable or not (os.path.exists(dst_a) or os.path.exists(manifest_path)):
                break
        else:
            raise RuntimeError("Too many audio filename collisions")
        text, ver, _, _ = build_rate(header, sections, rate, fmt, od_flag, new_audio, od_override, hp_override)
        filename = safe_name(f"{info['artist']} - {info['title']} ({info['creator']}) [{ver}]")[:160]
        fname = f"{filename} [mmr-x{fmt_rate(rate)}].osu"
        if reusable:
            log("        verified audio already exists, reused")
        else:
            if not ffmpeg:
                raise RuntimeError("FFmpeg not found. Install FFmpeg and add it to PATH, then restart Jatotrainer. No beatmap was written.")
            fd, temporary = tempfile.mkstemp(prefix=".mmr-", suffix=".mp3", dir=folder)
            os.close(fd)
            try:
                make_audio(ffmpeg, src_a, temporary, rate, pitch)
                # Exclusive creation protects files created since the check.
                with open(temporary, "rb") as src, open(dst_a, "xb") as dst:
                    shutil.copyfileobj(src, dst)
                record = {"identity": identity, "sha256": _file_digest(dst_a)}
                _save_audio_records({_audio_cache_key(dst_a): record})
                audio_records[_audio_cache_key(dst_a)] = record
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            log(f"        audio -> {new_audio}")
        published, created = _publish_unique(folder, fname, text)
        log(f"[{fmt_rate(rate)}x] {'wrote' if created else 'already exists'} {published}")
        output_path = os.path.join(folder, published)
        if not os.path.isfile(output_path) or not os.path.isfile(dst_a):
            raise RuntimeError("Output chart or audio is missing after conversion")
        if result is not None:
            result(dict(path=output_path, version=ver, rate=rate, created=created, audio=dst_a))
        yield rate


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #
def gradient_heading(text):
    """Render the blue-to-violet hero accent at 2x for high-DPI displays."""
    font = None
    for path in (os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "segoeuib.ttf"),
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(path, 38)
            break
        except OSError:
            pass
    if font is None:
        return None
    bounds = font.getbbox(text)
    width, height = bounds[2] - bounds[0] + 4, bounds[3] - bounds[1] + 8
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).text((2 - bounds[0], 4 - bounds[1]), text, font=font, fill=255)
    image = Image.new("RGBA", mask.size)
    draw = ImageDraw.Draw(image)
    for x in range(width):
        t = x / max(1, width - 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip((95, 166, 255), (170, 126, 247)))
        draw.line((x, 0, x, height), fill=color + (255,))
    image.putalpha(mask)
    return ctk.CTkImage(light_image=image, dark_image=image, size=(width // 2, height // 2))


def asset_path(name):
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets", name)


def load_poppins():
    """Register bundled fonts without requiring a system-wide installation."""
    for filename in ("Poppins-Regular.ttf", "Poppins-Bold.ttf"):
        path = asset_path(filename)
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.gdi32.AddFontResourceExW(path, 0x10, 0)
        else:
            ctk.FontManager.load_font(path)
    ctk.ThemeManager.theme["CTkFont"]["family"] = "Poppins"
    from ui_components import install_text_alignment
    install_text_alignment()


class App(ctk.CTk):
    def __init__(self):
        load_poppins()
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title(APP_NAME)
        self.option_add("*Font", "Poppins 10")
        self.logo_icon = ImageTk.PhotoImage(Image.open(asset_path("logo.png")))
        self.iconphoto(True, self.logo_icon)
        if sys.platform == "win32":
            self.after(250, lambda: self.iconbitmap(asset_path("jatotrainer.ico")))
        self.geometry("1240x900")
        self.minsize(1080, 780)
        self.configure(fg_color=BG_MAIN)

        self.cfg = load_json(CONFIG_PATH, {})
        self.songs_dir = normalize_songs_dir(self.cfg.get("songs_dir")) or find_songs_folder()
        self.ffmpeg = find_ffmpeg()
        self.maps, self.visible, self.selected = [], [], None
        self.q = queue.Queue()
        self.busy = False

        self._build_ui()
        if not self.ffmpeg:
            self.after_idle(self.show_ffmpeg_setup)
        self._poll_job = self.after(100, self._poll)
        if self.songs_dir:
            self.start_scan()
        else:
            msg = "Couldn't find your osu! Songs folder - click Browse… and pick it (the folder that contains your map folders)."
            if lazer_detected():
                msg += "\nNote: osu!lazer stores maps differently and isn't supported; this tool needs osu!stable."
            self.status.configure(text=msg)

    def show_ffmpeg_setup(self):
        if getattr(self, "_ffmpeg_dialog", None) and self._ffmpeg_dialog.winfo_exists():
            self._ffmpeg_dialog.lift()
            return
        self.ffmpeg = self.ffmpeg or find_ffmpeg()
        if self.ffmpeg:
            self.ffmpeg_setup_btn.grid_remove()
            return
        dialog = self._ffmpeg_dialog = ctk.CTkToplevel(self)
        dialog.title("FFmpeg setup")
        dialog.configure(fg_color=BG_PANEL)
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.geometry(f"+{self.winfo_rootx()+max(20,(self.winfo_width()-480)//2)}"
                        f"+{self.winfo_rooty()+max(20,(self.winfo_height()-315)//2)}")
        ctk.CTkLabel(dialog, text="FFmpeg not found", font=ctk.CTkFont(size=26, weight="bold")).pack(padx=28, pady=(24, 8))
        ctk.CTkLabel(dialog, text="Jatotrainer needs FFmpeg to change audio speed and compress audio. Download a standalone build and select its ZIP or executable.",
                     wraplength=425, justify="center").pack(padx=28)
        ctk.CTkButton(dialog, text="Download FFmpeg ↗", text_color="#8eb6ff",
                      font=ctk.CTkFont(size=14, underline=True), fg_color="transparent",
                      hover_color="#202b40", command=lambda: webbrowser.open(DOWNLOAD_URL)).pack(pady=12)
        status = ctk.CTkLabel(dialog, text="", text_color="#ff8888", wraplength=425)
        status.pack(padx=20)
        controls = ctk.CTkFrame(dialog, fg_color="transparent")
        controls.pack(padx=24, pady=(4, 20))
        installing = False

        def close():
            if not installing:
                dialog.destroy()

        def browse():
            nonlocal installing
            downloads = os.path.join(os.path.expanduser("~"), "Downloads")
            selection = filedialog.askopenfilename(parent=dialog, title="Select your downloaded FFmpeg",
                                                  initialdir=downloads if os.path.isdir(downloads) else os.path.expanduser("~"),
                                                  filetypes=[("FFmpeg or ZIP", (EXE_NAME, "*.zip")), ("All files", "*")])
            if not selection:
                return
            installing = True
            status.configure(text="Installing and checking FFmpeg…", text_color="#8eb6ff")
            choose.configure(state="disabled")
            later.configure(state="disabled")
            result = queue.Queue()

            def worker():
                try:
                    result.put((install_ffmpeg(selection), None))
                except Exception as error:
                    result.put((None, str(error)))

            def finish():
                nonlocal installing
                try:
                    path, error = result.get_nowait()
                except queue.Empty:
                    dialog.after(75, finish)
                    return
                installing = False
                if error is not None:
                    status.configure(text=error, text_color="#ff8888")
                    choose.configure(state="normal")
                    later.configure(state="normal")
                    return
                self.ffmpeg = path
                self.ffmpeg_setup_btn.grid_remove()
                close()
                self.status.configure(text="FFmpeg is ready. You can now process audio.")

            threading.Thread(target=worker, daemon=True).start()
            dialog.after(75, finish)

        later = ctk.CTkButton(controls, text="Not now", width=110, fg_color="#293147", command=close)
        later.pack(side="left", padx=6)
        choose = ctk.CTkButton(controls, text="Browse for FFmpeg…", width=175, command=browse)
        choose.pack(side="left", padx=6)
        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.bind("<Escape>", lambda _: close())
        dialog.wait_visibility()
        dialog.grab_set()
        choose.focus_set()

    # ---- layout ---- #
    def _build_ui(self):
        self.sidebar_expanded = self.cfg.get("sidebar_expanded", True)
        self.logs_expanded = self.cfg.get("logs_expanded", False)
        self._progress_job = None
        self.grid_columnconfigure(0, weight=0, minsize=500)
        self.grid_columnconfigure(1, weight=1, minsize=440)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="#0c101b", border_width=1,
                               border_color="#23283a", corner_radius=28)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(18, 8))
        header.grid_columnconfigure(0, weight=1)
        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.grid(row=0, column=0, rowspan=2, sticky="w", padx=16, pady=12)
        logo = Image.open(asset_path("logo.png"))
        self.brand_logo = ctk.CTkImage(light_image=logo, dark_image=logo, size=(40, 46))
        ctk.CTkLabel(brand, text="", image=self.brand_logo, width=40, height=46).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(brand, text="jatotrainer", font=ctk.CTkFont(family="Poppins", size=19, weight="bold")).pack(side="left")
        ctk.CTkLabel(brand, text="v1.5.0", width=56, height=24, fg_color="#15243e",
                     corner_radius=12, text_color="#8eb6ff", font=ctk.CTkFont(family="Poppins", size=11)).pack(side="left", padx=10)
        self.pack_btn = ctk.CTkButton(header, text="Pack maker", width=105, height=36,
                                      fg_color="#131a2a", hover_color="#202b40", corner_radius=18,
                                      border_width=1, border_color="#293147", command=self.open_pack_maker)
        self.pack_btn.grid(row=0, column=1, rowspan=2, padx=(12, 0))
        self.sidebar_btn = ctk.CTkButton(header, text="Collapse sidebar", height=36,
                                         fg_color="#131a2a", hover_color="#202b40", corner_radius=18,
                                         border_width=1, border_color="#293147",
                                         command=self.toggle_sidebar)
        self.sidebar_btn.grid(row=0, column=2, rowspan=2, padx=(12, 0))
        self.detect_btn = ctk.CTkButton(header, text="Detect from osu!", height=36,
                                        fg_color="#131a2a", hover_color="#202b40", corner_radius=18,
                                         border_width=1, border_color="#293147",
                                        command=self.detect_current)
        self.detect_btn.grid(row=0, column=3, rowspan=2, padx=(10, 0))
        self.follow_var = tk.BooleanVar(value=False)
        ctk.CTkSwitch(header, text="Follow osu!", variable=self.follow_var,
                      progress_color=ACCENT, command=self.toggle_follow).grid(
                          row=0, column=4, rowspan=2, padx=(18, 20))

        self.compact_btn = ctk.CTkButton(header, text="Compact", width=90, height=36,
                                         fg_color="#131a2a", hover_color="#202b40",
                                         corner_radius=18, command=self.enter_compact)
        self.compact_btn.grid(row=0, column=5, rowspan=2, padx=(0, 14))

        self.conversion_btn = ctk.CTkButton(header, text="StepMania conversion", width=205, height=30,
                                            corner_radius=15, fg_color="#131a2a", hover_color="#202b40",
                                            command=self.open_conversion)
        self.conversion_btn.grid(row=2, column=0, columnspan=6, sticky="e", padx=16, pady=(0,10))

        self.ffmpeg_setup_btn = ctk.CTkButton(header, text="Set up FFmpeg", width=145, height=30,
                                              corner_radius=15, command=self.show_ffmpeg_setup)
        if not self.ffmpeg:
            self.ffmpeg_setup_btn.grid(row=2, column=0, sticky="w", padx=16, pady=(0,10))

        # left: library
        left = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=22, border_width=1, border_color="#22283a")
        self.sidebar = left
        left.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=16)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(3, weight=1)

        top = ctk.CTkFrame(left, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 6))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Chart library", font=ctk.CTkFont(family="Poppins", size=18, weight="bold")).grid(row=0, column=0, sticky="w")
        self.browse_btn = ctk.CTkButton(top, text="Browse…", width=80, fg_color="#171c2c", hover_color="#242d45", command=self.browse)
        self.browse_btn.grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(top, text="Rescan", width=70, fg_color="#171c2c", hover_color="#242d45",
                      command=self.start_scan).grid(row=0, column=2)

        filt = ctk.CTkFrame(left, fg_color="transparent")
        filt.grid(row=1, column=0, sticky="ew", padx=14, pady=4)
        filt.grid_columnconfigure(0, weight=1)
        self.search_entry = ctk.CTkEntry(filt, placeholder_text="Search artist, title, mapper, diff…", height=34)
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<KeyRelease>", lambda e: self.refresh_list())
        self.keys_var = tk.StringVar(value="All keys")
        ctk.CTkOptionMenu(filt, values=["All keys"] + [f"{k}K" for k in range(1, 11)], variable=self.keys_var,
                          width=100, fg_color="#171c2c", button_color="#242d45",
                          command=lambda _: self.refresh_list()).grid(row=0, column=1, padx=(8, 0))
        cnt = ctk.CTkFrame(left, fg_color="transparent")
        cnt.grid(row=2, column=0, sticky="ew", padx=16)
        cnt.grid_columnconfigure(0, weight=1)
        self.count_lbl = ctk.CTkLabel(cnt, text="", text_color="#8888a0", anchor="w")
        self.count_lbl.grid(row=0, column=0, sticky="ew")
        style = ttk.Style()
        style.theme_use("clam")
        style.layout("Maps.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure("Maps.Treeview", background=BG_PANEL, fieldbackground=BG_PANEL, foreground="#e6e6f0",
                        rowheight=30, borderwidth=0, font=("Poppins", 10))
        style.configure("Maps.Treeview.Heading", background="#171c2c", foreground="#c0c0d0", relief="flat",
                        font=("Poppins", 9, "bold"))
        style.map("Maps.Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
        style.map("Maps.Treeview.Heading", background=[("active", "#242d45")])

        tf = ctk.CTkFrame(left, fg_color="transparent")
        tf.grid(row=3, column=0, sticky="nsew", padx=10, pady=(4, 12))
        tf.grid_columnconfigure(0, weight=1)
        tf.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(tf, columns=("song", "diff", "mapper", "keys", "bpm"), show="headings",
                                 style="Maps.Treeview", selectmode="browse",
                                 )
        self.tree.configure(takefocus=False)
        for col, text, w in (("song", "Artist - Title", 190), ("diff", "Difficulty", 105), ("mapper", "Mapper", 80),
                             ("keys", "Keys", 40), ("bpm", "BPM", 45)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, anchor="w" if col in ("song", "diff", "mapper") else "center")
        sb = ctk.CTkScrollbar(tf, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        # right: controls
        right_shell = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=22,
                                   border_width=1, border_color="#22283a")
        right_shell.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=16)
        right_shell.grid_columnconfigure(0, weight=1)
        right_shell.grid_rowconfigure(0, weight=1)
        self.conversion_dock = ctk.CTkFrame(right_shell, fg_color=BG_PANEL, corner_radius=18)
        self.conversion_dock.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.conversion_dock.grid_columnconfigure(0, weight=1)
        right = ctk.CTkScrollableFrame(right_shell, fg_color=BG_PANEL, corner_radius=22,
                                       border_width=1, border_color="#22283a",
                                       scrollbar_button_color="#27304a",
                                       scrollbar_button_hover_color="#3d4c72")
        self.workspace = right
        right.grid(row=0, column=0, sticky="nsew", padx=6, pady=(6, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(8, weight=1)

        from ui_components import TextCanvas
        self.chart_canvas = TextCanvas(right, height=260, bg=BG_PANEL, highlightthickness=0)
        self.chart_canvas.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 4))
        self.background_image = None
        self.chart_canvas.bind("<Configure>", lambda _: self._draw_chart_card())
        self.card_sub = ctk.CTkLabel(right,
                                     text="Select a chart in the sidebar, or detect your current osu! selection.",
                                     anchor="w", text_color="#8992a6", wraplength=520, justify="left",
                                     font=ctk.CTkFont(family="Poppins", size=12))
        self.card_sub.grid(row=1, column=0, sticky="ew", padx=22, pady=(2, 12))

        rhead = ctk.CTkFrame(right, fg_color="transparent")
        rhead.grid(row=2, column=0, sticky="ew", padx=18)
        rhead.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(rhead, text="RATES", anchor="w", text_color="#8888a0",
                     font=ctk.CTkFont(family="Poppins", size=11, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(rhead, text="Clear", width=50, height=22, fg_color="transparent", hover_color="#2a2a36",
                      text_color="#8888a0", command=lambda: self.rates_var.set("")).grid(row=0, column=2)
        ctk.CTkButton(rhead, text="Select all", width=70, height=22, fg_color="transparent", hover_color="#2a2a36",
                      text_color="#8888a0",
                      command=lambda: self.rates_var.set(", ".join(QUICK_RATES))).grid(row=0, column=1)
        chips = ctk.CTkFrame(right, fg_color="transparent")
        chips.grid(row=3, column=0, sticky="ew", padx=14, pady=(2, 0))
        self.chip_btns = {}
        for i, r in enumerate(QUICK_RATES):
            b = ctk.CTkButton(chips, text=f"{r}x", width=56, height=28, fg_color="#171c2c",
                              hover_color="#242d45", command=lambda r=r: self.toggle_rate(r))
            b.grid(row=i // 6, column=i % 6, padx=3, pady=3)
            self.chip_btns[r] = b
        self.rates_var = tk.StringVar(value="1.1, 1.2, 1.3")
        self.rates_var.trace_add("write", lambda *_: self.on_options_changed())
        ctk.CTkEntry(right, textvariable=self.rates_var, height=34,
                     placeholder_text="e.g. 1.1, 1.25, 1.35").grid(row=4, column=0, sticky="ew", padx=18, pady=(4, 10))

        ctk.CTkLabel(right, text="DIFFICULTY NAME FORMAT", anchor="w", text_color="#8888a0",
                     font=ctk.CTkFont(family="Poppins", size=11, weight="bold")).grid(row=5, column=0, sticky="ew", padx=18)
        fmtrow = ctk.CTkFrame(right, fg_color="transparent")
        fmtrow.grid(row=6, column=0, sticky="ew", padx=18, pady=(2, 0))
        fmtrow.grid_columnconfigure(0, weight=1)
        self.fmt_var = tk.StringVar(value=self.cfg.get("format", DEFAULT_FORMAT))
        self.fmt_var.trace_add("write", lambda *_: self.on_options_changed())
        ctk.CTkEntry(fmtrow, textvariable=self.fmt_var, height=34).grid(row=0, column=0, sticky="ew")
        ctk.CTkOptionMenu(fmtrow, values=FORMAT_PRESETS, width=100, fg_color="#171c2c", button_color="#242d45",
                          dynamic_resizing=False, variable=tk.StringVar(value="Presets"), command=self.fmt_var.set).grid(row=0, column=1, padx=(8, 0))
        self.preview = ctk.CTkLabel(right, text="", anchor="w", wraplength=520, justify="left",
                                    text_color=ACCENT)
        self.preview.grid(row=7, column=0, sticky="ew", padx=18, pady=(6, 0))

        opts = ctk.CTkFrame(right, fg_color="transparent")
        opts.grid(row=9, column=0, sticky="ew", padx=18, pady=(10, 0))
        ctk.CTkLabel(opts, text="Placeholders: {diff} {rate} {bpm} {bpm_orig} {od} {pct}",
                     text_color="#6a6a80", font=ctk.CTkFont(family="Poppins", size=11)).pack(anchor="w", pady=(0, 6))
        self.pitch_var = tk.BooleanVar(value=self.cfg.get("pitch", True))
        self.od_var = tk.BooleanVar(value=self.cfg.get("od", False))
        ctk.CTkSwitch(opts, text="Change pitch with speed (nightcore / DT style)", variable=self.pitch_var,
                      progress_color=ACCENT).pack(anchor="w", pady=2)
        ctk.CTkSwitch(opts, text="Scale OD like DT/HT would", variable=self.od_var,
                      progress_color=ACCENT).pack(anchor="w", pady=2)

        odrow = ctk.CTkFrame(opts, fg_color="transparent")
        odrow.pack(anchor="w", fill="x", pady=(8, 2))
        self.od_override_enabled = tk.BooleanVar(value=self.cfg.get("od_override_enabled", True))
        self.od_override_value = tk.StringVar(value=str(self.cfg.get("od_override", "8")))
        ctk.CTkSwitch(odrow, text="Set fixed OD (0–10)", variable=self.od_override_enabled,
                      progress_color=ACCENT).pack(side="left", padx=(0, 12))
        ctk.CTkEntry(odrow, textvariable=self.od_override_value, width=70).pack(side="left")
        ctk.CTkLabel(opts, text="Fixed OD overrides rate-based OD scaling.", text_color="#8992a6",
                     font=ctk.CTkFont(family="Poppins", size=11)).pack(anchor="w")
        self.od_override_enabled.trace_add("write", lambda *_: self.on_options_changed())
        self.od_override_value.trace_add("write", lambda *_: self.on_options_changed())
        self.od_var.trace_add("write", lambda *_: self.on_options_changed())

        self.gen_btn = ctk.CTkButton(self.conversion_dock, text="Convert charts", height=44, corner_radius=22, border_width=1, border_color="#78a8ff", fg_color=ACCENT,
                                     hover_color=ACCENT_HOVER, font=ctk.CTkFont(family="Poppins", size=15, weight="bold"),
                                     command=self.on_generate, state="disabled")
        self.gen_btn.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 6))
        progress_card = ctk.CTkFrame(self.conversion_dock, fg_color=BG_MAIN, corner_radius=16,
                                     border_width=1, border_color="#222c42")
        progress_card.grid(row=1, column=0, sticky="ew", padx=18, pady=(6, 4))
        progress_card.grid_columnconfigure(0, weight=1)
        self.progress_label = ctk.CTkLabel(progress_card, text="Ready to convert", anchor="w",
                                           text_color="#94a3b8", font=ctk.CTkFont(family="Poppins", size=12))
        self.progress_label.grid(row=0, column=0, sticky="ew", padx=14, pady=(8, 0))
        self.progress = ctk.CTkProgressBar(progress_card, progress_color=ACCENT,
                                           fg_color="#24304a", height=10, corner_radius=5)
        self.progress.set(0)
        self.progress.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 14))

        self.logs_panel = ctk.CTkFrame(right, fg_color="transparent")
        self.logs_panel.grid(row=12, column=0, sticky="ew", padx=18, pady=(4, 2))
        self.logs_panel.grid_columnconfigure(0, weight=1)
        self.logs_btn = ctk.CTkButton(self.logs_panel, text="Expand conversion logs  ▾",
                                      anchor="w", height=30, fg_color="transparent",
                                      hover_color="#24304a", text_color="#94a3b8",
                                      command=self.toggle_logs)
        self.logs_btn.grid(row=0, column=0, sticky="ew")
        self.log = ctk.CTkTextbox(self.logs_panel, height=100, fg_color=BG_MAIN,
                                  text_color="#cbd5e1", corner_radius=10,
                                  font=ctk.CTkFont(family="Poppins", size=11))
        self.log.grid(row=1, column=0, sticky="ew", pady=(6, 4))
        self.log.configure(state="disabled")
        self.status = ctk.CTkLabel(right, text="", anchor="w", text_color="#94a3b8",
                                    wraplength=520, justify="left", font=ctk.CTkFont(family="Poppins", size=12))
        self.status.grid(row=13, column=0, sticky="ew", padx=18, pady=(2, 14))
        self._apply_sidebar()
        self._apply_logs()

        self.on_options_changed()

    def enter_compact(self):
        if getattr(self, "compact_active", False):
            return
        from compact_mode import CompactMode
        popover = getattr(self, "_active_popover", None)
        if popover is not None and popover.winfo_exists():
            popover.destroy()
        self._full_geometry = self.geometry()
        self._full_state = self.state()
        self.state("normal")
        self._full_follow = self.follow_var.get()
        self._compact_widgets = [w for w in self.winfo_children() if w.winfo_manager() == "grid"]
        for widget in self._compact_widgets:
            widget.grid_remove()
        self.compact_active = True
        self.grid_columnconfigure(0, weight=1, minsize=0)
        self.grid_columnconfigure(1, weight=0, minsize=0)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.minsize(300, 500)
        self.geometry("300x500")
        self.od_override_enabled.set(True)
        self.compact = CompactMode(self)
        self.compact.grid(row=0, column=0, columnspan=2, rowspan=2, sticky="nsew")
        if not self.follow_var.get():
            self.follow_var.set(True)
            self.toggle_follow()
        self.compact.refresh()

    def exit_compact(self):
        if not getattr(self, "compact_active", False):
            return
        self.compact_active = False
        popover = getattr(self, "_active_popover", None)
        if popover is not None and popover.winfo_exists():
            popover.destroy()
        self.compact.destroy()
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1, minsize=440)
        self.minsize(1080, 780)
        self.geometry(self._full_geometry)
        self.state(self._full_state)
        for widget in self._compact_widgets:
            widget.grid()
        self._apply_sidebar()
        self.follow_var.set(self._full_follow)
        self.toggle_follow()
        self.on_options_changed()

    def open_conversion(self):
        from conversion_ui import ConversionPage
        if not hasattr(self, "conversion_page") or not self.conversion_page.winfo_exists():
            self.conversion_page = ConversionPage(self, sys.modules[__name__])
        self.show_pack_page(self.conversion_page)

    def back_from_conversion(self):
        self.conversion_page.active = False
        self.conversion_page.grid_remove()
        self.back_from_pack()

    def open_pack_maker(self):
        existing = getattr(self, "pack_window", None)
        if existing is not None and existing.winfo_exists():
            from pack_maker import PackMaker
            if isinstance(existing, PackMaker):
                self.show_pack_page(existing)
            else:
                existing.lift()
            return
        from pack_maker import PackSetup
        self.pack_window = PackSetup(self)

    def show_pack_page(self, page):
        if not hasattr(self, "_main_widgets"):
            self._main_widgets = [w for w in self.winfo_children() if w is not page and w.winfo_manager() == "grid"]
        for widget in self._main_widgets:
            widget.grid_remove()
        self.grid_columnconfigure(0, weight=1, minsize=0)
        self.grid_columnconfigure(1, weight=0, minsize=0)
        page.active = True
        page.grid(row=0, column=0, rowspan=2, columnspan=2, sticky="nsew")

    def back_from_pack(self):
        popover = getattr(self, "_active_popover", None)
        if popover is not None and popover.winfo_exists():
            popover.destroy()
        page = getattr(self, "pack_window", None)
        if page is not None and page.winfo_exists():
            page.active = False
            page.grid_remove()
        self.grid_columnconfigure(1, weight=1, minsize=440)
        for widget in getattr(self, "_main_widgets", []):
            widget.grid()
        self._apply_sidebar()

    def _apply_sidebar(self):
        if self.sidebar_expanded:
            self.sidebar.grid()
            self.grid_columnconfigure(0, minsize=500, weight=0)
            self.sidebar_btn.configure(text="Collapse sidebar")
        else:
            self.sidebar.grid_remove()
            self.grid_columnconfigure(0, minsize=0, weight=0)
            self.sidebar_btn.configure(text="Expand sidebar")

    def toggle_sidebar(self):
        self.sidebar_expanded = not self.sidebar_expanded
        self._apply_sidebar()
        self.cfg["sidebar_expanded"] = self.sidebar_expanded
        save_json(CONFIG_PATH, self.cfg)

    def _apply_logs(self):
        if self.logs_expanded:
            self.log.grid()
            self.logs_btn.configure(text="Collapse conversion logs  ▴")
        else:
            self.log.grid_remove()
            self.logs_btn.configure(text="Expand conversion logs  ▾")

    def toggle_logs(self):
        self.logs_expanded = not self.logs_expanded
        self._apply_logs()
        self.cfg["logs_expanded"] = self.logs_expanded
        save_json(CONFIG_PATH, self.cfg)

    def _set_progress(self, value, finished=False, failed=False):
        if self._progress_job is not None:
            self.after_cancel(self._progress_job)
            self._progress_job = None
        color = "#34d399" if finished else "#fb7185" if failed else ACCENT
        self.progress.configure(progress_color=color)
        label = "Complete · 100%" if finished else "Conversion failed" if failed else f"Converting · {value:.0%}"
        self.progress_label.configure(text=label, text_color=color)
        start = self.progress.get()
        if failed or value == 0:
            self.progress.set(value)
            return
        def frame(step=1):
            self.progress.set(start + (value - start) * step / 12)
            if step < 12:
                self._progress_job = self.after(16, lambda: frame(step + 1))
            else:
                self._progress_job = None
        frame()

    # ---- library ---- #
    def browse(self):
        from pack_maker import FolderPicker
        def chosen(d):
            self.songs_dir = normalize_songs_dir(d)
            self.cfg["songs_dir"] = self.songs_dir
            save_json(CONFIG_PATH, self.cfg)
            self.start_scan()
        FolderPicker(self, self.browse_btn, self.songs_dir, chosen)

    def start_scan(self, completion_message=None):
        if not self.songs_dir or self.busy:
            return
        self.busy = True
        self._scan_status = completion_message
        self._scan_selected_path = (self.selected or {}).get('path')
        self.status.configure(text=f"Scanning {self.songs_dir} …")
        self.count_lbl.configure(text="Scanning…")
        self.on_options_changed()

        def work():
            try:
                maps, stats = scan_songs(self.songs_dir, lambda i, t: self.q.put(("scanprog", i, t)))
                self.q.put(("scandone", maps, stats))
            except Exception as e:
                self.q.put(("scanerr", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def refresh_list(self):
        q = self.search_entry.get().lower().strip()
        k = self.keys_var.get()
        words = q.split()
        self.tree.delete(*self.tree.get_children())
        self.visible = []
        for m in self.maps:
            if m.get("gen"):
                continue
            if k != "All keys" and m["keys"] != int(k[:-1]):
                continue
            hay = f"{m['artist']} {m['title']} {m['creator']} {m['version']}".lower()
            if all(w in hay for w in words):
                self.visible.append(m)
        self.visible.sort(key=lambda m: (m["artist"].lower(), m["title"].lower(), m["keys"], m["version"].lower()))
        for i, m in enumerate(self.visible[:LIST_LIMIT]):
            self.tree.insert("", "end", iid=str(i), values=(f"{m['artist']} - {m['title']}", m["version"],
                                                           m["creator"], f"{m['keys']}K", m["bpm"]))
        extra = "" if len(self.visible) <= LIST_LIMIT else f" (showing first {LIST_LIMIT}, refine search)"
        self.count_lbl.configure(text=f"{len(self.visible)} difficulties{extra}")

    def on_select(self, _=None):
        sel = self.tree.selection()
        if not sel:
            return
        self.selected = self.visible[int(sel[0])]
        m = self.selected
        self.background_image = None
        try:
            import csv
            _, sections = parse_osu(m["path"])
            for line in sec(sections, "Events"):
                row = next(csv.reader([line]))
                if len(row) >= 3 and row[0].strip() in ("0", "Background"):
                    filename = row[2].replace("\\", os.sep)
                    candidate = os.path.realpath(os.path.join(os.path.dirname(m["path"]), filename))
                    base = os.path.realpath(os.path.dirname(m["path"]))
                    if os.path.commonpath([base, candidate]) == base:
                        with Image.open(candidate) as im:
                            self.background_image = im.convert("RGB")
                    break
        except (OSError, ValueError, StopIteration):
            pass
        self.card_sub.configure(text=f"{m['artist']} · {m['title']} · mapped by {m['creator']}")
        self.on_options_changed()

    def select_map(self, m):
        """Select a map in the list. If it's filtered out or beyond the display limit,
        narrow the list to it (search by title + difficulty) so it can be shown."""
        def shown():
            return m in self.visible and self.visible.index(m) < LIST_LIMIT

        if not shown():
            self.keys_var.set("All keys")
            self.search_entry.delete(0, "end")
            self.search_entry.insert(0, f"{m['title']} {m['version']}")
            self.refresh_list()
        if not shown():  # still too many matches: add the artist and mapper too
            self.search_entry.delete(0, "end")
            self.search_entry.insert(0, f"{m['artist']} {m['title']} {m['version']} {m['creator']}")
            self.refresh_list()
        if shown():
            i = str(self.visible.index(m))
            self.tree.selection_set(i)
            self.tree.see(i)
            return True
        return False

    def apply_selection(self, sel, verb):
        """Match + select; returns a status message explaining what happened."""
        m, n = match_selection(self.maps, sel, self.songs_dir)
        name = f"{sel['artist'] or '?'} - {sel['title'] or '?'} [{sel['version'] or '?'}]"
        if m and m.get("gen"):
            return (f"osu! has a rate you generated selected ({name}). Select the original difficulty "
                    "to make more rates.")
        if m and self.select_map(m):
            extra = ""
            if n > 1:
                extra = (f"\n{n} identical-looking copies exist; picked the one in '{os.path.basename(os.path.dirname(m['path']))}'. "
                         "If that's wrong, remove the duplicate set or pick it manually.")
            return f"{verb}: {m['artist']} - {m['title']} [{m['version']}]{extra}"
        why = "it isn't an osu!mania map in this Songs folder" if not m else "it couldn't be shown in the list (try Rescan)"
        return (f"osu! has {name} selected, but I couldn't find it: {why}.\n"
                f"Detected file={sel['file']}, folder={sel['folder']}, id={sel['bid']}")

    def detect_current(self):
        if getattr(self, "_detecting", False):
            return
        self._detecting = True
        self.status.configure(text="Reading your selected osu! chart…")
        def work():
            try:
                self.q.put(("detected", current_selection()))
            except Exception as error:
                self.q.put(("detect_error", str(error)))
        threading.Thread(target=work, daemon=True).start()

    def toggle_follow(self):
        if self.follow_var.get():
            self.follow_gen = getattr(self, "follow_gen", 0) + 1
            gen = self.follow_gen

            def loop():
                last = None
                warned = False
                while self.follow_gen == gen:
                    sel = current_selection()
                    if sel is None and not warned:
                        self.q.put(("follow_err",))
                        warned = True
                        last = None
                    elif sel is not None:
                        warned = False
                    key = tuple((sel or {}).get(field) for field in
                                ("path", "folder", "file", "bid", "artist", "title", "version"))
                    if sel and key != last:
                        last = key
                        self.q.put(("follow", sel))
                    time.sleep(1.0)

            threading.Thread(target=loop, daemon=True).start()
            self.status.configure(text="Following osu! … pick a map in-game and it'll appear here.")
        else:
            self.follow_gen = getattr(self, "follow_gen", 0) + 1

    # ---- options ---- #
    def _od_override(self):
        if not self.od_override_enabled.get():
            return None
        try:
            value = float(self.od_override_value.get())
        except ValueError:
            raise ValueError("OD must be a number between 0 and 10")
        if not math.isfinite(value) or not 0 <= value <= 10:
            raise ValueError("OD must be between 0 and 10")
        return value

    def _rounded_tile(self, x, y, x2, y2, fill, outline):
        r=9
        self.chart_canvas.create_polygon(x+r,y,x2-r,y,x2,y,x2,y+r,x2,y2-r,x2,y2,
            x2-r,y2,x+r,y2,x,y2,x,y2-r,x,y+r,x,y, smooth=True,
            fill=fill, outline=outline, width=2)

    def _draw_chart_card(self):
        from tkinter import font as tkfont
        c = self.chart_canvas
        w = max(300, c.winfo_width())
        rates = self.parse_rates(silent=True) if hasattr(self, "rates_var") else []
        columns = max(1, (w - 40) // 76)
        c.delete("all")
        m = self.selected
        title = m["title"] if m else "Choose a chart to begin"
        title_item = c.create_text(22, 18, text=title, fill="white", anchor="nw",
                                   width=w-44, font=("Poppins", 24, "bold"))
        diff_y = c.bbox(title_item)[3] + 6
        diff_item = c.create_text(22, diff_y,
            text="‹ " + m["version"].strip(" <>‹›") + " ›" if m else "Your chart. Your pace.",
            fill="white", anchor="nw", width=max(150,w-180), font=("Poppins",17,"bold"))
        badge_y = c.bbox(diff_item)[3] + 8
        label_y = badge_y + 46 if m else badge_y + 8
        rate_y = label_y + 28
        rows = max(1, math.ceil(len(rates) / columns)) if rates else 0
        h = rate_y + (rows-1)*48 + 38 + 18 if rates else label_y+38
        c.configure(height=h)
        image = Image.new("RGB", (w, h), "#171d30")
        if self.background_image is not None:
            image = ImageOps.fit(self.background_image, (w, h), method=Image.Resampling.LANCZOS)
            image = Image.blend(image, Image.new("RGB", (w, h), "#111322"), .58)
        mask = Image.new("L", (w, h))
        ImageDraw.Draw(mask).rounded_rectangle((1,1,w-2,h-2),radius=24,fill=255)
        image.putalpha(mask)
        ImageDraw.Draw(image).rounded_rectangle((2,2,w-3,h-3),radius=24,outline="#9c95aa",width=3)
        self.card_image = ImageTk.PhotoImage(image)
        background=c.create_image(0,0,image=self.card_image,anchor="nw")
        c.tag_lower(background)
        c.create_text(w-22,diff_y,text="By "+m["creator"] if m else "",
                      fill="#eeeaf4",anchor="ne",font=("Poppins",13))
        if m:
            x=22
            badge_font=tkfont.Font(family="Poppins",size=14,weight="bold")
            card_od = str(m['od'])
            if hasattr(self, "od_override_enabled") and self.od_override_enabled.get():
                try:
                    card_od = format(self._od_override(), "g")
                except ValueError:
                    card_od = "?"
            for text in (f"{m['keys']}K",f"{m['bpm']} BPM",f"OD {card_od}"):
                width=max(58,badge_font.measure(text)+20)
                self._rounded_tile(x,badge_y,x+width,badge_y+36,"#5987ee","#80a4ff")
                c.create_text(x+width/2,badge_y+18,text=text,fill="white",font=badge_font)
                x+=width+8
        c.create_text(22,label_y,text="Rates being created:" if rates else "Choose or enter rates below",
                      fill="white",anchor="nw",font=("Poppins",13))
        for i,rate in enumerate(rates):
            x=22+(i % columns)*76; y=rate_y+(i // columns)*48
            self._rounded_tile(x,y,x+68,y+38,"#b88925","#efd17a")
            c.create_text(x+34,y+19,text=fmt_rate(rate),fill="white",font=("Poppins",14,"bold"))

    def toggle_rate(self, r):
        cur = self.parse_rates(silent=True)
        val = float(r)
        cur = [x for x in cur if abs(x - val) > 1e-9] if any(abs(x - val) < 1e-9 for x in cur) else sorted(cur + [val])
        self.rates_var.set(", ".join(fmt_rate(x) for x in cur))

    def parse_rates(self, silent=False):
        out = []
        for tok in re.split(r"[,\s;]+", self.rates_var.get().strip()):
            if not tok:
                continue
            try:
                v = float(tok.rstrip("xX"))
                if 0.1 <= v <= 5 and abs(v - 1) > 1e-9:
                    out.append(v)
            except ValueError:
                pass
        return list(dict.fromkeys(out))

    def on_options_changed(self):
        rates = self.parse_rates(silent=True)
        self._draw_chart_card()
        for r, b in self.chip_btns.items():
            on = any(abs(x - float(r)) < 1e-9 for x in rates)
            b.configure(fg_color="#b88925" if on else "#2a2a36", hover_color="#d0a341" if on else "#363646", text_color="#ffffff")
        ok = True
        try:
            sample = rates[0] if rates else 1.25
            m = self.selected or dict(version="Insane", bpm=180, od="8")
            od = m.get("od", "8")
            override = self._od_override()
            names = [format_version(self.fmt_var.get(), m["version"], r, float(m["bpm"]), override if override is not None else scale_od(od, r) if self.od_var.get() else od)
                     for r in (rates[:3] or [sample])]
            self.preview.configure(text="Preview:  " + "   |   ".join(names), text_color=ACCENT)
        except (KeyError, IndexError, ValueError) as e:
            ok = False
            self.preview.configure(text=f"Invalid format ({e})", text_color="#ff6666")
        self.gen_btn.configure(state="normal" if ok and rates and self.selected and not self.busy else "disabled")

    # ---- generate ---- #
    def on_generate(self):
        rates, m = self.parse_rates(), self.selected
        if not rates or not m or self.busy:
            return
        override = self._od_override()
        self.cfg.update(od_override_enabled=self.od_override_enabled.get(), od_override=self.od_override_value.get(), format=self.fmt_var.get(), pitch=self.pitch_var.get(), od=self.od_var.get())
        save_json(CONFIG_PATH, self.cfg)
        self.busy = True
        self.gen_btn.configure(state="disabled", text="Converting…")
        self._set_progress(0)
        self.log.configure(state="normal"); self.log.delete("1.0", "end"); self.log.configure(state="disabled")
        if getattr(self, "compact_active", False):
            self.compact.refresh()
        hp = self.compact.hp_value if getattr(self, "compact_active", False) else None
        fmt, pitch, odf, ff = self.fmt_var.get(), self.pitch_var.get(), self.od_var.get(), self.ffmpeg

        def work():
            outputs = []
            try:
                for n, _ in enumerate(generate(m, rates, fmt, pitch, odf, lambda s: self.q.put(("log", s)), ff, override, hp, result=outputs.append), 1):
                    self.q.put(("prog", n / len(rates)))
                self.q.put(("done", len(rates), outputs))
            except Exception as e:
                self.q.put(("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _log(self, s):
        self.log.configure(state="normal")
        self.log.insert("end", s + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                k = msg[0]
                if k == "log":
                    self._log(msg[1])
                elif k == "prog":
                    self._set_progress(msg[1])
                elif k == "done":
                    self._set_progress(1, finished=True)
                    self.busy = False
                    self.gen_btn.configure(text="Convert charts")
                    outputs = msg[2] if len(msg) > 2 else []
                    self.last_outputs = outputs
                    created = sum(output['created'] for output in outputs)
                    reused = len(outputs) - created
                    if outputs:
                        message = (f"Created {created}; already existed {reused}. Press F5 in osu! song select."
                                   if created else f"All {reused} map(s) already exist; no new difficulty was added.")
                        for output in outputs:
                            self._log(f"{'Created' if output['created'] else 'Already exists'}: {output['version']}\nSaved at: {output['path']}")
                    else:
                        message = "Conversion finished."
                    self.status.configure(text=message)
                    self.on_options_changed()
                    if created or getattr(self, '_scan_selection', None):
                        self.start_scan(completion_message=message)
                elif k == "error":
                    self._set_progress(self.progress.get(), failed=True)
                    self.logs_expanded = True
                    self._apply_logs()
                    self.busy = False
                    self.gen_btn.configure(text="Convert charts")
                    self._log("ERROR: " + msg[1])
                    self.status.configure(text="Conversion failed: " + msg[1])
                    self.on_options_changed()
                elif k == "detected":
                    self._detecting = False
                    self.status.configure(text=self.apply_selection(msg[1], "Selected") if msg[1] else
                        "No selected chart detected. Start osu!stable and select a chart. tosu also works as a fallback.")
                elif k == "detect_error":
                    self._detecting = False
                    self.status.configure(text=f"Detection failed: {msg[1]}")
                elif k == "follow":
                    selection = msg[1]
                    found, _ = match_selection(self.maps, selection, self.songs_dir)
                    key = tuple(selection.get(field) for field in ('folder', 'file', 'path', 'title', 'version'))
                    if not found and self.songs_dir and key != getattr(self, '_missing_scan_key', None):
                        self._missing_scan_key = key
                        self._scan_selection = selection
                        if not self.busy:
                            self.start_scan()
                    else:
                        self.status.configure(text=self.apply_selection(selection, "Following osu!"))
                elif k == "follow_err":
                    self.status.configure(text="No selected chart detected. Start osu!stable and select a chart. tosu also works as a fallback.")
                elif k == "scanprog":
                    self.count_lbl.configure(text=f"Scanning… {msg[1]}/{msg[2]} folders")
                elif k == "scandone":
                    self.busy = False
                    self.maps, st = msg[1], msg[2]
                    self.refresh_list()
                    selected_path = getattr(self, '_scan_selected_path', None)
                    if selected_path:
                        selected_map = next((m for m in self.maps if m['path'] == selected_path), None)
                        if selected_map:
                            self.select_map(selected_map)
                    txt = f"Songs: {self.songs_dir}\n{st['folders']} folders, {st['files']} .osu files, {st['mania']} mania difficulties"
                    if st["mania"] == 0:
                        txt += ("\nNo mania maps found - is this the right folder? Use Browse… to pick the Songs folder."
                                if st["files"] == 0 else "\nFound maps but none are osu!mania.")
                    if not self.ffmpeg:
                        txt += "\n(ffmpeg missing - audio can't be made)"
                    pending = getattr(self, '_scan_selection', None)
                    self._scan_selection = None
                    if pending:
                        txt = self.apply_selection(pending, 'Following osu!')
                    self.status.configure(text=getattr(self, '_scan_status', None) or txt)
                    self._scan_status = None
                    self.on_options_changed()
                elif k == "scanerr":
                    self.busy = False
                    self.status.configure(text=f"Scan failed: {msg[1]}")
        except queue.Empty:
            pass
        if getattr(self, "compact_active", False):
            self.compact.refresh()
        self._poll_job = self.after(100, self._poll)


if __name__ == "__main__":
    App().mainloop()
