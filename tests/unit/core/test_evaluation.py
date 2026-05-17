"""
tests/unit/core/test_evaluation.py — Testes de corretude do motor de avaliação.

Cada teste verifica UMA camada da precedência.
Ordem: override > targeting > rollout > default.
"""
from __future__ import annotations

import pytest
from faker import Faker

from src.core.evaluation import EvaluationEngine
from src.schemas.evaluation import EvaluationContext
from tests.factories import FlagFactory, RuleFactory


class TestEvaluationPrecedence:
    """
    Cada teste verifica UMA camada da precedência.
    Ordem: override > targeting > rollout > default.
    """

    def test_environment_override_beats_targeting(self):
        """Override de ambiente tem prioridade máxima, sempre."""
        flag = FlagFactory.build(
            environments={
                "production": {
                    "enabled": True,
                    "override": False,  # override force-off
                    "rollout_percentage": 100,
                    "rules": [
                        RuleFactory.build(serve=True, priority=1)
                    ],
                }
            },
        )
        context = EvaluationContext(
            user_id="user-123",
            environment="production",
            attributes={"country": "BR"},  # bate na regra
        )
        result = EvaluationEngine().evaluate(flag, context)
        assert result.value is False
        assert result.reason == "OVERRIDE"

    def test_targeting_rule_beats_rollout(self):
        """Regra de targeting tem prioridade sobre percentual de rollout."""
        flag = FlagFactory.build(
            environments={
                "production": {
                    "enabled": True,
                    "override": None,
                    "rollout_percentage": 0,  # nenhum usuário no rollout
                    "rules": [
                        {
                            "id": "rule-1",
                            "name": "Enterprise Rule",
                            "priority": 1,
                            "conditions": [
                                {"attribute": "plan", "operator": "eq", "value": "enterprise"}
                            ],
                            "condition_combinator": "AND",
                            "serve": True,
                        }
                    ],
                }
            }
        )
        context = EvaluationContext(
            user_id="any-user",
            environment="production",
            attributes={"plan": "enterprise"},
        )
        result = EvaluationEngine().evaluate(flag, context)
        assert result.value is True
        assert result.reason == "TARGETING_MATCH"

    def test_rollout_zero_returns_default(self):
        """Rollout 0% retorna default independente do user_id."""
        flag = FlagFactory.build(
            default_value=False,
            environments={
                "production": {
                    "enabled": True,
                    "override": None,
                    "rollout_percentage": 0,
                    "rules": [],
                }
            },
        )
        for user_id in ["user-1", "user-999", "superuser", "admin"]:
            context = EvaluationContext(user_id=user_id, environment="production")
            result = EvaluationEngine().evaluate(flag, context)
            assert result.value is False, f"Falhou para user_id={user_id}"
            assert result.reason == "DEFAULT"

    def test_rollout_100_returns_true_for_all(self):
        """Rollout 100% retorna True para qualquer user_id."""
        flag = FlagFactory.build(
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
        fake = Faker()
        for _ in range(500):
            context = EvaluationContext(user_id=fake.uuid4(), environment="production")
            result = EvaluationEngine().evaluate(flag, context)
            assert result.value is True

    def test_disabled_flag_returns_default_regardless_of_rules(self):
        """Flag desabilitada retorna default mesmo com regras que batem."""
        flag = FlagFactory.build(
            default_value=False,
            environments={
                "production": {
                    "enabled": False,  # desabilitada
                    "override": None,
                    "rollout_percentage": 100,
                    "rules": [
                        {
                            "id": "rule-1",
                            "name": "All match",
                            "priority": 1,
                            "conditions": [
                                {"attribute": "country", "operator": "eq", "value": "BR"}
                            ],
                            "condition_combinator": "AND",
                            "serve": True,
                        }
                    ],
                }
            },
        )
        context = EvaluationContext(
            user_id="any",
            environment="production",
            attributes={"country": "BR"},
        )
        result = EvaluationEngine().evaluate(flag, context)
        assert result.value is False
        assert result.reason == "FLAG_DISABLED"
