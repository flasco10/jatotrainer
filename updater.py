"""In-app updates from the GitHub releases page: check, download, verify, run the installer."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

REPO = "flasco10/jatotrainer"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
HEADERS = {"User-Agent": "jatotrainer-updater", "Accept": "application/vnd.github+json"}


def version_tuple(text):
    """'v1.6.0' / '1.6' -> (1, 6, 0); suffixes like '-beta1' are ignored."""
    m = re.match(r"v?(\d+(?:\.\d+)*)", str(text).strip())
    nums = [int(n) for n in m.group(1).split(".")] if m else [0]
    return tuple((nums + [0, 0, 0])[:3])


def is_installed():
    """True for the Inno Setup install (it can update in place); False for portable or source runs."""
    if not getattr(sys, "frozen", False):
        return False
    return os.path.exists(os.path.join(os.path.dirname(sys.executable), "unins000.exe"))


def pick_update(release, current):
    """The newer release's installer asset from a GitHub release JSON, or None."""
    version = release.get("tag_name", "")
    if release.get("draft") or release.get("prerelease") or version_tuple(version) <= version_tuple(current):
        return None
    for asset in release.get("assets", []):
        if asset.get("name", "").lower().endswith("-setup.exe"):
            return dict(version=version.lstrip("v"), name=asset["name"], url=asset["browser_download_url"],
                        size=asset.get("size", 0), digest=asset.get("digest") or "",
                        page=release.get("html_url") or RELEASES_PAGE)
    return None


def check_for_update(current, timeout=8):
    with urllib.request.urlopen(urllib.request.Request(LATEST_URL, headers=HEADERS), timeout=timeout) as r:
        return pick_update(json.load(r), current)


def download_update(update, progress=None, dest_dir=None):
    """Download the installer and check it against GitHub's SHA-256; returns the file path."""
    algo, _, expected = update["digest"].partition(":")
    if algo != "sha256" or not expected:
        # GitHub gives every release asset a digest; without one we can't tell the download is intact.
        raise RuntimeError("The release has no checksum, so the download can't be verified.")
    dest_dir = dest_dir or tempfile.mkdtemp(prefix="jatotrainer-update-")
    path = os.path.join(dest_dir, os.path.basename(update["name"]))
    sha = hashlib.sha256()
    done = 0
    req = urllib.request.Request(update["url"], headers={"User-Agent": HEADERS["User-Agent"]})
    with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or update.get("size") or 0)
        while chunk := r.read(256 * 1024):
            f.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    if sha.hexdigest().lower() != expected.lower():
        os.remove(path)
        raise RuntimeError("The download didn't match its checksum and was deleted. Try again later.")
    return path


def run_installer(path):
    """Start the installer silently; it closes this app, updates in place and reopens it."""
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     close_fds=True)
