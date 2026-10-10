"""Admin application services.

The admin module never touches another module's tables: every number and
action goes through a published capability. Optional capabilities degrade
gracefully — a disabled module's dashboard section is ``None``, not an error.
"""

from __future__ import annotations

import hashlib
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from app.kernel.db import dialect_insert
from app.kernel.resilience.best_effort import best_effort
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.admin.api import AbuseFinding, AbuseRule
from app.modules.admin.models import AbuseFlag, LoginSignal
from app.modules.identity.api import IdentityAdmin, UserSummary
from app.modules.playback.api import ActiveSessionView, SessionDirectory
from app.shared_kernel.events import UserLoggedIn

SIGNAL_RETENTION = timedelta(days=7)


class AbuseFlagNotFoundError(LookupError):
    pass


class SessionNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class AdminUserRow:
    id: int
    username: str
    email: str | None
    role: str
    is_active: bool
    plan: str | None
    active_sessions: int
    created_at: datetime
    last_login_at: datetime | None


@dataclass(frozen=True, slots=True)
class AdminUserPage:
    items: list[AdminUserRow]
    next_cursor: int | None


@dataclass(frozen=True, slots=True)
class FlagView:
    id: int
    user_id: int
    kind: str
    score: int
    details: str
    status: str
    first_seen_at: datetime
    last_seen_at: datetime


def device_hash(client_device_id: str | None, user_agent: str) -> str:
    raw = f"id:{client_device_id}" if client_device_id else f"ua:{user_agent}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class AdminService:
    def __init__(
        self,
        *,
        identity: IdentityAdmin,
        sessions: SessionDirectory,
        capabilities: Any,
        clock: Clock,
    ) -> None:
        self._identity = identity
        self._sessions = sessions
        self._capabilities = capabilities
        self._clock = clock

    def dashboard(self) -> dict[str, Any]:
        """Each section is computed independently (best effort): one failing or
        absent module never blanks the whole dashboard."""

        def section(capability: str, fn: Callable[[Any], Any]) -> Any:
            provider = self._capabilities.optional(capability)
            if provider is None:
                return None
            value = best_effort(lambda: fn(provider), op=f"admin.dashboard.{capability}")
            if is_dataclass(value) and not isinstance(value, type):
                return asdict(value)
            return value

        return {
            "users": asdict(self._identity.counts()),
            "sessions": {"active_now": best_effort(self._sessions.active_count, op="admin.sessions", default=0)},
            "catalog": section("catalog.read", lambda p: p.stats()),
            "live": section("live.read", lambda p: p.stats()),
            "devices": section("devices.stats", lambda p: {"active": p.active_devices()}),
            "plans": section("billing.reports", lambda p: p.plan_distribution()),
            "drm": section("drm.stats", lambda p: p.stats()),
            "generated_at": self._clock.now().isoformat(),
        }

    def users(self, *, cursor: int | None, limit: int, search: str | None) -> AdminUserPage:
        page = self._identity.list_users(cursor=cursor, limit=limit, search=search)
        ids = [u.id for u in page.items]
        reports = self._capabilities.optional("billing.reports")
        plans: dict[int, str] = {}
        if reports is not None:
            plans = best_effort(lambda: reports.effective_plans(ids), op="admin.users.plans") or {}
        active: list[ActiveSessionView] = (
            best_effort(lambda: self._sessions.list_active(1000), op="admin.users.sessions") or []
        )
        live = Counter(s.user_id for s in active)
        return AdminUserPage(
            items=[self._row(u, plans.get(u.id), live.get(u.id, 0)) for u in page.items],
            next_cursor=page.next_cursor,
        )

    def set_active(self, *, user_id: int, active: bool, actor_id: int) -> AdminUserRow:
        """Suspension is an identity fact; its consequences (tokens, streams,
        licenses) propagate through ``identity.user_status_changed``."""
        user = self._identity.set_active(user_id=user_id, active=active, actor_id=actor_id)
        return self._row(user, None, 0)

    def live_sessions(self, limit: int) -> list[ActiveSessionView]:
        return self._sessions.list_active(limit)

    def terminate_session(self, token: str) -> None:
        if not self._sessions.terminate(token):
            raise SessionNotFoundError("session not found or already ended")

    @staticmethod
    def _row(user: UserSummary, plan: str | None, active_sessions: int) -> AdminUserRow:
        return AdminUserRow(
            id=user.id,
            username=user.username,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
            plan=plan,
            active_sessions=active_sessions,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )


