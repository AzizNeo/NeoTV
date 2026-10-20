"""xtream HTTP adapter, owner side: /api/v1/xtream — the account's app credentials for TV apps.

The Xtream-compatible routes TV apps call (``player_api.php``, ``xmltv.php``, stream URLs) are added
next to this file in later steps; this blueprint is the signed-in owner's management API.
"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint
from pydantic import BaseModel, ConfigDict, Field

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.profile_context import current_profile
from app.kernel.http.responses import no_content
from app.kernel.resilience.rate_limit import Rate
from app.kernel.security.auth import current_user
from app.modules.xtream.domain import LABEL_MAX
from app.modules.xtream.services import CredentialService

blueprint = Blueprint("xtream", __name__)
# Issuing is rare (one per TV); a tight limit keeps a stolen session from minting credentials in bulk.
_ISSUE_RATE = Rate("xtream.credentials.issue", rps=0.1, burst=5)
_KIDS = "XTREAM_KIDS_PROFILE"


class CredentialOut(BaseModel):
    id: int
    label: str
    username: str
    profile_id: int
    profile_name: str | None = Field(description="null when the profile was deleted (the credential no longer works)")
    created_at: datetime
    last_used_at: datetime | None


class IssueIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=LABEL_MAX, description="Where it is used, e.g. 'Living-room TV'")
    profile_id: int = Field(ge=1, description="The profile the TV app watches as (its rating limits apply)")


class IssuedOut(BaseModel):
    credential: CredentialOut
    server_url: str = Field(description="What the TV app calls the server / portal URL")
    password: str = Field(description="Shown once: only a keyed digest is stored")


@blueprint.get("/credentials")
@endpoint(
    summary="App credentials of the account (never their passwords)",
    profile=True,
    response=list[CredentialOut],
    errors=(_KIDS,),
)
def list_credentials() -> object:
    return resolve(CredentialService).list(user_id=current_user.id, context=current_profile())


@blueprint.post("/credentials")
@endpoint(
    summary="Create an app credential for a TV app; the password is in this answer only",
    profile=True,
    body=IssueIn,
    response=IssuedOut,
    status=201,
    rate=_ISSUE_RATE,
    errors=(_KIDS, "XTREAM_PROFILE_NOT_FOUND", "XTREAM_PROFILE_LOCKED", "XTREAM_CREDENTIAL_LIMIT"),
)
def issue_credential(body: IssueIn) -> object:
    return resolve(CredentialService).issue(
        user_id=current_user.id, context=current_profile(), profile_id=body.profile_id, label=body.label
    )


@blueprint.delete("/credentials/<int:credential_id>")
@endpoint(
    summary="Revoke an app credential (the TV app stops at its next request)",
    profile=True,
    errors=(_KIDS, "XTREAM_CREDENTIAL_NOT_FOUND"),
)
def revoke_credential(credential_id: int) -> object:
    resolve(CredentialService).revoke(user_id=current_user.id, context=current_profile(), credential_id=credential_id)
    return no_content()
