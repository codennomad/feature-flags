"""
Endpoints de avaliação de feature flags — núcleo de alta performance.

POST /api/v1/evaluate        → avaliação single, leitura exclusiva do cache
POST /api/v1/evaluate/batch  → avaliação em lote (até 50 flags)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.api.deps import CurrentUserDep
from src.core.cache import CacheNotReadyError
from src.core.evaluation import EvaluationEngine
from src.schemas.evaluation import (
    BatchEvaluationRequest,
    BatchEvaluationResponse,
    EvaluationResult,
    SingleEvaluationRequest,
)

router = APIRouter(prefix="/evaluate", tags=["evaluation"])
limiter = Limiter(key_func=get_remote_address)


@router.post(
    "",
    response_model=EvaluationResult,
    summary="Avaliar uma feature flag",
)
@limiter.limit("100/minute")
async def evaluate_single(
    request: Request,
    body: SingleEvaluationRequest,
    current_user: CurrentUserDep,
) -> EvaluationResult:
    """
    Avalia uma única flag. Operação de leitura pura — zero I/O de banco.
    Latência alvo: p50<0.1ms, p95<0.5ms, p99<1ms.
    """
    engine: EvaluationEngine = request.app.state.engine
    cache = request.app.state.cache

    try:
        raw_flag = cache.get(body.flag_key)
    except CacheNotReadyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache não está pronto. Tente novamente em instantes.",
        )

    if raw_flag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Flag '{body.flag_key}' não encontrada",
        )

    result = engine.evaluate(raw_flag, body.context)
    return result


@router.post(
    "/batch",
    response_model=BatchEvaluationResponse,
    summary="Avaliar múltiplas feature flags em lote",
)
@limiter.limit("200/minute")
async def evaluate_batch(
    request: Request,
    body: BatchEvaluationRequest,
    current_user: CurrentUserDep,
) -> BatchEvaluationResponse:
    """
    Avalia até 50 flags em lote. Leitura exclusiva do cache — sem I/O de banco.
    Retorna resultados para flags encontradas; flags inexistentes são omitidas.
    """
    engine: EvaluationEngine = request.app.state.engine
    cache = request.app.state.cache

    try:
        results: list[EvaluationResult] = []
        for flag_key in body.flags:
            raw_flag = cache.get(flag_key)
            if raw_flag is None:
                continue  # flag inexistente — omitida silenciosamente no lote
            result = engine.evaluate(raw_flag, body.context)
            results.append(result)
    except CacheNotReadyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache não está pronto. Tente novamente em instantes.",
        )

    return BatchEvaluationResponse(results=results)
