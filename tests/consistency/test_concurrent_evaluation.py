"""
tests/consistency/test_concurrent_evaluation.py — Testes de consistência sob concorrência.

Usa asyncio.TaskGroup real para validar comportamento do cache
durante atualizações concorrentes.
"""
from __future__ import annotations

import asyncio

import pytest

from src.core.cache import CacheNotReadyError, FlagCache
from src.core.evaluation import EvaluationEngine
from src.schemas.evaluation import EvaluationContext
from tests.factories import FlagFactory


class TestConcurrentEvaluation:

    @pytest.mark.asyncio
    async def test_cache_invalidation_during_concurrent_evaluation(self):
        """
        Cenário crítico: invalidação de cache enquanto 100 goroutines
        estão avaliando a mesma flag. Nenhuma deve receber resultado
        inconsistente (nem erro, nem panic, nem resultado de flag errada).
        """
        cache = FlagCache()
        engine = EvaluationEngine(cache=cache)

        flag_key = "concurrent-test-flag"
        initial_flag = FlagFactory.build(
            key=flag_key,
            default_value=False,
            environments={
                "production": {
                    "enabled": True,
                    "override": None,
                    "rollout_percentage": 100,
                    "rules": [],
                }
            },
        )
        await cache.set(flag_key, initial_flag)
        await cache.mark_ready()

        results: list[bool] = []
        errors: list[str] = []

        async def evaluate_continuously(user_id: str) -> None:
            for _ in range(100):
                try:
                    ctx = EvaluationContext(user_id=user_id, environment="production")
                    flag = cache.get(flag_key)
                    if flag is not None:
                        result = engine.evaluate(flag, ctx)
                        # O resultado deve ser bool, nunca None ou exceção
                        assert isinstance(result.value, bool)
                        results.append(result.value)
                except CacheNotReadyError:
                    # Pode ocorrer durante warm-up — não é um erro aqui
                    pass
                except Exception as exc:
                    errors.append(str(exc))
                await asyncio.sleep(0)  # yield para o event loop

        async def invalidate_periodically() -> None:
            for i in range(10):
                await asyncio.sleep(0.01)
                new_flag = FlagFactory.build(
                    key=flag_key,
                    default_value=bool(i % 2),  # alterna true/false
                    environments={
                        "production": {
                            "enabled": True,
                            "override": None,
                            "rollout_percentage": 100,
                            "rules": [],
                        }
                    },
                )
                await cache.set(flag_key, new_flag)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(invalidate_periodically())
            for i in range(100):
                tg.create_task(evaluate_continuously(f"user-{i}"))

        assert len(errors) == 0, f"Erros durante concorrência: {errors[:5]}"
        # 100 goroutines × 100 avaliações = 10.000 resultados esperados
        assert len(results) == 10_000

    @pytest.mark.asyncio
    async def test_warm_up_blocks_requests_until_complete(self):
        """
        Durante o warm_up, requests de evaluation não devem ser aceitos.
        Isso previne avaliações com cache vazio que retornariam defaults errados.
        """
        cache = FlagCache()

        warm_up_complete = asyncio.Event()
        evaluation_attempted_before_ready = False

        async def slow_warm_up() -> None:
            await asyncio.sleep(0.1)  # simula carregamento lento
            await cache.mark_ready()
            warm_up_complete.set()

        async def try_evaluate_early() -> None:
            nonlocal evaluation_attempted_before_ready
            # Tenta avaliar antes do warm_up completar
            if not cache.is_ready():
                evaluation_attempted_before_ready = True
                with pytest.raises(CacheNotReadyError):
                    cache.get("any-flag")

        async with asyncio.TaskGroup() as tg:
            tg.create_task(slow_warm_up())
            tg.create_task(try_evaluate_early())

        assert evaluation_attempted_before_ready, (
            "Teste não alcançou a condição desejada — cache já estava pronto"
        )
