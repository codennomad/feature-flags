"""
CRUD de feature flags, regras de targeting e audit.

Endpoints:
    POST   /api/v1/flags
    GET    /api/v1/flags
    GET    /api/v1/flags/{flag_key}
    PATCH  /api/v1/flags/{flag_key}
    DELETE /api/v1/flags/{flag_key}
    POST   /api/v1/flags/{flag_key}/rules
    PUT    /api/v1/flags/{flag_key}/rules/{rule_id}
    DELETE /api/v1/flags/{flag_key}/rules/{rule_id}
    GET    /api/v1/flags/{flag_key}/audit

Nota: enable/disable por ambiente estão em api/v1/environments.py
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import (
    CurrentUserDep,
    SessionDep,
    require_role,
)
from src.infra import redis as redis_infra
from src.models.audit import AuditLog
from src.models.flag import Flag
from src.schemas.flag import (
    AuditLogListResponse,
    AuditLogResponse,
    FlagCreate,
    FlagListResponse,
    FlagResponse,
    FlagUpdate,
    RuleSchema,
)

router = APIRouter(prefix="/flags", tags=["flags"])


def _flag_to_dict(flag: Flag) -> dict:
    return {
        "id": flag.id,
        "key": flag.key,
        "name": flag.name,
        "description": flag.description,
        "flag_type": flag.flag_type,
        "default_value": flag.default_value,
        "environments": flag.environments,
        "created_at": flag.created_at,
        "updated_at": flag.updated_at,
        "created_by": flag.created_by,
        "version": flag.version,
    }


async def _get_flag_or_404(session: AsyncSession, key: str) -> Flag:
    result = await session.execute(select(Flag).where(Flag.key == key))
    flag = result.scalar_one_or_none()
    if flag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flag não encontrada")
    return flag


async def _insert_audit(
    session: AsyncSession,
    flag: Flag,
    action: str,
    actor: str,
    changes: dict,
    metadata: dict | None = None,
) -> None:
    """Insere entrada no audit log. DEVE ser chamado na mesma transação da mudança."""
    entry = AuditLog(
        id=uuid.uuid4(),
        flag_id=flag.id,
        action=action,
        actor=actor,
        changes=changes,
        metadata_=metadata,
    )
    session.add(entry)


async def _publish_invalidation(flag: Flag, action: str) -> None:
    """Publica invalidação de cache via Redis pub/sub."""
    try:
        await redis_infra.publish_invalidation(flag.key, flag.version, action)
    except Exception:
        # Falha na publicação não deve abortar a operação de banco
        pass


# ─── CREATE ───────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=FlagResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("admin", "editor"))],
)
async def create_flag(
    data: FlagCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> FlagResponse:
    # Verifica duplicidade de key
    existing = await session.execute(select(Flag).where(Flag.key == data.key))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Flag com key '{data.key}' já existe",
        )

    flag = Flag(
        id=uuid.uuid4(),
        key=data.key,
        name=data.name,
        description=data.description,
        flag_type=data.flag_type,
        default_value=data.default_value,
        environments={
            env: cfg.model_dump() for env, cfg in data.environments.items()
        },
        created_by=current_user["sub"],
        version=1,
    )
    session.add(flag)

    # Audit log na mesma transação — CRÍTICO
    await _insert_audit(
        session, flag, "created", current_user["sub"],
        {"before": None, "after": _flag_to_dict(flag)},
    )

    await session.flush()
    await session.refresh(flag)
    await _publish_invalidation(flag, "update")
    return FlagResponse.model_validate(flag)


# ─── LIST ─────────────────────────────────────────────────────────────────────


@router.get("", response_model=FlagListResponse)
async def list_flags(
    session: SessionDep,
    current_user: CurrentUserDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=255),
) -> FlagListResponse:
    query = select(Flag)
    if search:
        # Busca por nome ou key (parameterizado — sem injeção SQL)
        like = f"%{search}%"
        query = query.where(Flag.name.ilike(like) | Flag.key.ilike(like))

    total_result = await session.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar_one()

    result = await session.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    )
    flags = result.scalars().all()
    return FlagListResponse(
        items=[FlagResponse.model_validate(f) for f in flags],
        total=total,
        page=page,
        page_size=page_size,
    )


# ─── GET ──────────────────────────────────────────────────────────────────────


@router.get("/{flag_key}", response_model=FlagResponse)
async def get_flag(
    flag_key: str,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> FlagResponse:
    flag = await _get_flag_or_404(session, flag_key)
    return FlagResponse.model_validate(flag)


# ─── UPDATE ───────────────────────────────────────────────────────────────────


@router.patch(
    "/{flag_key}",
    response_model=FlagResponse,
    dependencies=[Depends(require_role("admin", "editor"))],
)
async def update_flag(
    flag_key: str,
    data: FlagUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> FlagResponse:
    flag = await _get_flag_or_404(session, flag_key)
    before = _flag_to_dict(flag)

    if data.name is not None:
        flag.name = data.name
    if data.description is not None:
        flag.description = data.description
    if data.default_value is not None:
        flag.default_value = data.default_value
    if data.environments is not None:
        flag.environments = {
            env: cfg.model_dump() for env, cfg in data.environments.items()
        }

    flag.version += 1
    await _insert_audit(
        session, flag, "updated", current_user["sub"],
        {"before": before, "after": _flag_to_dict(flag)},
    )
    await session.flush()
    await session.refresh(flag)
    await _publish_invalidation(flag, "update")
    return FlagResponse.model_validate(flag)


# ─── DELETE ───────────────────────────────────────────────────────────────────


@router.delete(
    "/{flag_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role("admin"))],
)
async def delete_flag(
    flag_key: str,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> None:
    flag = await _get_flag_or_404(session, flag_key)
    await _insert_audit(
        session, flag, "deleted", current_user["sub"],
        {"before": _flag_to_dict(flag), "after": None},
    )
    await session.delete(flag)
    await _publish_invalidation(flag, "delete")


# ─── RULES ────────────────────────────────────────────────────────────────────


@router.post(
    "/{flag_key}/rules",
    response_model=FlagResponse,
    dependencies=[Depends(require_role("admin", "editor"))],
)
async def add_rule(
    flag_key: str,
    rule: RuleSchema,
    session: SessionDep,
    current_user: CurrentUserDep,
    env: Annotated[str, Query(description="Nome do ambiente")],
) -> FlagResponse:
    flag = await _get_flag_or_404(session, flag_key)
    before = dict(flag.environments)
    envs = dict(flag.environments)

    if env not in envs:
        envs[env] = {"enabled": False, "override": None, "rollout_percentage": 0, "rules": []}

    envs[env]["rules"] = envs[env].get("rules", []) + [rule.model_dump()]
    flag.environments = envs
    flag.version += 1

    await _insert_audit(
        session, flag, "rule_added", current_user["sub"],
        {"before": {"environments": before}, "after": {"environments": envs}},
    )
    await session.flush()
    await session.refresh(flag)
    await _publish_invalidation(flag, "update")
    return FlagResponse.model_validate(flag)


@router.put(
    "/{flag_key}/rules/{rule_id}",
    response_model=FlagResponse,
    dependencies=[Depends(require_role("admin", "editor"))],
)
async def update_rule(
    flag_key: str,
    rule_id: str,
    rule: RuleSchema,
    session: SessionDep,
    current_user: CurrentUserDep,
    env: Annotated[str, Query(description="Nome do ambiente")],
) -> FlagResponse:
    flag = await _get_flag_or_404(session, flag_key)
    before = dict(flag.environments)
    envs = dict(flag.environments)

    if env not in envs:
        raise HTTPException(status_code=404, detail="Ambiente não configurado")

    rules = envs[env].get("rules", [])
    updated = [rule.model_dump() if r.get("id") == rule_id else r for r in rules]
    if not any(r.get("id") == rule_id for r in rules):
        raise HTTPException(status_code=404, detail="Regra não encontrada")

    envs[env]["rules"] = updated
    flag.environments = envs
    flag.version += 1

    await _insert_audit(
        session, flag, "rule_updated", current_user["sub"],
        {"before": {"environments": before}, "after": {"environments": envs}},
    )
    await session.flush()
    await session.refresh(flag)
    await _publish_invalidation(flag, "update")
    return FlagResponse.model_validate(flag)


@router.delete(
    "/{flag_key}/rules/{rule_id}",
    response_model=FlagResponse,
    dependencies=[Depends(require_role("admin", "editor"))],
)
async def delete_rule(
    flag_key: str,
    rule_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    env: Annotated[str, Query(description="Nome do ambiente")],
) -> FlagResponse:
    flag = await _get_flag_or_404(session, flag_key)
    before = dict(flag.environments)
    envs = dict(flag.environments)

    if env not in envs:
        raise HTTPException(status_code=404, detail="Ambiente não configurado")

    rules = [r for r in envs[env].get("rules", []) if r.get("id") != rule_id]
    envs[env]["rules"] = rules
    flag.environments = envs
    flag.version += 1

    await _insert_audit(
        session, flag, "rule_deleted", current_user["sub"],
        {"before": {"environments": before}, "after": {"environments": envs}},
    )
    await session.flush()
    await session.refresh(flag)
    await _publish_invalidation(flag, "update")
    return FlagResponse.model_validate(flag)


# ─── AUDIT ────────────────────────────────────────────────────────────────────


@router.get("/{flag_key}/audit", response_model=AuditLogListResponse)
async def get_audit_log(
    flag_key: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AuditLogListResponse:
    flag = await _get_flag_or_404(session, flag_key)

    total_result = await session.execute(
        select(func.count()).where(AuditLog.flag_id == flag.id)
    )
    total = total_result.scalar_one()

    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.flag_id == flag.id)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = result.scalars().all()
    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
    )
