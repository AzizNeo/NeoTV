"""Live background jobs: ABR transcoder (queue: transcode) and EPG import."""

from __future__ import annotations

import logging
import shutil
import socket
import time
from pathlib import Path
from typing import Any

from celery import shared_task

from app.kernel.container import resolve
from app.kernel.security.egress import EgressGateway
from app.kernel.settings import Settings
from app.modules.live.orchestrator import TranscodeOrchestrator
from app.modules.live.services import EpgService
from app.modules.live.transcoding import FfmpegProcess, build_command, detect_encoder

_log = logging.getLogger("live.tasks")


def stream_dir(settings: Settings, stream_id: str) -> Path:
    root = Path(settings.hls_output_root).resolve()
    target = (root / stream_id).resolve()
    if root not in target.parents:
        raise ValueError("invalid stream id")
    return target


@shared_task(bind=True, name="live.run_transcoder", acks_late=False)
def run_transcoder(self: Any, stream_id: str, source_url: str) -> dict[str, Any]:
    """Owns one FFmpeg process for as long as its viewer lease is alive."""
    settings = resolve(Settings)
    orchestrator = resolve(TranscodeOrchestrator)
    output = stream_dir(settings, stream_id)
    shutil.rmtree(output, ignore_errors=True)
    for index in range(4):
        (output / f"stream_{index}").mkdir(parents=True, exist_ok=True)

    process: FfmpegProcess | None = None
    reason = "unknown"
    try:
        encoder = detect_encoder(tuple(settings.transcode_encoders))
        process = FfmpegProcess(
            build_command(source_url=source_url, stream_id=stream_id, output_dir=output, encoder=encoder)
        )
        orchestrator.mark_running(stream_id, worker=f"{socket.gethostname()}:{self.request.hostname}", pid=process.pid)
        _log.info("transcode.started stream=%s pid=%s encoder=%s", stream_id, process.pid, encoder)
        while True:
            time.sleep(1.0)
            code = process.poll()
            if code is not None:
                reason = f"exited:{code}"
                break
            if orchestrator.should_stop(stream_id):
                reason = "idle_or_stopped"
                break
    except Exception as exc:
        reason = f"error:{type(exc).__name__}"
        _log.exception("transcode.failed stream=%s", stream_id)
    finally:
        tail = list(process.tail)[-20:] if process else []
        if process is not None:
            process.stop()
        orchestrator.clear(stream_id)
        shutil.rmtree(output, ignore_errors=True)
        _log.info("transcode.stopped stream=%s reason=%s", stream_id, reason)
    return {"stream_id": stream_id, "reason": reason, "stderr_tail": tail}


@shared_task(name="live.import_epg", ignore_result=True)
def import_epg() -> dict[str, int] | None:
    settings = resolve(Settings)
    if not settings.epg_xmltv_url:
        return None
    return resolve(EpgService).import_xmltv(resolve(EgressGateway), settings.epg_xmltv_url)


@shared_task(name="live.import_epg_from", bind=True)
def import_epg_from(self: Any, url: str) -> dict[str, int]:
    self.update_state(state="PROGRESS", meta={"progress": 10, "message": "downloading XMLTV"})
    return resolve(EpgService).import_xmltv(resolve(EgressGateway), url)
