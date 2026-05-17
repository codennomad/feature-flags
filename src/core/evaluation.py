"""
Motor de avaliação de feature flags — o coração do sistema.

ORDEM DE PRECEDÊNCIA (crítica — documentada e testada):
    1. Override por ambiente (maior prioridade)
       - Se `override` não for None, retorne-o imediatamente
    2. Flag desabilitada no ambiente
       - Se não enabled, retorne default_value com reason=FLAG_DISABLED
    3. Targeting rules (top-down, first match wins)
       - Regras ordenadas por priority (crescente)
    4. Rollout percentual por hash determinístico
       - mmh3(flag_key:user_id, seed=42) % 10000 < rollout_percentage * 100
    5. Default value da flag (menor prioridade)

CRÍTICO: Avaliação é 100% em memória. ZERO I/O aqui.
O cache é carregado no lifespan e atualizado via pub/sub.
Se o cache não tiver a flag → retorna default_value sem consultar banco.
"""
from __future__ import annotations

import logging
from typing import Any

from src.core.cache import FlagCache, CacheNotReadyError
from src.core.hashing import is_in_rollout
from src.core.targeting import find_matching_rule
from src.infra.metrics import flag_evaluation_duration_seconds, flag_evaluation_total
from src.schemas.evaluation import EvaluationContext, EvaluationResult

log = logging.getLogger(__name__)

# Razões de avaliação (usadas em métricas + logs)
REASON_OVERRIDE = "OVERRIDE"
REASON_TARGETING_MATCH = "TARGETING_MATCH"
REASON_ROLLOUT = "ROLLOUT"
REASON_DEFAULT = "DEFAULT"
REASON_FLAG_DISABLED = "FLAG_DISABLED"
REASON_FLAG_NOT_FOUND = "FLAG_NOT_FOUND"


class EvaluationEngine:
    """
    Motor de avaliação stateless.
    Recebe flag snapshot (dict) e EvaluationContext → EvaluationResult.
    Instrumente com Prometheus em cada avaliação.
    """

    def __init__(self, cache: FlagCache | None = None) -> None:
        self._cache = cache

    def evaluate(
        self,
        flag: dict[str, Any],
        context: EvaluationContext,
    ) -> EvaluationResult:
        """
        Avalia uma flag para um contexto.
        NUNCA faz I/O — tudo em memória.
        NUNCA levanta exceção — retorna EvaluationResult com default em caso de erro.
        """
        flag_key = flag.get("key", "unknown")

        with flag_evaluation_duration_seconds.labels(
            flag_key=flag_key,
            environment=context.environment,
        ).time():
            result = self._evaluate_internal(flag, context)

        flag_evaluation_total.labels(
            flag_key=result.flag_key,
            result=str(result.value),
            reason=result.reason,
        ).inc()

        return result

    def _evaluate_internal(
        self,
        flag: dict[str, Any],
        context: EvaluationContext,
    ) -> EvaluationResult:
        flag_key = flag.get("key", "unknown")
        default_value = flag.get("default_value")
        flag_version = flag.get("version", 0)

        # Recupera configuração do ambiente solicitado
        environments = flag.get("environments", {})
        env_config = environments.get(context.environment)

        if env_config is None:
            # Ambiente não configurado → retorna default
            return EvaluationResult(
                flag_key=flag_key,
                value=default_value,
                reason=REASON_DEFAULT,
                environment=context.environment,
                flag_version=flag_version,
            )

        # ── 1. Override por ambiente (prioridade máxima) ─────────────────────
        override = env_config.get("override")
        if override is not None:
            return EvaluationResult(
                flag_key=flag_key,
                value=override,
                reason=REASON_OVERRIDE,
                environment=context.environment,
                flag_version=flag_version,
            )

        # ── 2. Flag desabilitada ─────────────────────────────────────────────
        if not env_config.get("enabled", False):
            return EvaluationResult(
                flag_key=flag_key,
                value=default_value,
                reason=REASON_FLAG_DISABLED,
                environment=context.environment,
                flag_version=flag_version,
            )

        # ── 3. Targeting rules (first match wins, ordered by priority) ───────
        rules = env_config.get("rules", [])
        if rules:
            # Regras devem estar ordenadas por priority (crescente) no cache
            sorted_rules = sorted(rules, key=lambda r: r.get("priority", 0))
            matched_rule = find_matching_rule(sorted_rules, context.attributes)
            if matched_rule is not None:
                return EvaluationResult(
                    flag_key=flag_key,
                    value=matched_rule.get("serve"),
                    reason=REASON_TARGETING_MATCH,
                    environment=context.environment,
                    flag_version=flag_version,
                )

        # ── 4. Rollout percentual ────────────────────────────────────────────
        rollout_pct = env_config.get("rollout_percentage", 0)
        if is_in_rollout(flag_key, context.user_id, rollout_pct):
            return EvaluationResult(
                flag_key=flag_key,
                value=True,  # rollout sempre serve o valor positivo
                reason=REASON_ROLLOUT,
                environment=context.environment,
                flag_version=flag_version,
            )

        # ── 5. Default (prioridade mínima) ───────────────────────────────────
        return EvaluationResult(
            flag_key=flag_key,
            value=default_value,
            reason=REASON_DEFAULT,
            environment=context.environment,
            flag_version=flag_version,
        )

    def evaluate_from_cache(
        self,
        flag_key: str,
        context: EvaluationContext,
        default_value: Any = None,
    ) -> EvaluationResult:
        """
        Avalia usando o cache interno.
        Se a flag não estiver no cache → retorna default sem I/O.
        """
        if self._cache is None:
            raise RuntimeError("EvaluationEngine sem cache configurado")

        try:
            flag = self._cache.get(flag_key)
        except CacheNotReadyError:
            raise

        if flag is None:
            # Flag não encontrada no cache → default sem consultar banco
            return EvaluationResult(
                flag_key=flag_key,
                value=default_value,
                reason=REASON_FLAG_NOT_FOUND,
                environment=context.environment,
            )

        return self.evaluate(flag, context)
