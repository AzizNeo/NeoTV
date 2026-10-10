"""Catalog's contribution to the playback extension point ``playback.content_providers``."""

from __future__ import annotations

from typing import Any

from app.kernel.capabilities import CapabilityIndex
from app.kernel.uow import UnitOfWorkFactory
from app.modules.catalog.api import NAMESPACE
from app.modules.catalog.services import ChannelRepository
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

_VOD_EXT = (".mp4", ".m4v", ".mov", ".webm", ".mkv")


def mime_for(url: str, kind: str) -> str:
    path = url.lower().split("?", 1)[0]
    if ".m3u8" in path or path.endswith(".m3u"):
        return "application/vnd.apple.mpegurl"
    if path.endswith(_VOD_EXT):
        return "video/mp4"
    return "video/mp2t" if kind == ContentKind.LIVE else "video/mp4"


class CatalogContentProvider:
    namespace = NAMESPACE

    def __init__(self, uow: UnitOfWorkFactory, urls: StreamUrlFactory) -> None:
        self._uow = uow
        self._urls = urls

    def describe(self, content_id: int) -> ContentDescriptor | None:
        with self._uow() as uow:
            channel = ChannelRepository(uow.session).active(content_id)
            if channel is None:
                return None
            return ContentDescriptor(
                ref=ContentRef(NAMESPACE, channel.id),
                title=channel.name,
                kind=ContentKind(channel.kind),
                rating=Rating(channel.rating),
                group=channel.group_name,
            )

    def cards(self, content_ids: list[int]) -> list[ContentCard]:
        with self._uow() as uow:
            return [
                ContentCard(
                    ref=f"{NAMESPACE}:{c.id}",
                    title=c.name,
                    image=c.logo_url,
                    group=c.group_name,
                    kind=ContentKind(c.kind),
                    rating=Rating(c.rating),
                )
                for c in ChannelRepository(uow.session).by_ids(content_ids)
            ]

    def resolve(self, ctx: PlaybackContext, descriptor: ContentDescriptor) -> ResolvedSource:
        with self._uow() as uow:
            channel = ChannelRepository(uow.session).active(descriptor.ref.id)
            if channel is None:
                raise LookupError(str(descriptor.ref))
            upstream, delivery, kind = channel.stream_url, channel.delivery, channel.kind
        manifest = upstream if delivery == "direct" else self._urls.proxied(upstream, ctx)
        return ResolvedSource(
            manifest_url=manifest, is_live=kind == ContentKind.LIVE, mime_type=mime_for(upstream, kind)
        )


def build_provider(container: Any) -> CatalogContentProvider:
    return CatalogContentProvider(
        container.resolve(UnitOfWorkFactory), container.resolve(CapabilityIndex).required("playback.urls")
    )
