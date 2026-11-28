"""Read beatmap metadata from osu!stable's own index (osu!.db) instead of opening every .osu file.

Format: https://github.com/ppy/osu/wiki/Legacy-database-file-structure
Only what the beatmap list needs is decoded; everything else is skipped by size.
"""
import struct

# Windows FILETIME-style ticks (100 ns since 0001-01-01) at the Unix epoch.
UNIX_EPOCH_TICKS = 621355968000000000
# From this version on, each beatmap no longer starts with its byte size.
NO_ENTRY_SIZE = 20191106
# From this version on, star ratings are stored as float instead of double.
FLOAT_STARS = 20250107


class _Reader:
    __slots__ = ("data", "pos")

    def __init__(self, data):
        self.data, self.pos = data, 0

    def unpack(self, fmt, size):
        value = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += size
        return value

    def byte(self):
        self.pos += 1
        return self.data[self.pos - 1]

    def short(self):
        return self.unpack("<h", 2)[0]

    def int(self):
        return self.unpack("<i", 4)[0]

    def long(self):
        return self.unpack("<q", 8)[0]

    def single(self):
        return self.unpack("<f", 4)[0]

    def skip(self, size):
        self.pos += size

    def string(self):
        marker = self.byte()
        if marker == 0:
            return ""
        if marker != 0x0B:
            raise ValueError(f"bad string marker {marker:#x} at {self.pos - 1}")
        length = shift = 0
        while True:  # ULEB128 length
            b = self.byte()
            length |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
        text = self.data[self.pos:self.pos + length].decode("utf-8", "replace")
        self.pos += length
        return text


def _skip_star_ratings(r, version):
    for _ in range(4):  # standard, taiko, catch, mania
        count = r.int()
        if count > 0:
            # Each pair is: 0x08, int mods, then 0x0d double or (newer) 0x0c float.
            r.skip(count * (10 if version >= FLOAT_STARS else 14))


def read_osu_db(path):
    """Return (version, beatmaps). Each beatmap is a dict with the fields the scanner needs."""
    with open(path, "rb") as f:
        r = _Reader(f.read())
    version = r.int()
    r.int(); r.byte(); r.long(); r.string()  # folder count, account unlocked, unlock date, player name
    count = r.int()
    maps = []
    for _ in range(count):
        if version < NO_ENTRY_SIZE:
            r.int()
        artist = r.string(); r.string()  # artist (unicode skipped)
        title = r.string(); r.string()
        creator = r.string()
        difficulty = r.string()
        r.string()  # audio file
        md5 = r.string()
        filename = r.string()
        r.byte()  # ranked status
        r.skip(6)  # circle, slider, spinner counts
        modified = r.long()
        if version < 20140609:
            r.skip(4)
            cs, od = r.data[r.pos - 3], r.data[r.pos - 1]
        else:
            r.single()  # AR
            cs = r.single()
            r.single()  # HP
            od = r.single()
        r.skip(8)  # slider velocity
        if version >= 20140609:
            _skip_star_ratings(r, version)
        r.skip(12)  # drain time, total time, preview time
        bpm = 0.0
        for _ in range(r.int()):  # timing points: double ms per beat, double offset, bool uninherited
            ms_per_beat, _offset, uninherited = r.unpack("<dd?", 17)
            if not bpm and uninherited and ms_per_beat > 0:
                bpm = 60000.0 / ms_per_beat
        beatmap_id = r.int()
        r.int(); r.int()  # set id, thread id
        r.skip(4)  # grades
        r.short(); r.single()  # local offset, stack leniency
        mode = r.byte()
        r.string()  # source
        tags = r.string()
        r.short()  # online offset
        r.string()  # title font
        r.byte(); r.long(); r.byte()  # unplayed, last played, osz2
        folder = r.string()
        r.long()  # last checked
        r.skip(5)  # ignore sounds/skin, disable storyboard/video, visual override
        if version < 20140609:
            r.short()
        r.int()  # last modification (unused)
        r.byte()  # mania scroll speed
        maps.append(dict(artist=artist, title=title, creator=creator, version=difficulty, md5=md5,
                         folder=folder, file=filename, modified=modified, mode=mode, cs=cs, od=od,
                         bpm=bpm, bid=beatmap_id, tags=tags))
    return version, maps


def mtime_to_ticks(mtime_ns):
    return mtime_ns // 100 + UNIX_EPOCH_TICKS


def same_file_time(mtime_ns, ticks, tolerance_s=2):
    """osu! records each .osu file's write time; a mismatch means it changed since osu! indexed it."""
    return abs(mtime_to_ticks(mtime_ns) - ticks) <= tolerance_s * 10**7


def scan_info(m, path, gen_tag):
    """The scanner's info dict for an osu!.db entry, or None if it isn't osu!mania."""
    if m["mode"] != 3:
        return None
    return dict(
        gen=gen_tag in m["tags"].split(),
        path=path,
        artist=m["artist"] or "?",
        title=m["title"] or "?",
        creator=m["creator"] or "?",
        version=m["version"] or "?",
        bid=m["bid"],
        keys=int(m["cs"]),
        od=format(round(m["od"], 3), "g"),  # stored as float32: 8.25 reads back as 8.2500000x
        bpm=int(round(m["bpm"])),
    )
