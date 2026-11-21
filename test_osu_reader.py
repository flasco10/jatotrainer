"""Native reader selection and fallback checks."""
import unittest
from unittest.mock import patch

from piotrekol_reader import selection
from test_generation import m as core


class ReaderTests(unittest.TestCase):
    def test_ipc_snapshot_preserves_beatmap_identity(self):
        current = selection({"folder": "Song set", "file": "Song [Hard].osu", "bid": 42, "md5": "a" * 32})
        self.assertEqual((current["folder"], current["file"], current["bid"], current["md5"]),
                         ("Song set", "Song [Hard].osu", 42, "a" * 32))
        self.assertIsNone(selection({"folder": "..", "file": "Song.osu"}))
        self.assertIsNone(selection({"folder": "Song set", "file": "../Song.osu"}))
        self.assertIsNone(selection(None))

    def test_native_reader_precedes_tosu_and_title_fallback(self):
        data = selection({"folder": "Song set", "file": "Song [Hard].osu"})
        with patch("piotrekol_reader.reader.poll", return_value=data), patch.object(core, "fetch_tosu") as tosu:
            self.assertEqual(core.current_selection(), data)
            tosu.assert_not_called()
        with patch("piotrekol_reader.reader.poll", return_value=None), patch.object(core, "fetch_tosu", return_value=None), patch.object(core, "osu_window_title", return_value="osu! - Artist - Song [Hard]"):
            self.assertEqual(core.current_selection()["version"], "Hard")


if __name__ == "__main__":
    unittest.main()
