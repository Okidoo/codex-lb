from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.audit.service import AuditService
from app.core.auth.dependencies import (
    require_dashboard_write_access,
    set_dashboard_error_format,
    validate_dashboard_session,
)
from app.core.exceptions import DashboardBadRequestError, DashboardNotFoundError
from app.dependencies import ModelAliasesContext, get_model_aliases_context
from app.modules.model_aliases.schemas import (
    ModelAliasDeleteResponse,
    ModelAliasListResponse,
    ModelAliasResponse,
    ModelAliasUpsertRequest,
)
from app.modules.model_aliases.service import ModelAliasValidationError
from app.modules.proxy.account_cache import get_account_selection_cache

router = APIRouter(
    prefix="/api/model-aliases",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


def _to_response(alias) -> ModelAliasResponse:
    return ModelAliasResponse(
        id=alias.id,
        source_model=alias.source_model,
        target_model=alias.target_model,
        enabled=alias.enabled,
        created_at=alias.created_at,
        updated_at=alias.updated_at,
    )


@router.get("", response_model=ModelAliasListResponse)
async def list_model_aliases(
    context: ModelAliasesContext = Depends(get_model_aliases_context),
) -> ModelAliasListResponse:
    aliases = await context.service.list_aliases()
    return ModelAliasListResponse(aliases=[_to_response(alias) for alias in aliases])


@router.post("", response_model=ModelAliasResponse)
async def upsert_model_alias(
    payload: ModelAliasUpsertRequest,
    request: Request,
    _write_access=Depends(require_dashboard_write_access),
    context: ModelAliasesContext = Depends(get_model_aliases_context),
) -> ModelAliasResponse:
    try:
        alias = await context.service.upsert_alias(
            source_model=payload.source_model,
            target_model=payload.target_model,
            enabled=payload.enabled,
        )
    except ModelAliasValidationError as exc:
        raise DashboardBadRequestError(str(exc), code="invalid_model_alias") from exc
    await get_account_selection_cache().invalidate()
    AuditService.log_async(
        "model_alias_upserted",
        actor_ip=request.client.host if request.client else None,
        details={
            "source_model": alias.source_model,
            "target_model": alias.target_model,
            "enabled": alias.enabled,
        },
    )
    return _to_response(alias)


@router.delete("/{alias_id}", response_model=ModelAliasDeleteResponse)
async def delete_model_alias(
    alias_id: str,
    request: Request,
    _write_access=Depends(require_dashboard_write_access),
    context: ModelAliasesContext = Depends(get_model_aliases_context),
) -> ModelAliasDeleteResponse:
    deleted = await context.service.delete_alias(alias_id)
    if not deleted:
        raise DashboardNotFoundError("Model alias not found", code="model_alias_not_found")
    await get_account_selection_cache().invalidate()
    AuditService.log_async(
        "model_alias_deleted",
        actor_ip=request.client.host if request.client else None,
        details={"alias_id": alias_id},
    )
    return ModelAliasDeleteResponse(status="deleted")
