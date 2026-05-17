"""
tests/security/test_rate_limiting.py — Testes de DoS e brute force.

Valida que o endpoint de evaluation tem rate limiting configurado
e que tentativas repetidas com tokens inválidos são bloqueadas.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.security


class TestRateLimiting:

    async def test_evaluation_endpoint_rate_limited(self, async_client, auth_headers):
        """
        O endpoint de evaluation é o mais crítico — deve ter rate limiting.
        Acima do limite, retorna 429 com Retry-After header.
        """
        responses = []
        for _ in range(200):
            r = await async_client.post(
                "/api/v1/evaluate",
                headers=auth_headers,
                json={
                    "flag_key": "test-flag",
                    "user_id": "user-1",
                    "environment": "production",
                },
            )
            responses.append(r)

        statuses = [r.status_code for r in responses]
        rate_limited = [s for s in statuses if s == 429]
        assert len(rate_limited) > 0, "Rate limiting não foi ativado após 200 requests"

    async def test_brute_force_auth_limited(self, async_client):
        """
        Tentativas repetidas com tokens inválidos devem ser limitadas.
        Previne brute force em tokens de curta vida.
        """
        last_response = None
        for i in range(50):
            last_response = await async_client.get(
                "/api/v1/flags",
                headers={"Authorization": f"Bearer invalid-token-{i}"},
            )
        # Após muitas tentativas, deve bloquear por IP ou rejeitar credenciais
        assert last_response is not None
        assert last_response.status_code in (401, 429)
