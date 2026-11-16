#!/bin/sh
# Shows a Cardputer Zero's screen in a window on this computer (view only).
# Usage: tools/screen-view.sh [user@host]
# Needs ssh access to the device and ffplay (part of ffmpeg) on this computer.
set -eu
HOST=${1:-soliton@10.0.0.49}

# The screen is 320x170 in RGB565; read it about five times a second.
# The device file is padded past the visible pixels, so take exactly one frame.
ssh "$HOST" 'while head -c 108800 /dev/fb0; do sleep 0.2; done' |
    ffplay -loglevel error -window_title "Cardputer Zero" \
        -f rawvideo -pixel_format rgb565le -video_size 320x170 -framerate 5 \
        -vf scale=960:510:flags=neighbor -
