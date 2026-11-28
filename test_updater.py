import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import updater


def release(tag, name="jatotrainer-9.9.9-Setup.exe", **extra):
    return dict(tag_name=tag, html_url="https://example/rel", assets=[
        dict(name="jatotrainer-portable.zip", browser_download_url="zip"),
        dict(name=name, browser_download_url="https://example/setup.exe", size=10, digest="sha256:ab")], **extra)


class UpdaterTests(unittest.TestCase):
    def test_version_tuple(self):
        self.assertEqual(updater.version_tuple("v1.6.0"), (1, 6, 0))
        self.assertEqual(updater.version_tuple("1.6"), (1, 6, 0))
        self.assertEqual(updater.version_tuple("1.10.0-beta1"), (1, 10, 0))
        self.assertGreater(updater.version_tuple("1.10.0"), updater.version_tuple("1.9.9"))
        self.assertEqual(updater.version_tuple("garbage"), (0, 0, 0))

    def test_pick_update_only_newer_stable_installer(self):
        found = updater.pick_update(release("v1.7.0"), "1.6.0")
        self.assertEqual((found["version"], found["url"], found["digest"]), ("1.7.0", "https://example/setup.exe", "sha256:ab"))
        self.assertIsNone(updater.pick_update(release("v1.6.0"), "1.6.0"))
        self.assertIsNone(updater.pick_update(release("v1.5.0"), "1.6.0"))
        self.assertIsNone(updater.pick_update(release("v1.7.0", prerelease=True), "1.6.0"))
        self.assertIsNone(updater.pick_update(release("v1.7.0", name="notes.txt"), "1.6.0"))

    def test_download_verifies_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.exe"
            src.write_bytes(b"installer bytes" * 1000)
            good = hashlib.sha256(src.read_bytes()).hexdigest()
            out = Path(tmp) / "out"; out.mkdir()
            update = dict(name="jatotrainer-1.7.0-Setup.exe", url=src.as_uri(), size=0, digest="sha256:" + good)
            seen = []
            path = updater.download_update(update, seen.append, str(out))
            self.assertEqual(Path(path).read_bytes(), src.read_bytes())
            self.assertAlmostEqual(seen[-1], 1.0)

            os.remove(path)
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                updater.download_update(dict(update, digest="sha256:" + "0" * 64), None, str(out))
            self.assertFalse(os.path.exists(path))  # a bad download is not left behind
            with self.assertRaisesRegex(RuntimeError, "no checksum"):
                updater.download_update(dict(update, digest=""), None, str(out))

    def test_is_installed_only_for_inno_install(self):
        self.assertFalse(updater.is_installed())  # running from source
        with tempfile.TemporaryDirectory() as tmp, patch.object(updater.sys, "frozen", True, create=True), \
                patch.object(updater.sys, "executable", os.path.join(tmp, "jatotrainer.exe")):
            self.assertFalse(updater.is_installed())
            Path(tmp, "unins000.exe").touch()
            self.assertTrue(updater.is_installed())


if __name__ == "__main__":
    unittest.main()
