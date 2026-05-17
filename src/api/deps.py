"""
Injeção de dependências para FastAPI.
- get_session: sessão async do banco
- get_current_user: extrai e valida JWT Bearer
- require_role: verifica autorização por role
- get_cache: retorna FlagCache da aplicação
- get_engine: retorna EvaluationEngine
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.infra.database import AsyncSessionLocal

log = logging.getLogger(__name__)

# ─── Banco de dados ────────────────────────────────────────────────────────────


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]

# ─── Autenticação JWT ──────────────────────────────────────────────────────────


def _decode_token(token: str) -> dict[str, Any]:
    """
    Decodifica e valida JWT.
    - Rejeita algoritmo 'none' explicitamente (ataque clássico)
    - Rejeita tokens expirados (sem tolerância de clock)
    """
    try:
        # algorithms= lista explícita — NUNCA aceitar 'none'
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={
                "verify_exp": True,
                "verify_iat": True,
                "require": ["sub", "exp"],
            },
        )
        return payload
    except JWTError as exc:
        # Log sem expor o token (compliance)
        log.info("JWT inválido: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """Extrai usuário do token JWT Bearer."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header obrigatório",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Formato inválido. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _decode_token(parts[1])


CurrentUserDep = Annotated[dict, Depends(get_current_user)]


def require_role(*allowed_roles: str):
    """
    Dependency factory que verifica se o usuário tem uma das roles permitidas.
    Uso: Depends(require_role("admin", "editor"))
    """

    async def _check(current_user: CurrentUserDep) -> dict:
        user_role = current_user.get("role", "viewer")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user_role}' não tem permissão. Requerido: {allowed_roles}",
            )
        return current_user

    return _check


# ─── Cache e Engine ────────────────────────────────────────────────────────────


def get_cache(request: Request):
    """Retorna FlagCache da aplicação (injetado no lifespan)."""
    return request.app.state.cache


def get_engine(request: Request):
    """Retorna EvaluationEngine da aplicação."""
    return request.app.state.engine


CacheDep = Annotated[Any, Depends(get_cache)]
EngineDep = Annotated[Any, Depends(get_engine)]
