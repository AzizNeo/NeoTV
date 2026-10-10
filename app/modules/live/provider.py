"""Live module's content provider for the playback gate (namespace ``live``)."""

from __future__ import annotations

from typing import Any

from app.kernel.capabilities import CapabilityIndex
from app.kernel.settings import Settings
from app.modules.live.api import NAMESPACE
from app.modules.live.orchestrator import TranscodeOrchestrator
from app.modules.live.services import LiveChannelService
from app.modules.playback.api import (
    ContentCard,
    ContentDescriptor,
    ContentKind,
    PlaybackContext,
    Rating,
    ResolvedSource,
    StreamUrlFactory,
)
from app.shared_kernel.content import ContentRef

HLS_PREFIX = "/api/v1/live/hls/"


class LiveOfflineError(Exception):
    pass


class TranscoderUnavailableError(Exception):
    pass


def hls_dir(playback_id: str) -> str:
    return f"{HLS_PREFIX}{playback_id}/"


class LiveContentProvider:
    namespace = NAMESPACE

    def __init__(
        self,
        channels: LiveChannelService,
        urls: StreamUrlFactory,
        orchestrator: TranscodeOrchestrator,
        settings: Settings,
    ) -> None:
        self._channels = channels
        self._urls = urls
        self._orchestrator = orchestrator
        self._settings = settings

    def describe(self, content_id: int) -> ContentDescriptor | None:
        channel = self._channels.get_active(content_id)
        if channel is None:
            return None
        return ContentDescriptor(
            ref=ContentRef(NAMESPACE, channel.id),
            title=channel.name,
            kind=ContentKind.LIVE,
            rating=Rating(channel.rating),
            group="Live",
        )

    def cards(self, content_ids: list[int]) -> list[ContentCard]:
        cards = []
        for channel in self._channels.list_public(kids_only=False):
            if channel.id in content_ids:
                cards.append(
                    ContentCard(
                        ref=channel.ref,
                        title=channel.name,
                        image=channel.logo,
                        group="Live",
                        kind=ContentKind.LIVE,
                        rating=Rating(channel.rating),
                    )
                )
        return cards

    def resolve(self, ctx: PlaybackContext, descriptor: ContentDescriptor) -> ResolvedSource:
        channel = self._channels.get_active(descriptor.ref.id)
        if channel is None:
            raise LookupError(str(descriptor.ref))
        if channel.source_type == "external":
            assert channel.upstream_url is not None
            url = (
                channel.upstream_url if channel.delivery == "direct" else self._urls.proxied(channel.upstream_url, ctx)
            )
            return ResolvedSource(manifest_url=url, is_live=True)
        if not channel.is_live:
            raise LiveOfflineError("This channel is not broadcasting right now")
        if self._settings.celery_always_eager:
            raise TranscoderUnavailableError("Transcoding needs a Celery worker (CELERY_ALWAYS_EAGER is on)")
        from app.modules.live.tasks import run_transcoder

        self._orchestrator.ensure_running(
            channel.playback_id,
            f"{self._settings.rtmp_internal_base.rstrip('/')}/{channel.playback_id}",
            dispatch=lambda stream_id, source: run_transcoder.apply_async(args=(stream_id, source), queue="transcode"),
        )
        return ResolvedSource(
            manifest_url=self._urls.signed_entry(hls_dir(channel.playback_id), "master.m3u8", ctx), is_live=True
        )


def build_provider(container: Any) -> LiveContentProvider:
    return LiveContentProvider(
        container.resolve(LiveChannelService),
        container.resolve(CapabilityIndex).required("playback.urls"),
        container.resolve(TranscodeOrchestrator),
        container.resolve(Settings),
    )
