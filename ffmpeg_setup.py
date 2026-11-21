"""Install a user-supplied FFmpeg executable without bundling it with Jatotrainer."""
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
from zipfile import ZipFile

EXE_NAME = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
DOWNLOAD_URL = "https://ffmpeg.org/download.html"


def managed_ffmpeg_path():
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") if os.name == "nt" else Path.home() / ".local" / "share"
    return base / "Jatotrainer" / "tools" / EXE_NAME


def install_ffmpeg(source, destination=None):
    """Copy only the executable, validate it, and publish it atomically."""
    source = Path(source)
    is_zip = source.suffix.casefold() == ".zip"
    if not is_zip and source.name.casefold() != EXE_NAME:
        raise ValueError(f"Choose {EXE_NAME} or a ZIP containing it.")
    destination = Path(destination or managed_ffmpeg_path()).absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ffmpeg-setup-", dir=destination.parent) as tmp:
        candidate = Path(tmp) / EXE_NAME
        if is_zip:
            with ZipFile(source) as archive:
                matches = [entry for entry in archive.infolist() if not entry.is_dir()
                           and PurePosixPath(entry.filename.replace("\\", "/")).name.casefold() == EXE_NAME]
                if len(matches) != 1:
                    raise ValueError(f"The ZIP must contain exactly one {EXE_NAME}.")
                if not 0 < matches[0].file_size <= 300 * 1024 * 1024:
                    raise ValueError("The FFmpeg executable in this ZIP has an unexpected size.")
                with archive.open(matches[0]) as stream, candidate.open("wb") as out:
                    shutil.copyfileobj(stream, out)
        else:
            shutil.copyfile(source, candidate)
        if os.name != "nt":
            candidate.chmod(0o700)
        try:
            probe = subprocess.run([str(candidate), "-version"], stdin=subprocess.DEVNULL,
                                   capture_output=True, timeout=10, cwd=tmp,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError("FFmpeg could not run. Choose a standalone build for your system.") from error
        if probe.returncode or not probe.stdout.startswith(b"ffmpeg version "):
            raise ValueError("FFmpeg could not run. Choose a standalone build for your system.")
        os.replace(candidate, destination)
    return str(destination)
