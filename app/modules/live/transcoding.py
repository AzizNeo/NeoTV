"""ABR transcoding: ladder, encoder detection, FFmpeg command, process wrapper.

Platform-neutral (STR-03): process groups via ``start_new_session`` on POSIX
and ``CREATE_NEW_PROCESS_GROUP`` on Windows; output root from Settings;
encoder chosen from what the local FFmpeg actually supports; every process
is tagged (``-metadata neotv_stream=<id>``) so reapers only ever touch our
own processes. stderr is drained continuously (STR-01: no pipe deadlock).
"""

from __future__ import annotations

import collections
import functools
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger("live.transcoding")

SEGMENT_SECONDS = 2
PLAYLIST_SIZE = 6


class EncoderUnavailableError(RuntimeError):
    pass


class FfmpegNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Rung:
    name: str
    width: int
    height: int
    video_kbps: int
    audio_kbps: int

    @property
    def bandwidth(self) -> int:
        return int((self.video_kbps + self.audio_kbps) * 1000 * 1.1)


LADDER: tuple[Rung, ...] = (
    Rung("1080p", 1920, 1080, 5000, 192),
    Rung("720p", 1280, 720, 2800, 128),
    Rung("480p", 854, 480, 1400, 128),
    Rung("360p", 640, 360, 800, 96),
)

_PRESETS: dict[str, list[str]] = {
    "h264_nvenc": ["-preset", "p4", "-tune", "ll", "-rc", "cbr"],
    "h264_qsv": ["-preset", "veryfast"],
    "h264_videotoolbox": ["-realtime", "1"],
    "libx264": ["-preset", "veryfast", "-tune", "zerolatency"],
}


def ffmpeg_binary() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise FfmpegNotFoundError("ffmpeg executable not found on PATH")
    return found


@functools.lru_cache(maxsize=4)
def detect_encoder(preferred: tuple[str, ...]) -> str:
    output = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [ffmpeg_binary(), "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=15, check=False
    ).stdout
    for encoder in preferred:
        if f" {encoder} " in output and encoder in _PRESETS:
            return encoder
    raise EncoderUnavailableError(f"none of the preferred encoders are available: {list(preferred)}")


def master_playlist(ladder: tuple[Rung, ...] = LADDER) -> str:
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS"]
    for index, rung in enumerate(ladder):
        lines.append(
            f"#EXT-X-STREAM-INF:BANDWIDTH={rung.bandwidth},RESOLUTION={rung.width}x{rung.height},"
            f'CODECS="avc1.640028,mp4a.40.2",NAME="{rung.name}"'
        )
        lines.append(f"stream_{index}.m3u8")
    return "\n".join(lines) + "\n"


def build_command(
    *,
    source_url: str,
    stream_id: str,
    output_dir: Path,
    encoder: str,
    fps: int = 25,
    ladder: tuple[Rung, ...] = LADDER,
    ffmpeg: str | None = None,
) -> list[str]:
    """argv for one transcoder process. ``ffmpeg`` defaults to the binary on PATH
    (FfmpegNotFoundError if absent); pass it explicitly to build argv without one."""
    keyint = max(1, fps * SEGMENT_SECONDS)
    splits = "".join(f"[v{i}]" for i in range(len(ladder)))
    scales = "; ".join(
        f"[v{i}]scale=w={r.width}:h={r.height}:force_original_aspect_ratio=decrease,pad={r.width}:{r.height}:(ow-iw)/2:(oh-ih)/2[v{i}o]"
        for i, r in enumerate(ladder)
    )
    cmd = [
        ffmpeg or ffmpeg_binary(),
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "warning",
        "-y",
        "-rw_timeout",
        "15000000",
        "-i",
        source_url,
        "-filter_complex",
        f"[0:v]split={len(ladder)}{splits}; {scales}",
    ]
    stream_map = []
    for index, rung in enumerate(ladder):
        cmd += [
            "-map",
            f"[v{index}o]",
            f"-c:v:{index}",
            encoder,
            *_PRESETS[encoder],
            f"-b:v:{index}",
            f"{rung.video_kbps}k",
            f"-maxrate:v:{index}",
            f"{int(rung.video_kbps * 1.07)}k",
            f"-bufsize:v:{index}",
            f"{rung.video_kbps * 2}k",
            "-g",
            str(keyint),
            "-keyint_min",
            str(keyint),
            "-sc_threshold",
            "0",
            "-map",
            "0:a:0?",
            f"-c:a:{index}",
            "aac",
            f"-b:a:{index}",
            f"{rung.audio_kbps}k",
            "-ac",
            "2",
        ]
        stream_map.append(f"v:{index},a:{index}")
    cmd += [
        "-metadata",
        f"neotv_stream={stream_id}",
        "-f",
        "hls",
        "-hls_time",
        str(SEGMENT_SECONDS),
        "-hls_list_size",
        str(PLAYLIST_SIZE),
        "-hls_flags",
        "independent_segments+delete_segments+temp_file",
        "-hls_segment_type",
        "mpegts",
        "-hls_segment_filename",
        str(output_dir / "stream_%v" / "data%06d.ts"),
        "-var_stream_map",
        " ".join(stream_map),
        str(output_dir / "stream_%v.m3u8"),
    ]
    return cmd


class FfmpegProcess:
    """Owns one FFmpeg process group; drains stderr into a bounded ring buffer."""

    def __init__(self, argv: list[str], *, env: dict[str, str] | None = None) -> None:
        kwargs: dict[str, object] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.PIPE,
            "bufsize": 0,
        }
        if env is not None:
            kwargs["env"] = {**os.environ, **env}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True
        self.process = subprocess.Popen(argv, **kwargs)  # type: ignore[call-overload]  # noqa: S603
        self.tail: collections.deque[str] = collections.deque(maxlen=200)
        self._drain_thread = threading.Thread(target=self._drain, name=f"ffmpeg-stderr-{self.process.pid}", daemon=True)
        self._drain_thread.start()

    @property
    def pid(self) -> int:
        return self.process.pid

    def _drain(self) -> None:
        stream = self.process.stderr
        if stream is None:
            return
        for raw in iter(stream.readline, b""):
            self.tail.append(raw.decode("utf-8", "replace").rstrip())
        stream.close()

    def poll(self) -> int | None:
        return self.process.poll()

    def stop(self, timeout: float = 8.0) -> int:
        if self.process.poll() is None:
            try:
                if sys.platform.startswith("win"):
                    self.process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
                else:
                    os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=timeout)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=5)
        self._drain_thread.join(timeout=2)
        return int(self.process.returncode or 0)
