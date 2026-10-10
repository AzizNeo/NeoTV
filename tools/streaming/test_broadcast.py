"""Publish a test stream to the RTMP ingest (replaces Scripts/streaming/broadcast*.py).

    python -m tools.streaming.test_broadcast --key <ingest key>                 # SMPTE bars + tone
    python -m tools.streaming.test_broadcast --key <key> --file movie.mp4        # loop a local file
    python -m tools.streaming.test_broadcast --key <key> --server rtmp://host:1935/live

The ingest key is the one shown once by the admin panel / ``tools.seed_demo --ingest``.
The RTMP server (deploy/rtmp/nginx.conf) asks the API to verify it, then the
transcoder worker produces the HLS ladder that viewers play.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


def build_command(ffmpeg: str, server: str, key: str, file: str | None) -> list[str]:
    target = f"{server.rstrip('/')}/{key}"
    if file:
        source = ["-re", "-stream_loop", "-1", "-i", file]
    else:
        source = [
            "-re",
            "-f",
            "lavfi",
            "-i",
            "smptehdbars=size=1280x720:rate=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000",
        ]
    encode = [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-g",
        "50",
        "-b:v",
        "2500k",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
    ]
    return [ffmpeg, "-hide_banner", "-loglevel", "warning", *source, *encode, "-f", "flv", target]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--key", required=True, help="channel ingest key")
    parser.add_argument("--server", default="rtmp://127.0.0.1:1935/live")
    parser.add_argument("--file", help="loop this media file instead of test bars")
    args = parser.parse_args(argv)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print("ffmpeg not found on PATH")
        return 2
    command = build_command(ffmpeg, args.server, args.key, args.file)
    print("publishing →", f"{args.server.rstrip('/')}/<key hidden>", "(Ctrl+C to stop)")
    try:
        return subprocess.call(command)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
