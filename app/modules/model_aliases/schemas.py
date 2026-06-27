from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.modules.shared.schemas import DashboardModel


class ModelAliasResponse(DashboardModel):
    id: str
    source_model: str
    target_model: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ModelAliasListResponse(DashboardModel):
    aliases: list[ModelAliasResponse] = Field(default_factory=list)


class ModelAliasUpsertRequest(DashboardModel):
    source_model: str = Field(min_length=1, max_length=128)
    target_model: str = Field(min_length=1, max_length=128)
    enabled: bool = True


class ModelAliasDeleteResponse(DashboardModel):
    status: str
