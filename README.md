# jatotrainer

A desktop trainer for generating osu!mania rate charts.

## Build the Windows x64 installer

The finished installer bundles the osu!stable reader, its .NET runtime and
FFmpeg. Players only install Jatotrainer; they do not need StreamCompanion,
FFmpeg, .NET, Python or MSYS2 separately.

For the person building the installer:

1. Install [64-bit Python 3.11 or newer](https://www.python.org/downloads/windows/)
   with Python on PATH, the [.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0),
   [MSYS2](https://www.msys2.org/) and [Inno Setup 6](https://jrsoftware.org/isdl.php).
2. Update MSYS2 following its setup instructions. In the **UCRT64** shell, install
   the compiler and build tools:
   ```sh
   pacman -S --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-nasm mingw-w64-ucrt-x86_64-pkgconf make diffutils
   ```
3. From Windows, run `build_installer.bat`. If MSYS2 is not in `C:/msys64`, set
   `JATO_MSYS2` to its installation folder first. The build compiles FFmpeg
   from the included source archives and publishes the reader as a self-contained
   Windows x64 executable.
4. For a public release, publish **both** files from `installer-output` next to
   each other: `jatotrainer-Setup.exe` and `jatotrainer-corresponding-source.zip`.
   Keep the source available for that exact binary release. Do the same for any
   portable binaries (`build.bat`, then `python source_release.py`).

The installer is unsigned and installs per user. Keep the whole
`dist/jatotrainer` folder together for a portable build. For Python development,
run `python -m pip install -r requirements.txt` and `python jatotrainer.py`.

The combined distribution is GPLv3 or later. Historical MIT notices and
third-party licenses are retained; see `THIRD_PARTY.md`.

# Jatotrainer Features

Jatotrainer is a Windows tool for osu!mania. Generate several rates of a chart in one pass, build a custom practice pack, or convert charts between osu!mania and StepMania.

- **Batch rates:** Generate multiple rates at once, with preview points, Kiai timing, bookmarks, and BPM adjusted for each rate.
- **Practice settings:** Customize difficulty names and OD, and choose whether pitch changes with the rate or stays the same.
- **Chart selection:** Browse your Songs folder, follow the selected chart in osu!stable without requiring tosu, or use Compact Mode for quick conversions.
- **Pack Maker:** Combine charts into a practice pack, choose rates per chart, and reduce pack size with audio and background compression.
- **(BETA) StepMania conversion:** Convert individual charts or whole packs between osu!mania and StepMania, with timing checks and logs for unsupported features.

# Compact mode

- Transforms the app into a small compact window for the rate changer
