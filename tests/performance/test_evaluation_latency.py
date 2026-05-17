"""
tests/performance/test_evaluation_latency.py — Prova que a avaliação está abaixo de 1ms.

IMPORTANTE: Este teste requer cache warm e zero I/O.
Falha no CI se p99 > 1ms — regressão de performance é quebra de contrato.
"""
from __future__ import annotations

import statistics
import time

import pytest

from src.core.evaluation import EvaluationEngine
from src.schemas.evaluation import EvaluationContext

pytestmark = pytest.mark.performance


class TestEvaluationLatency:

    def test_single_evaluation_under_1ms(self, loaded_cache):
        """
        A promessa central do sistema: avaliação em < 1ms.
        Testado com cache warm e sem I/O.
        """
        engine = EvaluationEngine(cache=loaded_cache)
        context = EvaluationContext(
            user_id="benchmark-user",
            environment="production",
            attributes={"country": "BR", "plan": "pro"},
        )
        flag = loaded_cache.get("test-flag")
        assert flag is not None, "Cache não está aquecido com 'test-flag'"

        # Aquece JIT/caches de CPU
        for _ in range(1000):
            engine.evaluate(flag, context)

        # Mede latência real
        latencies: list[float] = []
        for _ in range(10_000):
            start = time.perf_counter_ns()
            engine.evaluate(flag, context)
            elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
            latencies.append(elapsed_ms)

        p50 = statistics.median(latencies)
        p95 = statistics.quantiles(latencies, n=20)[18]   # 95th percentile
        p99 = statistics.quantiles(latencies, n=100)[98]  # 99th percentile

        # Documentado no output de CI
        print(
            f"\nLatência de avaliação — "
            f"p50={p50:.3f}ms  p95={p95:.3f}ms  p99={p99:.3f}ms"
        )

        assert p50 < 0.1, f"p50 muito alto: {p50:.3f}ms (esperado < 0.1ms)"
        assert p95 < 0.5, f"p95 muito alto: {p95:.3f}ms (esperado < 0.5ms)"
        assert p99 < 1.0, f"p99 fora do SLA: {p99:.3f}ms (esperado < 1ms)"
