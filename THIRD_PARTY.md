The combined Jatotrainer build is distributed under GNU GPLv3 or later; see
LICENSE. Earlier MIT grants are preserved in JATOTRAINER-MIT-NOTICE.txt.

The bundled Windows osu!stable reader uses Piotrekol's ProcessMemoryDataFinder
and OsuMemoryDataProvider, GPL-3.0-or-later. Unmodified library source and its
original license are in vendor/piotrekol. The adapter is in native/.
Upstream: https://github.com/Piotrekol/ProcessMemoryDataFinder
Pinned commit: 37f67c010dc51ecab8e550ab6325d6899272bc2c

StepMania conversion uses simfile 2.1.1 and its timing/note-data engine:
https://github.com/garcia/simfile
https://docs.simfile.dev/en/main/timing-note-data.html
Its MIT license and dependency licenses are bundled in assets/licenses.
Requirements pin simfile and setuptools (<81), because PyFilesystem2's fs
package still imports pkg_resources. The Windows build collects simfile,
msdparser, fs and pkg_resources and their resources.

Native timing/default and grid behavior was checked against StepMania's source:
https://github.com/stepmania/stepmania/blob/master/src/TimingData.cpp
https://github.com/stepmania/stepmania/blob/master/src/NotesLoaderSSC.cpp
https://github.com/stepmania/stepmania/blob/master/src/NoteDataUtil.cpp
Reference revision: 825467bcd81c812b33ad684dc04dd151b2d5dec3
osu! chart syntax reference:
https://osu.ppy.sh/wiki/en/Client/File_formats/osu_(file_format)

The bundled FFmpeg 7.1.5 executable is compiled with --enable-gpl and
--enable-version3, as a GPLv3-or-later build. It includes the LAME 3.100 MP3
encoder (LGPL). Exact source archives and checksums are in vendor/audio.
build_ffmpeg.sh contains the build configuration; the installer includes
the build configuration report and upstream license texts.
https://ffmpeg.org/releases/ffmpeg-7.1.5.tar.xz
https://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz
