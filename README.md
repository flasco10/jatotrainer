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

## New interface

- Near-black surfaces, blue-violet accents, rounded cards, and a jatotrainer header.
- “Collapse sidebar” / “Expand sidebar” hides or restores the chart library,
  search bar, key filter, and manual selection without losing their state.
- Detect from osu! and Follow osu! remain accessible in the header.
- Conversion logs expand downward beneath their toggle. Hidden logs continue
  recording. Errors automatically expand the logs.
- The rounded progress bar smoothly advances when each rate completes, turns
  green at successful completion, and shows red on failure. It resets to blue
  for a new conversion. The percentage counts completed rates, not FFmpeg time.
- Sidebar and log visibility persist across launches.

## Existing behavior preserved

The working 320 kbps CBR preview conversion, readable filenames, collision
protection, rate/timing conversion, and central audio cache are retained.

Example names with difficulty format `{diff} x{rate}`:
`Fellowship - Hold Up Your Hearts (Again) (Jhown) [ Obstinacy  x1.3] [mmr-x1.3].osu`
and `audio x1.3 mmr.mp3`. Different contents get numbered suffixes rather than
being overwritten. Settings and checksums are stored outside Songs. Verified
legacy `.mp3.json` files migrate when generating in their song folder.

The user files retain legacy `.mania_multirate...` names for compatibility
with your existing installation and saved settings. The window, installer,
shortcuts, executable, and package name use jatotrainer. Generated charts keep
`mmr` naming and tags as previously requested.

External .osb storyboards, storyboard variables, and videos remain unsupported
and stop generation with an explanation. The optional OD formula is unchanged.
Use one instance at a time for generation.

## Validation

All 21 tests passed in the build environment: 17 backend regressions and
4 real-widget tests under a virtual display. Expanded/collapsed layouts
were also rendered and inspected. Windows binaries were not compiled here.


Run `python -m unittest -v test_generation` for backend regression tests,
including real FFmpeg duration, frequency and constant-bitrate checks.
Run `python -m unittest -v test_ui` in a desktop session (or using xvfb-run
on Linux) for real-widget layout and interaction checks.
Windows packaging and install/uninstall must be validated on Windows.

## Custom chart card and OD

The chart card follows the supplied mockup: title, mapper, difficulty, blue
key/BPM/base OD badges, and rounded gold tiles for chosen rates. Manual rates
appear immediately and wrap into new rows. The local background image is loaded
from the selected .osu file's [Events] background entry, cropped to fit and dimmed
for readability. Missing backgrounds fall back to the dark card.

Enable **Set fixed OD (0–10)** to write a chosen OverallDifficulty to every
generated chart. Decimals are supported. Fixed OD takes priority over OD scaling;
when disabled, the existing preserve/scale behavior remains. Originals are unchanged.
Fixed OD is enabled by default for new configurations. The blue OD badge follows
the fixed OD value when enabled, and shows the source OD when disabled. Saved
choices are respected. Presets include {diff} x{rate} [{bpm}] and {diff} x{rate}.

The chart card uses tighter adaptive spacing and centered badges. Convert charts
and its progress bar stay pinned below the scrollable settings and logs, including
at the minimum window size.

## Logo and font

The supplied logo is used in the header, window icon, Windows executable and
installer. Poppins Regular and Bold are bundled with their OFL license. Fonts
load privately at startup; no separate font installation is required. Rebuild
with build_installer.bat on Windows to apply the logo to the installer/executable.

## Pack maker (v1.3.1)

Click **Pack maker**, immediately left of **Collapse sidebar**. Enter the pack
name, pack creator, OD and HP (0–10). Pack maker opens inside jatotrainer; **Back**
returns to the rate changer and keeps the pack draft for your next visit. It has
its own Songs path, search, scan, Detect from osu! and Follow osu!. Add charts and
edit each card's rates.

For live detection, run osu!stable and select a chart. Use **Detect from osu!**,
**Follow osu!**, or Pack Maker's detect button. The bundled reader uses
Piotrekol's ProcessMemoryDataFinder and reads the selected chart from osu!stable.
If it cannot find the chart, tosu/gosumemory and the gameplay window title remain
fallbacks. You can also choose a chart manually.

Each compact card uses the chart's background. The cog edits Diffname, Artist,
ArtistUnicode and tags. Diffname is a base name; non-original rates add x<rate>.
**Pitch** starts enabled (blue) for new charts. Clicking it turns it off (gray).
Rate 1 preserves timing and pitch. Other rates convert audio and timing.
Artist and ArtistUnicode retain their source values by default. The pack-wide
**Various Artists** switch replaces both. The cog's artist mode can override
that switch per chart with **Use chart fields** or **Various Artists**.