class AbuseService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock, rules_factory: Callable[[], list[AbuseRule]]) -> None:
        self._uow = uow
        self._clock = clock
        self._rules_factory = rules_factory
        self._rules: list[AbuseRule] | None = None
        self._lock = threading.Lock()

    # write side -------------------------------------------------------------
    @staticmethod
    def record_login(session: Any, event: UserLoggedIn) -> None:
        session.add(
            LoginSignal(
                user_id=event.user_id,
                ip=event.ip[:45],
                device_hash=device_hash(event.client_device_id, event.user_agent),
                occurred_at=datetime.fromisoformat(event.occurred_at),
            )
        )

    def evaluate(self) -> int:
        """Run every rule; one failing rule is logged and skipped (best effort)."""
        now = self._clock.now()
        findings: list[AbuseFinding] = []
        for rule in self._all_rules():

            def run(rule: AbuseRule = rule) -> list[AbuseFinding]:
                return rule.evaluate(now)

            findings.extend(best_effort(run, op=f"admin.abuse.{rule.name}") or [])
        with self._uow() as uow:
            for f in findings:
                updated = uow.session.execute(
                    AbuseFlag.__table__.update()
                    .where(AbuseFlag.user_id == f.user_id, AbuseFlag.kind == f.kind, AbuseFlag.status == "open")
                    .values(score=f.score, details=f.details[:500], last_seen_at=now)
                ).rowcount
                if not updated:
                    uow.session.execute(
                        dialect_insert(uow.session, AbuseFlag.__table__).values(
                            user_id=f.user_id,
                            kind=f.kind[:40],
                            score=f.score,
                            details=f.details[:500],
                            status="open",
                            first_seen_at=now,
                            last_seen_at=now,
                        )
                    )
            uow.session.execute(delete(LoginSignal).where(LoginSignal.occurred_at < now - SIGNAL_RETENTION))
        return len(findings)

    # read / review ----------------------------------------------------------
    def flags(self, *, status: str, limit: int) -> list[FlagView]:
        with self._uow() as uow:
            rows = uow.session.execute(
                select(AbuseFlag)
                .where(AbuseFlag.status == status)
                .order_by(AbuseFlag.last_seen_at.desc(), AbuseFlag.score.desc())
                .limit(limit)
            ).scalars()
            return [self._view(r) for r in rows]

    def resolve(self, flag_id: int, *, outcome: str, actor_id: int) -> FlagView:
        with self._uow() as uow:
            row = uow.session.get(AbuseFlag, flag_id)
            if row is None:
                raise AbuseFlagNotFoundError("abuse flag not found")
            if row.status == "open":
                row.status = outcome
                row.resolved_by = actor_id
                row.resolved_at = self._clock.now()
            return self._view(row)

    def _all_rules(self) -> list[AbuseRule]:
        if self._rules is None:
            with self._lock:
                if self._rules is None:
                    rules = self._rules_factory()
                    names = [r.name for r in rules]
                    if len(names) != len(set(names)):
                        raise RuntimeError(f"duplicate abuse rule names: {sorted(names)}")
                    self._rules = rules
        return self._rules

    @staticmethod
    def _view(r: AbuseFlag) -> FlagView:
        return FlagView(r.id, r.user_id, r.kind, r.score, r.details, r.status, r.first_seen_at, r.last_seen_at)
