from __future__ import annotations

from datetime import datetime
from typing import Any

from app.kernel.manifest import ExtensionSpec, ModuleManifest, RouteSpec
from app.kernel.settings import Settings
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.live.api import LiveListing, LiveReader, LiveStats, ProgramListing
from app.modules.live.provider import LiveOfflineError, TranscoderUnavailableError
from app.modules.live.services import (
    EpgImportError,
    InvalidIngestKeyError,
    LiveChannelNotFoundError,
    LiveSourceConfigError,
)
from app.modules.live.transcoding import EncoderUnavailableError, FfmpegNotFoundError


class _LiveReader:
    def __init__(self, c: Any) -> None:
        self._c = c

    def stats(self) -> LiveStats:
        from app.modules.live.orchestrator import TranscodeOrchestrator
        from app.modules.live.services import LiveChannelService

        return self._c.resolve(LiveChannelService).stats(self._c.resolve(TranscodeOrchestrator).running_count())

    def listing(self, *, kids_only: bool) -> list[LiveListing]:
        from app.modules.live.services import LiveChannelService

        return self._c.resolve(LiveChannelService).listing(kids_only=kids_only)

    def programmes(self, *, channel_ids: list[int], start: datetime, end: datetime) -> list[ProgramListing]:
        from app.modules.live.services import EpgService

        if not channel_ids:  # the guide service reads "no filter" as every channel
            return []
        return [
            ProgramListing(
                id=p.id,
                channel_id=p.channel_id,
                title=p.title,
                description=p.description,
                starts_at=p.starts_at,
                ends_at=p.ends_at,
            )
            for p in self._c.resolve(EpgService).guide(start=start, end=end, channel_ids=channel_ids)
        ]


def _services(c: Any) -> None:
    from app.modules.live.orchestrator import TranscodeOrchestrator
    from app.modules.live.services import EpgService, IngestKeyService, LiveChannelService

    settings = c.resolve(Settings)
    c.register(IngestKeyService, lambda _c: IngestKeyService(settings.derive_key("live-ingest-keys")))
    c.register(
        LiveChannelService,
        lambda c: LiveChannelService(c.resolve(UnitOfWorkFactory), c.resolve(IngestKeyService), c.resolve(Clock)),
    )
    c.register(EpgService, lambda c: EpgService(c.resolve(UnitOfWorkFactory), c.resolve(Clock)))
    c.register(
        TranscodeOrchestrator,
        lambda c: TranscodeOrchestrator(c.resolve("kernel.redis"), idle_grace_s=settings.transcode_idle_grace_s),
    )
    c.register(LiveReader, lambda c: _LiveReader(c))


manifest = ModuleManifest(
    name="live",
    version="2.0.0",
    description="Live channels (external HLS or RTMP ingest + ABR transcoding) and the programme guide.",
    provides={"live.read": LiveReader},
    requires=frozenset({"identity.authentication", "profile.context", "playback.urls", "playback.grants"}),
    models=("app.modules.live.models",),
    services=_services,
    routes=(RouteSpec("app.modules.live.http:blueprint", "/api/v1/live"),),
    task_modules=("app.modules.live.tasks",),
    task_routes={"live.run_transcoder": {"queue": "transcode"}, "live.import_epg*": {"queue": "epg"}},
    beat_schedule={"live.import-epg": {"task": "live.import_epg", "schedule": 6 * 3600.0}},
    permissions=("live:write",),
    extensions=(ExtensionSpec("playback.content_providers", "app.modules.live.provider:build_provider"),),
    error_map={
        LiveChannelNotFoundError: (404, "LIVE_CHANNEL_NOT_FOUND"),
        InvalidIngestKeyError: (403, "INVALID_INGEST_KEY"),
        LiveSourceConfigError: (422, "LIVE_SOURCE_INVALID"),
        EpgImportError: (502, "EPG_IMPORT_FAILED"),
        LiveOfflineError: (409, "LIVE_OFFLINE"),
        TranscoderUnavailableError: (503, "TRANSCODER_UNAVAILABLE"),
        EncoderUnavailableError: (503, "ENCODER_UNAVAILABLE"),
        FfmpegNotFoundError: (503, "FFMPEG_NOT_FOUND"),
    },
)
