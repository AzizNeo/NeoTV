"""``flask live ...`` commands."""

from __future__ import annotations

import os
import signal
import socket
import time
from pathlib import Path
from types import FrameType

import click
from flask.cli import AppGroup

from app.kernel.container import resolve
from app.kernel.security.egress import EgressGateway

live_cli = AppGroup("live", help="Live TV operations.")

#: Touched every pass: the container health check reads its age (no HTTP in this process).
ALIVE_FILE = Path(os.environ.get("RECORDER_ALIVE_FILE", "/tmp/neotv-recorder.alive"))  # noqa: S108
TICK_S = 5.0


@live_cli.command("record")
@click.option("--once", is_flag=True, help="One supervision pass, then exit (diagnostics).")
def record(once: bool) -> None:
    """Run the catch-up recorder (ADR-0012) until SIGTERM / SIGINT."""
    from app.modules.live.archive import ArchiveDiskGuard, ArchiveStorage
    from app.modules.live.recorder import Recorder, RecorderLease
    from app.modules.live.services import ArchiveService
    from app.modules.live.transcoding import FfmpegProcess, ffmpeg_binary

    owner = f"{socket.gethostname()}:{os.getpid()}"
    recorder = Recorder(
        sources=resolve(ArchiveService),
        storage=resolve(ArchiveStorage),
        guard=resolve(ArchiveDiskGuard),
        lease=RecorderLease(resolve("kernel.redis"), owner),
        spawn=lambda argv: FfmpegProcess(argv, env={"TZ": "UTC"}),  # segment names are UTC
        ffmpeg=ffmpeg_binary(),
        check_source=resolve(EgressGateway).check,
    )
    stopping = False

    def _stop(signum: int, frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    click.echo(f"recorder {owner} started")
    try:
        while not stopping:
            recorder.tick()
            ALIVE_FILE.touch()
            if once:
                break
            time.sleep(TICK_S)
    finally:
        recorder.stop_all()
        click.echo(f"recorder {owner} stopped")
