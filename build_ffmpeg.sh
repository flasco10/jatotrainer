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
  # Only what Jatotrainer uses: read song audio, change speed/pitch, pad, and write MP3/WAV.
  # A full build is ~40x bigger. Add a component here if a song format stops decoding.
  ./configure --enable-gpl --enable-version3 --disable-autodetect --disable-shared --enable-static \
    --disable-everything --enable-libmp3lame \
    --disable-ffplay --disable-ffprobe --disable-doc --disable-debug --disable-network \
    --disable-swscale --disable-postproc \
    --enable-protocol=file,pipe \
    --enable-demuxer=mp3,ogg,wav,flac,aiff,mov,aac,s16le \
    --enable-decoder=mp3,mp3float,mp2,mp2float,vorbis,opus,flac,aac,alac \
    --enable-decoder=pcm_s16le,pcm_s16be,pcm_s24le,pcm_s24be,pcm_s32le,pcm_f32le,pcm_f64le,pcm_u8,pcm_alaw,pcm_mulaw \
    --enable-decoder=adpcm_ms,adpcm_ima_wav \
    --enable-parser=mpegaudio,vorbis,opus,flac,aac \
    --enable-encoder=libmp3lame,pcm_s16le \
    --enable-muxer=mp3,wav,s16le,null \
    --enable-filter=aresample,asetrate,atempo,adelay,aformat,anull,sine \
    --enable-indev=lavfi \
    --extra-cflags="-I$prefix/include" --extra-ldflags="-static -L$prefix/lib"
  make -j"$jobs" ffmpeg.exe
  # Smoke-test every path the app takes, so a missing component fails the build, not a user.
  q=(-hide_banner -loglevel error -y)
  ./ffmpeg.exe "${q[@]}" -f lavfi -i sine=frequency=1000:duration=1 -c:a pcm_s16le "$work/smoke.wav"
  ./ffmpeg.exe "${q[@]}" -i "$work/smoke.wav" -filter:a "aresample=44100,asetrate=44100*1.25,aresample=44100" \
    -c:a libmp3lame -b:a 192k -ar 44100 -write_xing 1 -f mp3 "$work/pitch.mp3"
  ./ffmpeg.exe "${q[@]}" -i "$work/pitch.mp3" -map 0:a:0 -vn -filter:a "atempo=2.0,atempo=1.1" \
    -ac 2 -ar 44100 -c:a pcm_s16le -f wav "$work/tempo.wav"
  ./ffmpeg.exe "${q[@]}" -i "$work/tempo.wav" -af "adelay=250:all=1" -c:a pcm_s16le "$work/pad.wav"
  ./ffmpeg.exe "${q[@]}" -i "$work/pad.wav" -f s16le -ar 44100 -ac 2 - > "$work/raw.pcm"
  # Pack maker reads the bitrate from this banner; "-i" alone always exits nonzero.
  { ./ffmpeg.exe -hide_banner -i "$work/pitch.mp3" 2>&1 || true; } | grep -Eq "bitrate: [0-9]+ kb/s"
  ./ffmpeg.exe "${q[@]}" -i "$work/pad.wav" -f null -
  [[ -s "$work/raw.pcm" ]] || { echo "FFmpeg smoke test produced no audio" >&2; exit 1; }
  ls -l ffmpeg.exe
  mkdir -p "$out/audio/licenses"
  cp LICENSE.md COPYING.GPLv2 COPYING.GPLv3 COPYING.LGPLv2.1 COPYING.LGPLv3 "$out/audio/licenses/"
  cp "$work/lame-3.100/COPYING" "$out/audio/licenses/LAME-LGPL.txt"
  ./ffmpeg.exe -version > "$out/audio/FFMPEG-BUILD.txt"
  cp ffmpeg.exe "$out/audio/ffmpeg.exe"
)
