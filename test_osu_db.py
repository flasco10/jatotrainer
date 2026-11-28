import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jatotrainer as core
import osu_db


def s(text):
    data = text.encode("utf-8")
    out, n = b"\x0b", len(data)
    while True:  # ULEB128
        b = n & 0x7F
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out + data


def entry(version, folder, file, mode=3, cs=4.0, od=8.25, ms_per_beat=500.0, modified=0, title="T", tags="", bid=7):
    star_pair = (b"\x08" + struct.pack("<i", 0) + (b"\x0c" + struct.pack("<f", 3.5) if version >= osu_db.FLOAT_STARS
                                                   else b"\x0d" + struct.pack("<d", 3.5)))
    body = b"".join([s("Artist"), s(""), s(title), s(""), s("Mapper"), s("Hard"), s("audio.mp3"), s("md5"), s(file),
                     b"\x04", struct.pack("<hhh", 1, 0, 0), struct.pack("<q", modified),
                     struct.pack("<ffff", 5, cs, 8, od), struct.pack("<d", 1.4),
                     struct.pack("<i", 0), struct.pack("<i", 0), struct.pack("<i", 0), struct.pack("<i", 1) + star_pair,
                     struct.pack("<iii", 60, 60000, 0),
                     struct.pack("<i", 2), struct.pack("<dd?", -100.0, 0, False), struct.pack("<dd?", ms_per_beat, 10, True),
                     struct.pack("<iii", bid, 1, 0), b"\0\0\0\0", struct.pack("<hf", 0, 0.7), bytes([mode]),
                     s(""), s(tags), struct.pack("<h", 0), s(""), b"\x01", struct.pack("<q", 0), b"\x00", s(folder),
                     struct.pack("<q", 0), b"\0\0\0\0\0", struct.pack("<i", 0), b"\x00"])
    return body if version >= osu_db.NO_ENTRY_SIZE else struct.pack("<i", len(body)) + body


def database(version, entries):
    return (struct.pack("<ii", version, 1) + b"\x01" + struct.pack("<q", 0) + s("player")
            + struct.pack("<i", len(entries)) + b"".join(entries) + struct.pack("<i", 0))


class OsuDbTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_reads_both_star_rating_formats(self):
        for version in (20191106, osu_db.FLOAT_STARS):
            path = self.root / f"{version}.db"
            path.write_bytes(database(version, [entry(version, "Set", "a.osu"), entry(version, "Set", "b.osu", mode=0)]))
            read_version, maps = osu_db.read_osu_db(path)
            self.assertEqual(read_version, version)
            self.assertEqual([m["file"] for m in maps], ["a.osu", "b.osu"])
            info = osu_db.scan_info(maps[0], "p", core.GEN_TAG)
            self.assertEqual((info["keys"], info["od"], info["bpm"], info["bid"], info["version"]), (4, "8.25", 120, 7, "Hard"))
            self.assertIsNone(osu_db.scan_info(maps[1], "p", core.GEN_TAG))

    def test_old_format_with_entry_sizes(self):
        path = self.root / "old.db"
        path.write_bytes(database(20190906, [entry(20190906, "Set", "a.osu", cs=7.0)]))
        self.assertEqual(osu_db.read_osu_db(path)[1][0]["cs"], 7.0)

    def test_scan_uses_osu_db_only_while_the_file_is_unchanged(self):
        songs = self.root / "osu!" / "Songs"
        folder = songs / "Set"
        folder.mkdir(parents=True)
        chart = folder / "map.osu"
        chart.write_text("osu file format v14\n[General]\nMode: 3\n[Metadata]\nTitle:From file\n"
                         "[Difficulty]\nCircleSize:4\n[TimingPoints]\n0,500,4,1,0,100,1,0\n")
        ticks = osu_db.mtime_to_ticks(chart.stat().st_mtime_ns)
        db = songs.parent / "osu!.db"
        db.write_bytes(database(osu_db.FLOAT_STARS, [entry(osu_db.FLOAT_STARS, "Set", "map.osu", modified=ticks, title="From db")]))
        cache = str(self.root / "cache.json")
        with patch.object(core, "CACHE_PATH", cache), patch.object(core, "_running_osu_dir", return_value=None), \
                patch.object(core, "_registry_osu_dir", return_value=None):
            maps, stats = core.scan_songs(str(songs))
            self.assertEqual((maps[0]["title"], stats["from_osu_db"]), ("From db", 1))
            # Edited since osu! indexed it: the write time no longer matches, so the file is read.
            os.remove(cache)
            os.utime(chart, ns=(chart.stat().st_atime_ns, chart.stat().st_mtime_ns + 10 * 10**9))
            maps, stats = core.scan_songs(str(songs))
            self.assertEqual((maps[0]["title"], stats["from_osu_db"]), ("From file", 0))
            # A damaged osu!.db is ignored rather than breaking the scan.
            os.remove(cache)
            db.write_bytes(b"\x01\x02")
            maps, _ = core.scan_songs(str(songs))
            self.assertEqual(maps[0]["title"], "From file")


if __name__ == "__main__":
    unittest.main()
