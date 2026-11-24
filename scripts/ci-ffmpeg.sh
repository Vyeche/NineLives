#!/usr/bin/env bash
# ci-ffmpeg.sh — ffmpeg for the Gauntlet's Linux lanes, without apt. Ubuntu's package mirror stalled
# twice in one day (2026-11-23) and failed runs that had nothing wrong; PyPI is fast and steady on
# GitHub's runners. The static ffmpeg inside the imageio-ffmpeg wheel has what check.sh and the test
# kitty use (Opus/Vorbis decoders, ebur128, x11grab) and gives the same loudness as Ubuntu's.
#   bash scripts/ci-ffmpeg.sh            puts ffmpeg in /usr/local/bin (sudo), or $1 if given
# The wheel is pinned by SHA-256; change the version and the hash together.
set -euo pipefail
VERSION="0.5.1"
SHA256="5289f75c7f755b499653f3209fea4efd1430cba0e39831c381aad2d458f7a316"  # imageio_ffmpeg-0.5.1-py3-none-manylinux2010_x86_64.whl
BIN="imageio_ffmpeg/binaries/ffmpeg-linux64-v4.2.2"
DEST="${1:-/usr/local/bin}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
printf 'imageio-ffmpeg==%s --hash=sha256:%s\n' "$VERSION" "$SHA256" > "$work/req.txt"
python3 -m pip download --quiet --retries 5 --timeout 30 --require-hashes --no-deps \
  --only-binary=:all: --platform manylinux2010_x86_64 -r "$work/req.txt" -d "$work"
python3 - "$work" "$BIN" <<'EOF'
import glob, os, sys, zipfile
work, member = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(glob.glob(os.path.join(work, "*.whl"))[0]) as z:
    with z.open(member) as src, open(os.path.join(work, "ffmpeg"), "wb") as out:
        out.write(src.read())
EOF
chmod 755 "$work/ffmpeg"
if [ -w "$DEST" ]; then install -m 755 "$work/ffmpeg" "$DEST/ffmpeg"
else sudo install -m 755 "$work/ffmpeg" "$DEST/ffmpeg"; fi
"$DEST/ffmpeg" -hide_banner -version | head -1
