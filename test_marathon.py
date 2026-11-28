import math
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from PIL import Image

import jatotrainer as core
import marathon_backend as mb


def chart(audio, bg, keys=4, notes=(1000, 2000), hold=None, title="Song", timing="0,500,4,1,0,100,1,0"):
    objects = [f"64,192,{t},1,0,0:0:0:0:" for t in notes]
    if hold:
        objects.append(f"192,192,{hold[0]},128,0,{hold[1]}:0:0:0:0:custom.wav")
    return (f"osu file format v14\n\n[General]\nAudioFilename: {audio}\nPreviewTime: 1000\nMode: 3\n\n"
            f"[Metadata]\nTitle:{title}\nArtist:Artist {title}\nCreator:C\nVersion:Hard\n\n"
            f"[Difficulty]\nHPDrainRate:8\nCircleSize:{keys}\nOverallDifficulty:8\n\n"
            f'[Events]\n0,0,"{bg}",0,0\n\n[TimingPoints]\n{timing}\n\n[HitObjects]\n' + "\n".join(objects) + "\n")


class LayoutTests(unittest.TestCase):
    def test_two_maps_are_side_by_side_halves(self):
        rects = mb.collage_layout([1, 1], gap=0)
        self.assertEqual(rects, [(0, 0, 960, 1080), (960, 0, 960, 1080)])

    def test_seven_maps_with_one_long_map_match_reference_layout(self):
        # Four on top; the long sixth map gets a double-width slot on the bottom row.
        rects = mb.collage_layout(mb.auto_weights([180, 180, 180, 180, 180, 360, 180]), gap=0)
        self.assertEqual([r[1] for r in rects], [0, 0, 0, 0, 540, 540, 540])
        self.assertEqual([r[2] for r in rects], [480, 480, 480, 480, 480, 960, 480])

    def test_up_to_four_maps_sit_side_by_side(self):
        rects = mb.collage_layout([1] * 4, gap=0)
        self.assertEqual(rects, [(0, 0, 480, 1080), (480, 0, 480, 1080), (960, 0, 480, 1080), (1440, 0, 480, 1080)])

    def test_rows_fill_up_to_max_per_row(self):
        self.assertEqual([mb.auto_row_count(n) for n in (1, 2, 4, 5, 8, 9, 12)], [1, 1, 1, 2, 2, 3, 3])
        self.assertEqual(mb.auto_row_count(5, per_row=5), 1)
        # Five maps: the extra map goes to the upper row (3 + 2).
        rects = mb.collage_layout([1] * 5, gap=0)
        self.assertEqual([r[1] for r in rects], [0, 0, 0, 540, 540])
        rects = mb.collage_layout([1] * 12, gap=0)
        self.assertEqual(len({r[1] for r in rects}), 3)

    def test_all_in_one_row(self):
        self.assertEqual(mb.auto_row_count(12, per_row=None), 1)
        rects = mb.collage_layout([1, 1, 2, 1, 1, 1, 1], gap=0, per_row=None)
        self.assertEqual({r[1] for r in rects}, {0})
        self.assertEqual(rects[2][2], 2 * rects[0][2])  # the long song is still twice as wide

    def test_focus_pans_the_crop(self):
        image = Image.new("RGB", (1600, 900), "blue")
        image.paste(Image.new("RGB", (400, 900), "red"), (0, 0))
        rect = [(0, 0, 200, 1080)]
        left = mb.render_collage([image], rect, (200, 1080), focus=[0.0])
        center = mb.render_collage([image], rect, (200, 1080), focus=[0.5])
        self.assertGreater(left.getpixel((100, 500))[0], 200)
        self.assertGreater(center.getpixel((100, 500))[2], 200)

    def test_manual_rows_and_tiles_cover_canvas(self):
        rects = mb.collage_layout([1, 2, 1], rows=[1, 2, None], gap=4)
        self.assertEqual(rects[0][:2], (0, 0))
        self.assertEqual(rects[0][2], 1920)  # alone on row 1
        self.assertEqual(rects[1][1], rects[2][1])  # map 3 follows map 2 onto row 2
        self.assertGreater(rects[1][2], rects[2][2])
        for x, y, w, h in rects:
            self.assertTrue(0 <= x and x + w <= 1920 and 0 <= y and y + h <= 1080)

    def test_auto_weights(self):
        self.assertEqual(mb.auto_weights([100, 110, 90, 400]), [1, 1, 1, 4])
        self.assertEqual(mb.auto_weights([]), [])


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg unavailable")
class MarathonBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.songs = self.root / "Songs"
        self.songs.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def make_set(self, name, seconds, color, **kwargs):
        folder = self.songs / name
        folder.mkdir()
        with wave.open(str(folder / "audio.wav"), "wb") as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(44100)
            f.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(int(44100 * seconds))))
        Image.new("RGB", (800, 600), color).save(folder / "bg.png")
        path = folder / "map.osu"
        path.write_text(chart("audio.wav", "bg.png", title=name, **kwargs))
        return str(path)

    def build(self, entries, **kwargs):
        return mb.build_marathon(core, self.songs, "Test Marathon", "Me", 8, 7, entries, shutil.which("ffmpeg"), **kwargs)

    def test_songs_are_joined_with_rates_and_breaks(self):
        a = self.make_set("A", 3.0, "red", hold=(2500, 2800))
        b = self.make_set("B", 2.0, "blue", notes=(500, 1500), timing="-20,400,4,1,0,100,1,0")
        folder, offsets = self.build([dict(path=a, rate=1.0, break_after=2), dict(path=b, rate=1.25, pitch=False)])
        # Song B starts after 3 s of song A plus the 2 s break.
        self.assertEqual(offsets, [0, 5000])
        out = Path(folder)
        osu = next(out.glob("*.osu")).read_text(encoding="utf-8")
        _, sections = core.parse_osu_text(osu)
        times = [int(line.split(",")[2]) for line in core.sec(sections, "HitObjects")]
        self.assertEqual(times, [1000, 2000, 2500, 5400, 6200])  # B notes at 500/1.25 and 1500/1.25 + 5000
        hold = core.sec(sections, "HitObjects")[2]
        self.assertTrue(hold.endswith("2800:0:0:0:0:"), hold)  # custom hitsound file dropped
        timing = [int(line.split(",")[0]) for line in core.sec(sections, "TimingPoints")]
        self.assertEqual(timing, [0, 4984, 4984])  # -20 ms at 1.25x is -16 ms before song B; + its scroll fix
        self.assertEqual(core.kv(core.sec(sections, "Editor"), "Bookmarks"), "0,5000")
        self.assertEqual(core.kv(core.sec(sections, "Difficulty"), "OverallDifficulty"), "8")
        self.assertEqual(core.kv(core.sec(sections, "Difficulty"), "CircleSize"), "4")
        # Total audio length: 3 s + 2 s break + 2 s / 1.25.
        with Image.open(out / "background.jpg") as bg:
            self.assertEqual(bg.size, (1920, 1080))
            self.assertGreater(bg.getpixel((400, 500))[0], 200)  # left half red
            self.assertGreater(bg.getpixel((1500, 500))[2], 200)  # right half blue
        self.assertTrue((out / "audio.mp3").stat().st_size > 1000)

    def test_long_gap_becomes_break_period(self):
        a = self.make_set("A", 2.0, "red")
        b = self.make_set("B", 2.0, "blue")
        _, offsets = self.build([dict(path=a, break_after=5), dict(path=b)])
        osu = next(Path(self.songs / "Various Artists - Test Marathon").glob("*.osu")).read_text(encoding="utf-8")
        _, sections = core.parse_osu_text(osu)
        # A's last note at 2000, B's first at 7000 + 1000.
        self.assertIn("2,3000,7000", core.sec(sections, "Events"))

    def test_long_intro_and_outro_are_skipped(self):
        # A: 10 s of audio, notes only at 6-7 s. Keeps 2 s before (from 4 s) and 1 s after (to 8 s).
        a = self.make_set("A", 10.0, "red", notes=(6000, 7000))
        b = self.make_set("B", 6.0, "blue", notes=(4500, 5000), timing="0,500,4,1,0,100,1,0")
        folder, offsets = self.build([dict(path=a, break_after=2), dict(path=b)])
        self.assertEqual(offsets, [0, 6000])  # 4 s of A + 2 s break, not 10 s + 2 s
        _, sections = core.parse_osu_text(next(Path(folder).glob("*.osu")).read_text(encoding="utf-8"))
        times = [int(line.split(",")[2]) for line in core.sec(sections, "HitObjects")]
        self.assertEqual(times, [2000, 3000, 8000, 8500])  # B cut from 2.5 s: 6000 + (4500|5000 - 2500)
        timing = [int(line.split(",")[0]) for line in core.sec(sections, "TimingPoints")]
        self.assertEqual(timing, [0, 3500])  # B's 0 ms point moves with B's notes, so beats stay on the grid
        self.assertEqual(core.kv(core.sec(sections, "General"), "PreviewTime"), "0")  # 1000 was cut away
        audio = mb.subprocess.run([shutil.which("ffmpeg"), "-i", str(Path(folder) / "audio.mp3")],
                                  capture_output=True, text=True).stderr
        h, m, s = audio.split("Duration: ")[1].split(",")[0].split(":")
        self.assertAlmostEqual(float(s) + 60 * int(m), 9.5, delta=0.15)  # 4 + 2 + 3.5 s

    def test_each_song_keeps_its_own_scroll_speed(self):
        # A: 120 BPM and longest, so the marathon's main BPM. B: 240 BPM with its own 1.5x SV section.
        a = self.make_set("A", 6.0, "red", notes=(1000, 5000), timing="0,500,4,1,0,100,1,0")
        b = self.make_set("B", 3.0, "blue", notes=(500, 2500),
                          timing="0,250,4,1,0,100,1,0\n1000,-66.6666666667,4,1,0,100,0,0")
        folder, _ = self.build([dict(path=a), dict(path=b)])
        _, sections = core.parse_osu_text(next(Path(folder).glob("*.osu")).read_text(encoding="utf-8"))
        points = [line.split(",")[:2] for line in core.sec(sections, "TimingPoints")]
        a_points, b_points = points[:1], points[1:]
        self.assertEqual(a_points, [["0", "500"]])  # A is the main BPM: untouched
        # B: red point gets a 0.5x green (250/500), and its 1.5x section becomes 0.75x.
        self.assertEqual([p[0] for p in b_points], ["6000", "6000", "7000"])
        self.assertEqual(float(b_points[0][1]), 250)
        self.assertAlmostEqual(-100 / float(b_points[1][1]), 0.5)
        self.assertAlmostEqual(-100 / float(b_points[2][1]), 0.75)

    def test_main_beat_is_longest_lasting(self):
        lines = ["0,500,4,1,0,100,1,0", "1000,-50,4,1,0,100,0,0", "2000,250,4,1,0,100,1,0"]
        self.assertEqual(mb._main_beat(lines, 10000), 250)  # 8 s at 250 vs 2 s at 500
        self.assertEqual(mb._main_beat(lines, 3000), 500)

    def test_trim_off_keeps_full_audio(self):
        a = self.make_set("A", 10.0, "red", notes=(6000, 7000))
        b = self.make_set("B", 2.0, "blue")
        _, offsets = self.build([dict(path=a, break_after=2), dict(path=b)], trim=False)
        self.assertEqual(offsets, [0, 12000])

    def test_rejects_mixed_key_counts_without_writing(self):
        a = self.make_set("A", 1.0, "red")
        b = self.make_set("B", 1.0, "blue", keys=7)
        with self.assertRaisesRegex(ValueError, "same key count"):
            self.build([dict(path=a), dict(path=b)])
        self.assertFalse((self.songs / "Various Artists - Test Marathon").exists())


if __name__ == "__main__":
    unittest.main()
