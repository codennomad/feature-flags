"""
tests/unit/core/test_hashing.py — Determinismo e uniformidade do hash.

Prova que compute_rollout_hash é:
- Determinístico: mesmos inputs = mesmo output
- Uniforme: distribuição estatisticamente correta
- Independente entre flags: correlação próxima de 50%
"""
from __future__ import annotations

import statistics

import pytest
from faker import Faker

from src.core.hashing import compute_rollout_hash


class TestDeterministicHash:

    def test_same_inputs_always_produce_same_result(self):
        """O hash é determinístico: mesmos inputs = mesmo output, sempre."""
        for _ in range(1000):
            h1 = compute_rollout_hash("my-flag", "user-abc")
            h2 = compute_rollout_hash("my-flag", "user-abc")
            assert h1 == h2

    def test_different_flags_same_user_different_hash(self):
        """
        user_id idêntico em flags diferentes deve ter distribuições independentes.
        Sem isso, ativar flag A sempre ativaria flag B para os mesmos usuários.
        """
        results_flag_a = []
        results_flag_b = []
        for i in range(10_000):
            user_id = f"user-{i}"
            ha = compute_rollout_hash("flag-a", user_id) < 5000
            hb = compute_rollout_hash("flag-b", user_id) < 5000
            results_flag_a.append(ha)
            results_flag_b.append(hb)

        # As distribuições são independentes — correlação deve ser baixa
        overlap = sum(1 for a, b in zip(results_flag_a, results_flag_b) if a == b)
        correlation = overlap / 10_000
        # Correlação esperada para independentes: ~50% (± 2%)
        assert 0.48 <= correlation <= 0.52, (
            f"Correlação anômala entre flags: {correlation:.2%}"
        )

    def test_rollout_distribution_is_uniform(self):
        """
        Para rollout de 50%, exatamente ~50% dos usuários devem estar incluídos.
        Tolerância estatística: ± 1% para 100.000 amostras.
        """
        fake = Faker()
        flag_key = "distribution-test"
        n = 100_000
        threshold = 5000  # 50% de 10000 buckets

        included = sum(
            1
            for _ in range(n)
            if compute_rollout_hash(flag_key, fake.uuid4()) < threshold
        )
        ratio = included / n
        assert 0.49 <= ratio <= 0.51, (
            f"Distribuição fora do esperado: {ratio:.2%} (esperado 50% ± 1%)"
        )

    @pytest.mark.parametrize("percentage", [0, 1, 10, 25, 50, 75, 90, 99, 100])
    def test_rollout_boundary_percentages(self, percentage: int):
        """
        Percentuais extremos devem produzir distribuições corretas.
        0% → nenhum usuário; 100% → todos os usuários.
        """
        fake = Faker()
        threshold = percentage * 100  # 0-10000

        n = 10_000
        included = sum(
            1
            for _ in range(n)
            if compute_rollout_hash("boundary-test", fake.uuid4()) < threshold
        )
        ratio = included / n
        tolerance = 0.03  # ± 3% para n menor
        assert abs(ratio - percentage / 100) <= tolerance, (
            f"Percentual {percentage}%: obtido {ratio:.2%}"
        )
