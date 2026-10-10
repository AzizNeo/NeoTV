from __future__ import annotations

from datetime import datetime

from flask import Blueprint
from pydantic import BaseModel, ConfigDict, Field

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.responses import no_content
from app.kernel.security.auth import current_user
from app.modules._template.services import TemplateService

blueprint = Blueprint("_template", __name__)


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)


class ItemOut(BaseModel):
    id: int
    title: str
    created_at: datetime


@blueprint.get("/items")
@endpoint(summary="List my items", tags=("_template",), response=list[ItemOut])
def list_items() -> object:
    return resolve(TemplateService).list(current_user.id)


@blueprint.post("/items")
@endpoint(summary="Create an item", tags=("_template",), body=ItemIn, response=ItemOut, status=201)
def create_item(body: ItemIn) -> object:
    return resolve(TemplateService).create(current_user.id, body.title)


@blueprint.delete("/items/<int:item_id>")
@endpoint(summary="Delete an item", tags=("_template",), errors=("_TEMPLATE_ITEM_NOT_FOUND",))
def delete_item(item_id: int) -> object:
    resolve(TemplateService).delete(current_user.id, item_id)
    return no_content()
