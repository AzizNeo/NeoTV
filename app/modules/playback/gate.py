"""The playback gate: providers × policies × enhancers, assembled from extension points."""

from __future__ import annotations

from collections.abc import Sequence

from app.modules.playback.api import (
    ContentCard,
    ContentDescriptor,
    ContentProvider,
    Deny,
    PlaybackContext,
    PlaybackPolicy,
    ResolvedSource,
    SourceEnhancer,
)
from app.shared_kernel.content import ContentRef
from app.shared_kernel.ratings import allowed_for_kids


class PlaybackConfigurationError(RuntimeError):
    pass


class ContentNotFoundError(LookupError):
    pass


class NoContentProviderError(LookupError):
    pass


class PlaybackDeniedError(Exception):
    def __init__(self, deny: Deny, policy: str) -> None:
        super().__init__(deny.message)
        self.code = deny.code
        self.error_code = deny.code
        self.policy = policy
        self.details = {"policy": policy, "reason": deny.code}


class KidsRatingPolicy:
    """Kids profiles may only play content the shared rating rule allows."""

    name = "kids_rating"
    order = 20

    def evaluate(self, ctx: PlaybackContext, descriptor: ContentDescriptor) -> Deny | None:
        if ctx.is_kids and not allowed_for_kids(descriptor.rating):
            return Deny("CONTENT_NOT_ALLOWED_FOR_KIDS", "This content is not available on a kids profile")
        return None


class PlaybackGate:
    def __init__(
        self,
        providers: Sequence[ContentProvider],
        policies: Sequence[PlaybackPolicy],
        enhancers: Sequence[SourceEnhancer],
    ) -> None:
        self._providers: dict[str, ContentProvider] = {}
        for provider in providers:
            if provider.namespace in self._providers:
                raise PlaybackConfigurationError(f"two content providers for namespace '{provider.namespace}'")
            self._providers[provider.namespace] = provider
        names = [p.name for p in policies]
        if len(names) != len(set(names)):
            raise PlaybackConfigurationError(f"duplicate playback policy names: {sorted(names)}")
        self._policies = sorted(policies, key=lambda p: (p.order, p.name))
        self._enhancers = list(enhancers)

    @property
    def namespaces(self) -> list[str]:
        return sorted(self._providers)

    def provider(self, namespace: str) -> ContentProvider:
        try:
            return self._providers[namespace]
        except KeyError:
            raise NoContentProviderError(
                f"no content provider for namespace '{namespace}' (is the owning module installed and enabled?)"
            ) from None

    def describe(self, ref: ContentRef) -> ContentDescriptor:
        descriptor = self.provider(ref.namespace).describe(ref.id)
        if descriptor is None:
            raise ContentNotFoundError(str(ref))
        return descriptor

    def authorize(self, ctx: PlaybackContext) -> ContentDescriptor:
        descriptor = self.describe(ctx.content)
        if ctx.window is not None and not getattr(self.provider(ctx.content.namespace), "supports_window", False):
            raise PlaybackDeniedError(Deny("CATCHUP_NOT_AVAILABLE", "This content has no catch-up"), "window")
        for policy in self._policies:
            deny = policy.evaluate(ctx, descriptor)
            if deny is not None:
                raise PlaybackDeniedError(deny, policy.name)
        return descriptor

    def resolve(self, ctx: PlaybackContext, descriptor: ContentDescriptor) -> ResolvedSource:
        source = self.provider(ctx.content.namespace).resolve(ctx, descriptor)
        for enhancer in self._enhancers:
            source = enhancer.enhance(ctx, descriptor, source)
        return source

    def cards(self, refs: list[str]) -> dict[str, ContentCard]:
        by_namespace: dict[str, list[int]] = {}
        for raw in refs:
            try:
                ref = ContentRef.parse(raw)
            except ValueError:
                continue
            by_namespace.setdefault(ref.namespace, []).append(ref.id)
        cards: dict[str, ContentCard] = {}
        for namespace, ids in by_namespace.items():
            provider = self._providers.get(namespace)
            if provider is None:  # owning module disabled → its content silently drops from lists (by design)
                continue
            for item in provider.cards(sorted(set(ids))):
                cards[item.ref] = item
        return cards


class ContentDirectoryService:
    """Capability ``playback.content`` (backed by the gate's providers)."""

    def __init__(self, gate_provider: object) -> None:
        self._gate_provider = gate_provider

    def _gate(self) -> PlaybackGate:
        return self._gate_provider()  # type: ignore[operator]

    def cards(self, refs: list[str]) -> dict[str, ContentCard]:
        return self._gate().cards(refs)

    def describe(self, ref: ContentRef) -> ContentDescriptor | None:
        try:
            return self._gate().describe(ref)
        except (ContentNotFoundError, NoContentProviderError):
            return None


def build_kids_policy(_container: object) -> KidsRatingPolicy:
    return KidsRatingPolicy()
