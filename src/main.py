"""
Feature Flags API — app factory + lifespan.

Ordem de inicialização (crítica — documentada no prompt.md):
    1. database.connect()
    2. redis.connect()
    3. cache.warm_up(load_all_flags)
    4. redis.start_listener()
    5. metrics.register_collectors()

Middleware:
    - Prometheus (prometheus-fastapi-instrumentator)
    - CORS
    - Trusted Host

Endpoints registrados:
    /api/v1/flags
    /api/v1/evaluate
    /api/v1/webhooks
    /health
    /metrics (Prometheus scrape)
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

try:
    from pydantic_core import PydanticSerializationError as _PydanticSerializationError
except ImportError:  # pragma: no cover
    _PydanticSerializationError = None  # type: ignore[assignment, misc]
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select

from src.config import settings
from src.core.cache import FlagCache
from src.core.evaluation import EvaluationEngine
from src.infra import database, redis as redis_infra
from src.infra.metrics import db_pool_size, db_pool_checked_out
from src.models.flag import Flag

log = logging.getLogger(__name__)

# ── Logging estruturado (structlog) ──────────────────────────────────────────────
def _configure_logging() -> None:
    """Configura structlog para emitir JSON em produção e texto bonito em dev."""
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.debug:
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG if settings.debug else logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    # Redireciona o stdlib logging padrão (uvicorn, sqlalchemy, etc.) para structlog
    logging.basicConfig(
        format="%(message)s",
        level=logging.DEBUG if settings.debug else logging.INFO,
    )


# ── Sentry (error tracking + tracing) ────────────────────────────────────────
def _configure_sentry() -> None:
    """Inicializa o Sentry se SENTRY_DSN estiver configurado."""
    if not settings.sentry_dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        environment=settings.environment,
        release=settings.app_version,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        # Nunca envia dados pessoais / tokens
        send_default_pii=False,
    )
    log.info("Sentry inicializado (environment=%s)", settings.environment)


# ── Limiter global (slowapi) ──────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


async def _load_all_flags() -> list[dict]:
    """Carrega todas as flags do banco e retorna lista de dicts (formato do cache)."""
    async with database.AsyncSessionLocal() as session:
        result = await session.execute(select(Flag))
        flags = result.scalars().all()
        return [
            {
                "id": str(f.id),
                "key": f.key,
                "name": f.name,
                "flag_type": f.flag_type,
                "default_value": f.default_value,
                "environments": f.environments,
                "version": f.version,
            }
            for f in flags
        ]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Ciclo de vida da aplicação.
    Garante inicialização e encerramento ordenados.
    """
    # ── Startup ───────────────────────────────────────────────────────────────
    log.info("▶ Iniciando Feature Flags API...")

    # 1. Banco de dados
    await database.connect()

    # 2. Redis
    await redis_infra.connect()

    # 3. Cache warm-up (bloqueia até concluir)
    cache = FlagCache()
    await cache.warm_up(_load_all_flags)
    app.state.cache = cache

    # 4. Motor de avaliação (stateless, recebe cache por ref)
    engine = EvaluationEngine(cache=cache)
    app.state.engine = engine

    # 5. Listener pub/sub (invalida cache em tempo real)
    redis_infra.register_invalidation_handler(cache.handle_invalidation_message)
    await redis_infra.start_listener()

    # 6. Métricas de pool (valores iniciais)
    db_pool_size.set(settings.db_pool_size)
    db_pool_checked_out.set(0)

    log.info("✅ Feature Flags API pronta.")
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    log.info("⏹ Encerrando Feature Flags API...")
    await redis_infra.disconnect()
    await database.disconnect()
    log.info("✅ Encerramento concluído.")


def create_app() -> FastAPI:
    """Factory function — cria e configura a aplicação FastAPI."""
    _configure_logging()
    _configure_sentry()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # ── Slowapi (rate limiting) ───────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    # JSON com profundidade excessiva causa RecursionError no parsing/validação
    app.add_exception_handler(
        RecursionError,
        lambda request, exc: JSONResponse(
            status_code=422,
            content={"detail": "Payload excede profundidade máxima suportada."},
        ),
    )
    # Pydantic v2 lança PydanticSerializationError ao serializar objetos demasiado aninhados
    if _PydanticSerializationError is not None:
        app.add_exception_handler(
            _PydanticSerializationError,
            lambda request, exc: JSONResponse(
                status_code=422,
                content={"detail": "Payload excede profundidade máxima suportada."},
            ),
        )
    app.add_middleware(SlowAPIMiddleware)

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Em dev (DEBUG=true): aceita qualquer origem.
    # Em prod: usa CORS_ORIGINS (env var, vírgula-separado). Vazio = bloqueado.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # ── Trusted Host ─────────────────────────────────────────────────────────
    # allowed_hosts vem de ALLOWED_HOSTS (env var, vírgula-separado).
    # Default: localhost/127.0.0.1 para dev. Em produção defina explicitamente.
    if not settings.debug:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    # ── Prometheus ────────────────────────────────────────────────────────────
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
    ).instrument(app).expose(app, endpoint="/metrics")

    # ── Routers ───────────────────────────────────────────────────────────────
    from src.api.v1.flags import router as flags_router
    from src.api.v1.evaluation import router as evaluation_router
    from src.api.v1.webhooks import router as webhooks_router
    from src.api.v1.environments import router as environments_router

    app.include_router(flags_router, prefix="/api/v1")
    app.include_router(evaluation_router, prefix="/api/v1")
    app.include_router(webhooks_router, prefix="/api/v1")
    app.include_router(environments_router, prefix="/api/v1")

    # ── Health ────────────────────────────────────────────────────────────────
    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok", "version": settings.app_version}

    return app


# Instância usada pelo uvicorn
app = create_app()
