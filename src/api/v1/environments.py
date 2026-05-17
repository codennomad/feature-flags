"""
Gerenciamento de ambientes de feature flags.

Endpoints:
    POST   /api/v1/flags/{flag_key}/environments/{env}/enable
    POST   /api/v1/flags/{flag_key}/environments/{env}/disable
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import CurrentUserDep, SessionDep, require_role
from src.api.v1.flags import (
    _get_flag_or_404,
    _insert_audit,
    _publish_invalidation,
)
from src.schemas.flag import FlagResponse

router = APIRouter(prefix="/flags", tags=["environments"])


@router.post(
    "/{flag_key}/environments/{env}/enable",
    response_model=FlagResponse,
    dependencies=[Depends(require_role("admin", "editor"))],
)
async def enable_flag_in_environment(
    flag_key: str,
    env: str,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> FlagResponse:
    """Ativa uma flag em um ambiente específico."""
    flag = await _get_flag_or_404(session, flag_key)
    before = dict(flag.environments)
    envs = dict(flag.environments)

    if env not in envs:
        envs[env] = {"enabled": False, "override": None, "rollout_percentage": 0, "rules": []}
    envs[env] = {**envs[env], "enabled": True}
    flag.environments = envs
    flag.version += 1

    await _insert_audit(
        session, flag, "enabled", current_user["sub"],
        {"before": {"environments": before}, "after": {"environments": envs}},
    )
    await session.flush()
    await session.refresh(flag)
    await _publish_invalidation(flag, "update")
    return FlagResponse.model_validate(flag)


@router.post(
    "/{flag_key}/environments/{env}/disable",
    response_model=FlagResponse,
    dependencies=[Depends(require_role("admin", "editor"))],
)
async def disable_flag_in_environment(
    flag_key: str,
    env: str,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> FlagResponse:
    """Desativa uma flag em um ambiente específico."""
    flag = await _get_flag_or_404(session, flag_key)
    before = dict(flag.environments)
    envs = dict(flag.environments)

    if env not in envs:
        envs[env] = {"enabled": False, "override": None, "rollout_percentage": 0, "rules": []}
    envs[env] = {**envs[env], "enabled": False}
    flag.environments = envs
    flag.version += 1

    await _insert_audit(
        session, flag, "disabled", current_user["sub"],
        {"before": {"environments": before}, "after": {"environments": envs}},
    )
    await session.flush()
    await session.refresh(flag)
    await _publish_invalidation(flag, "update")
    return FlagResponse.model_validate(flag)
