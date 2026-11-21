#!/usr/bin/env bash
# Build a native Windows x64 executable in the MSYS2 UCRT64 environment.
set -euo pipefail
cd -- "$(dirname -- "$0")"
root="$PWD"
out="$root/build-tools"
for program in gcc make nasm pkg-config sha256sum; do
  command -v "$program" >/dev/null || { echo "Missing MSYS2 tool: $program" >&2; exit 1; }
done
[[ "$(gcc -dumpmachine)" == x86_64-w64-mingw32 ]] || { echo "Launch a Windows x64 MinGW shell." >&2; exit 1; }
(cd vendor/audio && sha256sum -c SHA256SUMS)
mkdir -p "$out"
work="$(mktemp -d /tmp/jatotrainer-audio.XXXXXXXX)"
trap 'rm -rf -- "$work"' EXIT
prefix="$work/install"
jobs="${JATO_BUILD_JOBS:-4}"
tar -xf vendor/audio/lame-3.100.tar.gz -C "$work"
tar -xf vendor/audio/ffmpeg-7.1.5.tar.xz -C "$work"
(
  cd "$work/lame-3.100"
  ./configure --prefix="$prefix" --disable-shared --enable-static --disable-frontend
  make -j"$jobs"
  make install
)
(
  cd "$work/ffmpeg-7.1.5"
  ./configure --enable-gpl --enable-version3 --disable-autodetect --disable-shared --enable-static \
    --enable-libmp3lame --disable-ffplay --disable-ffprobe --disable-doc --disable-debug --disable-network \
    --extra-cflags="-I$prefix/include" --extra-ldflags="-static -L$prefix/lib"
  make -j"$jobs" ffmpeg.exe
  ./ffmpeg.exe -hide_banner -loglevel error -y -f lavfi -i sine -t 0.1 -c:a libmp3lame "$work/smoke.mp3"
  ./ffmpeg.exe -hide_banner -loglevel error -i "$work/smoke.mp3" -f null -
  mkdir -p "$out/audio/licenses"
  cp LICENSE.md COPYING.GPLv2 COPYING.GPLv3 COPYING.LGPLv2.1 COPYING.LGPLv3 "$out/audio/licenses/"
  cp "$work/lame-3.100/COPYING" "$out/audio/licenses/LAME-LGPL.txt"
  ./ffmpeg.exe -version > "$out/audio/FFMPEG-BUILD.txt"
  cp ffmpeg.exe "$out/audio/ffmpeg.exe"
)