**Compression** offers Original and 128/160/192/224/256/320 kbps. Every target is
capped at its source bitrate and rounded down to a supported MP3 bitrate, so a
192 kbps source selected for 256 kbps still exports at 192 kbps. Original copies
rate-1 audio unchanged; rate variants use the source bitrate up to MP3's maximum
of 320 kbps. Sources below 128 kbps retain their lower bitrate. If FFmpeg cannot
read the source bitrate, explicit compression reports an error; Original rate
audio falls back to 320 kbps. FFmpeg is required for rates or compression.

**8-bit backgrounds** exports 256-color indexed PNGs with transparency preserved.
It reduces color depth, not dimensions. Indexed PNG can be larger than a source
JPEG, depending on the image. Identical background contents are shared across
all charts and rates, even if the originals have different filenames.

**Create pack** prepares the output and creates a new
`Songs/Various Artists - <pack name>` folder. Existing folders are never
overwritten; originals stay untouched. Files use song-title names and numbered
collision suffixes. Audio and background references point to the exported files.
Each chart gets the pack creator, shared OD/HP, BeatmapID 0, BeatmapSetID -1 and
the pack title. Title uses ASCII transliteration; TitleUnicode preserves the
entered name. Version defaults to `Song title [original charter]` with x<rate>
for rates, or the cog's edited name. The .osu filename remains
`Various Artists - <pack title> (<pack creator>) [<Version>].osu`.

Charts with video, storyboard or explicit custom hitsound attachments are
rejected because they need extra files beyond this export format. A missing
background/audio or failed conversion leaves no new pack folder. Press F5 in
osu! after creation. Rebuild on Windows with **build.bat** for a testing EXE or
**build_installer.bat** for the installer. Pillow is explicitly included in the
requirements. Validation: `python -m unittest test_generation test_pack test_ui`.

## Compact cards and side panels

Pack setup, chart options, compression and Songs folder browsing are anchored
panels beside the clicked button. They flip left at the right edge and remain
inside the app. Use × or Done/Save to dismiss; opening a different panel replaces
the current one. Folder browsing supports typed paths, double-clicking folders,
Up and Windows drive selection; **Use this folder** confirms the current path.
Back dismisses open panels and retains the pack draft.

Chosen chart cards are 118 px tall (previously 166); the selection preview is
76 px (previously 125). Buttons draw directly over the background, eliminating
opaque rectangular backing around their rounded edges. Long titles fit up to
two lines. Text in controls and chart canvases shifts slightly down for Poppins
alignment. Main rate-changer pitch defaults on for new configurations while
respecting saved preferences.

When **Various Artists** is enabled, **Include artist in diffname** appears.
It defaults off. When enabled, the original/chart-options artist prefixes the
difficulty: `Fellowship - Hold Up Your Hearts Again [Jhown]`. Creator remains
the typed pack creator. The exported Version and filename use the same name;
rate suffixes are still added. Charts overriding to Use chart fields do not
receive the prefix. Turning Various Artists off hides and bypasses this option.

## Compact rate changer

Click **Compact** in the full-mode header to switch the same window to 300×500.
The arrow returns to the previous full window size. Compact mode remains active
until you click that arrow and automatically enables Follow osu!; returning
restores your previous Follow setting. It uses your full-mode difficulty name
format, selected chart, rates and pitch setting.

The small background chart card shows title, difficulty, artist and mapper.
Base BPM is shown beside a list of target BPM values for every selected rate. Preset buttons toggle selected
rates from 0.80× through 1.40× in 0.05 steps. The 0.5×–2× slider moves in 0.01
steps and shows its rate beside an **Add** button. Moving the slider chooses a pending
rate; Add includes it without replacing existing rates or adding duplicates.
The entry accepts one or several rates, including outside the slider range. OD and HP sliders use 0.1 steps from 0 to 10;
compact mode enables fixed OD. HP initially follows each selected source chart
and is applied only to conversions started in compact mode. Pitch is blue when
on and gray when off. Cards and controls have rounded corners. **Create map**
is pinned at the bottom and becomes blank and disabled during conversion. Its
progress bar sits below the button and turns green on completion. The full UI and Pack maker remain
available after returning. Rebuild with build.bat to include compact_mode.py.

Pack maker rate exports parse transformed charts in memory, avoiding Windows
text-mode CRLF conversion. Background references are rewritten by their event
contents rather than source row numbers, so comments remain intact and rates
retain the source's single background event without inserting a duplicate.

Compact conversion status distinguishes newly created charts from exact repeats
that already exist. Click the compact status line to open Output details with
the generated difficulty names and full output paths. This also exposes errors
and conversion logs without leaving compact mode. A real FFmpeg UI regression
checks that Create map writes a chart and audio and reports repeats accurately.

The compact header has a **Rescan** button in place of the Follow label. Follow
osu! remains enabled in compact mode. Songs is automatically rescanned after
new rate charts are written; exact repeats do not trigger an unnecessary scan.
If Follow detects a newly imported chart that is not indexed yet, it rescans
and retries that selection. Scans run in the background and preserve the source
selection and conversion result. This refreshes jatotrainer's index; osu! may
still need F5 to load files newly generated on disk.

Compact polling only redraws control text/state/colors when they change. The
Rescan button has a fixed header grid position to prevent repeated redraw jitter.

## StepMania conversion

The **StepMania conversion** button opens a separate page inside jatotrainer.
**Back** returns to the rate changer; your conversion page is kept for the next
visit. Pick either direction at the top:

- StepMania `.sm` / `.ssc` → osu!mania beatmap packages (`.osz`).
- osu!mania `.osu` → StepMania 5 `.ssc`.

Browse to one chart file or a whole pack folder and click **Scan**. A StepMania
file can contain several difficulties; each gets its own selectable row.
Select one row, Ctrl-click several, or enable **Convert entire scanned pack**.
The pack option includes every scanned difficulty, even those hidden by search.
An SSC is preferred over a same-name companion SM so a song is not imported twice.

Select an existing output folder. For osu!, export to Downloads or another
folder, then open the .osz in osu! (for a pack, drag the exported .osz files
into the osu! window). osu! imports the packages into its own library.
For StepMania, select its Songs folder or a pack folder. If the osu! map
has a Source, the converter uses it as the pack folder name.

Title and artist stay separate in both directions. The StepMania subtitle
becomes the osu! difficulty; if blank, the StepMania difficulty label is used.
Step Artist / Credit becomes Creator, and the StepMania pack name becomes
Source. osu! tags contain the pack name and jatotrainer. When exporting to
StepMania, each distinct osu! difficulty name needs its own song entry because
StepMania stores Subtitle at song level. Rate and duplicate suffixes distinguish
exports where needed. Original charts and media are left in place. Failed
charts are logged individually.

**Rate** chooses one playback rate for the conversion, from 0.1× to 5×. At 1×
the original audio is copied. Other rates use FFmpeg with the pitch choice;
notes, holds, BPMs, offsets, pauses and previews follow the changed audio speed.
Audio is shared by difficulties when possible. Static backgrounds are copied,
with unsupported static image formats converted to PNG. Missing backgrounds
are reported. Notes before music zero on StepMania input cause matching silence
to be prepended to audio instead of being clamped or lost.

The converter preserves taps, chords, hold start/end times, lane count/order,
BPM changes, offsets, Unicode/transliterated title and artist, charter credits,
static backgrounds and preview start points. SSC per-chart timing stays
independent. StepMania stops, delays, warps and fake regions are interpreted by
the timing engine; only judged notes are turned into mania objects. Pauses and
warps are baked into absolute mania judgment times and timing resets. osu!mania
has no identical native pause/warp scrolling, so this visual difference is logged.
Preview durations, personal game calibration and player speed mods are not shared
chart settings; only the chart's preview start and native timestamp alignment are
transferred. Video/storyboard backgrounds are flattened to the static image and
reported.

Mania OD/HP can be chosen for SM imports. On StepMania export, choose the
StepMania difficulty meter; it is independent of mania OD or star difficulty.
Original OD/HP are stored in custom SSC tags for jatotrainer round trips; they do
not change StepMania's native judgment windows or health behavior.
StepMania output supports standard 4/5/6/7/8/10-lane layouts (dance single,
pump single, dance solo, kb7 single, dance double, pump double). Other lane counts
are rejected with a reason instead of dropping or merging columns.

**Strict sync**, enabled by default, checks every exported tap and hold endpoint
against StepMania's native 1/48-beat grid and rejects a difficulty if its maximum
shift would exceed 2 ms. Disabling it permits quantization, reports the measured
maximum deviation, and still rejects same-lane collisions or collapsed holds.
Mania import uses integer millisecond timestamps (at most 0.5 ms rounding).
Mania inherited SV is exported as SSC SCROLLS; display also depends on the
player's speed mod. Non-quarter time-signature barlines may differ in mania.

**Allow gameplay approximations** is off by default. When enabled, mines are
omitted, rolls become holds, lifts become taps, and animated speed ramps become
instantaneous changes; every change is logged. Zero/reverse/extreme scroll
multipliers can be omitted with this option. Keysounded audio, automatic keysounds,
attacks attached to notes, multiplayer routine/couple charts, orphaned holds,
and legacy negative-BPM simfiles are rejected rather than exported out of sync.
Normalize legacy negative BPMs to SSC warps in a StepMania editor first.

The conversion log shows output paths, individual rejections, approximations
and measured sync errors. Progress turns green when charts are produced and red
if all selected charts fail. Build again using **build.bat**; the updated requirements
and Windows build collect the new parser dependencies. Installer version is 1.4.0.

Validation includes native-engine timing comparisons, SM/SSC parsing, split timing,
stops/delays/warps/fakes, holds, rates, previews, negative-time audio padding,
real FFmpeg encoding, grid quantization/collision handling, pack grouping,
source protection, and a real-widget pack conversion. Live playback sync in both
Windows games still needs testing with your charts.
