"""Headless unit tests for LN <-> tap Note conversion."""
import unittest

import ln_transform


def _times(lines):
    out = []
    for line in lines:
        p = line.split(",")
        typ = int(p[3])
        end = int(p[5].split(":", 1)[0]) if (typ & 128) else None
        out.append((int(p[0]), int(p[2]), bool(typ & 128), end, int(p[4]), p[5]))
    return out


class LnTransformTests(unittest.TestCase):
    def test_off_mode_validation_and_tags(self):
        lines = ["64,192,1000,1,0,0:0:0:0:", "192,192,1000,128,0,2000:0:0:0:0:"]
        self.assertEqual(ln_transform.transform_hit_objects(lines, ["0,500,4,2,0,100,1,0"], mode="off"), lines)
        self.assertEqual(ln_transform.mode_tag("off"), "")
        self.assertEqual(ln_transform.mode_tag("ln_to_notes", density="head"), "NoLN")
        self.assertEqual(ln_transform.mode_tag("ln_to_notes", density="head_tail"), "NoLN H+T")
        self.assertEqual(ln_transform.mode_tag("ln_to_notes", density="1/4"), "NoLN 1/4")
        self.assertEqual(ln_transform.mode_tag("notes_to_ln", gap="1/4"), "FullLN 1/4")
        with self.assertRaises(ValueError):
            ln_transform.validate_options(mode="bad")
        with self.assertRaises(ValueError):
            ln_transform.validate_options(density="1/16")
        with self.assertRaises(ValueError):
            ln_transform.validate_options(gap="head")

    def test_beat_length_at_multi_bpm_ignores_inherited(self):
        timing = [
            "1000,500,4,2,0,100,1,0",   # 120 BPM
            "1500,-50,4,2,0,100,0,0",   # inherited green line -> ignored
            "2000,250,4,2,0,100,1,0",   # 240 BPM
        ]
        red = ln_transform.parse_red_timing_points(timing)
        self.assertEqual(ln_transform.beat_length_at(red, 500), 500.0)
        self.assertEqual(ln_transform.beat_length_at(red, 1750), 500.0)
        self.assertEqual(ln_transform.beat_length_at(red, 2000), 250.0)
        self.assertEqual(ln_transform.beat_length_at(red, 3000), 250.0)
        self.assertEqual(ln_transform.beat_length_at([], 1000), ln_transform.DEFAULT_BEAT_MS)

    def test_ln_to_notes_head_and_head_tail(self):
        timing = ["0,500,4,2,0,100,1,0"]
        lines = [
            "64,192,1000,133,2,2000:1:2:0:0:hit.wav",  # 128 + 4 (new combo) + 1
            "192,192,1200,1,8,0:0:0:0:",
        ]
        head_only = ln_transform.transform_hit_objects(lines, timing, keys=4, mode="ln_to_notes", density="head")
        parsed_head = _times(head_only)
        self.assertEqual(len(parsed_head), 2)
        self.assertEqual(parsed_head[0], (64, 1000, False, None, 2, "1:2:0:0:hit.wav"))
        self.assertEqual(int(head_only[0].split(",")[3]), 5)  # 4 (new combo) | 1 (tap), 128 cleared
        self.assertEqual(parsed_head[1], (192, 1200, False, None, 8, "0:0:0:0:"))

        head_tail = ln_transform.transform_hit_objects(lines, timing, keys=4, mode="ln_to_notes", density="head_tail")
        self.assertEqual([(x, t, hs) for x, t, _, _, hs, _ in _times(head_tail)], [
            (64, 1000, 2),
            (192, 1200, 8),
            (64, 2000, 0),
        ])

        # Collision guard: existing note within 5ms in same column suppresses tail note.
        colliding = [
            "64,192,1000,128,0,2000:0:0:0:0:",
            "64,192,2002,1,0,0:0:0:0:",
        ]
        guarded = ln_transform.transform_hit_objects(colliding, timing, keys=4, mode="ln_to_notes", density="head_tail")
        self.assertEqual([t for _, t, *_ in _times(guarded)], [1000, 2002])

    def test_ln_to_notes_densities_and_mid_ln_bpm_change(self):
        timing = ["1000,500,4,2,0,100,1,0"]  # 120 BPM (500ms/beat)
        ln = ["64,192,1000,128,2,2000:1:2:0:0:hit.wav"]
        expected_counts = {
            "1/1": 3,  # 1000, 1500, 2000
            "1/2": 5,  # 1000, 1250, 1500, 1750, 2000
            "1/3": 7,
            "1/4": 9,  # 1000..2000 every 125ms
            "1/6": 13,
            "1/8": 17,
        }
        for density, count in expected_counts.items():
            out = ln_transform.transform_hit_objects(ln, timing, keys=4, mode="ln_to_notes", density=density)
            parsed = _times(out)
            self.assertEqual(len(parsed), count, density)
            self.assertTrue(all(not hold for _, _, hold, *_ in parsed))
            self.assertEqual(parsed[0][4], 2)
            self.assertEqual(parsed[0][5], "1:2:0:0:hit.wav")
            for p in parsed[1:]:
                self.assertEqual(p[4], 0)
                self.assertEqual(p[5], "0:0:0:0:")
        out_1_4 = ln_transform.transform_hit_objects(ln, timing, keys=4, mode="ln_to_notes", density="1/4")
        self.assertEqual([t for _, t, *_ in _times(out_1_4)], [1000, 1125, 1250, 1375, 1500, 1625, 1750, 1875, 2000])

        # Mid-LN BPM change: 120 BPM at 1000 (1/2 = 250ms), 240 BPM at 1500 (1/2 = 125ms)
        multi_timing = ["1000,500,4,2,0,100,1,0", "1500,250,4,2,0,100,1,0"]
        multi_out = ln_transform.transform_hit_objects(ln, multi_timing, keys=4, mode="ln_to_notes", density="1/2")
        self.assertEqual([t for _, t, *_ in _times(multi_out)], [1000, 1250, 1500, 1625, 1750, 1875, 2000])

    def test_notes_to_ln_gaps_jacks_chords_breaks_and_existing_lns(self):
        timing = ["0,500,4,2,0,100,1,0"]  # 120 BPM (500ms/beat)
        # Normal spacing + tight jack + second column chord + existing LN + trailing note
        lines = [
            "64,192,1000,1,0,0:0:0:0:",
            "192,192,1000,5,0,0:0:0:0:",      # chord in col 1 (new combo bit 4 + 1)
            "64,192,2000,1,0,0:0:0:0:",      # next in col 0: 1000ms later
            "64,192,2125,1,0,0:0:0:0:",      # tight 1/4 jack (125ms after 2000) -> stays tap
            "320,192,1000,128,0,1500:0:0:0:0:",  # existing LN preserved
            "320,192,2500,1,0,0:0:0:0:",     # last in col 2 -> +1 beat (3000)
        ]
        out = ln_transform.transform_hit_objects(lines, timing, keys=4, mode="notes_to_ln", gap="1/4")
        parsed = _times(out)
        # Col 0: 1000 -> 1875 (2000 - 125), 2000 stays tap (2125 - 125 == 2000 < 15ms), 2125 -> 2625 (last in col 0)
        # Col 1: 1000 -> 1500 (last in col 1, keeps new-combo bit 4: 4|128 = 132)
        # Col 2: 1000..1500 preserved, 2500 -> 3000
        self.assertEqual([(x, t, h, end) for x, t, h, end, *_ in parsed], [
            (64, 1000, True, 1875),
            (192, 1000, True, 1500),
            (320, 1000, True, 1500),
            (64, 2000, False, None),
            (64, 2125, True, 2625),
            (320, 2500, True, 3000),
        ])
        self.assertEqual(int(out[1].split(",")[3]), 132)  # new combo preserved on LN

        # Break clamping: break starts at 1600 -> LN starting at 1000 clamps end to 1600
        events = ["2,1600,3000", "Break,4000,5000"]
        broken = ln_transform.transform_hit_objects(
            ["64,192,1000,1,0,0:0:0:0:", "64,192,3500,1,0,0:0:0:0:"],
            timing, keys=4, mode="notes_to_ln", gap="1/4", event_lines=events,
        )
        self.assertEqual([(t, h, end) for _, t, h, end, *_ in _times(broken)], [
            (1000, True, 1600),
            (3500, True, 4000),
        ])

        # Verify different gaps produce expected end times
        pair = ["64,192,1000,1,0,0:0:0:0:", "64,192,2000,1,0,0:0:0:0:"]
        for gap, expected_end in (("1/1", 1500), ("1/2", 1750), ("1/3", 1833), ("1/4", 1875), ("1/6", 1917), ("1/8", 1938)):
            res = _times(ln_transform.transform_hit_objects(pair, timing, keys=4, mode="notes_to_ln", gap=gap))
            self.assertEqual(res[0][3], expected_end, gap)


if __name__ == "__main__":
    unittest.main()
