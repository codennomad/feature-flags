"""
tests/security/test_injection.py — SQL Injection, NoSQL Injection, SSTI.

Payloads centralizados em tests/utils/attack_payloads.py para manutenção.
Cada teste documenta que o input adversarial nunca chega ao banco raw.
"""
from __future__ import annotations

import pytest

from tests.utils.attack_payloads import (
    NOSQL_INJECTION_PAYLOADS,
    SQL_INJECTION_PAYLOADS,
    SSTI_PAYLOADS,
)

pytestmark = pytest.mark.security


class TestSQLInjection:

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    async def test_flag_key_sql_injection(self, async_client, auth_headers, payload):
        """flag_key é usado em queries — deve rejeitar payloads SQL."""
        response = await async_client.get(
            f"/api/v1/flags/{payload}",
            headers=auth_headers,
        )
        # Nunca deve retornar 500 (indica erro SQL não tratado)
        # Deve retornar 404 (não encontrado) ou 422 (validação)
        assert response.status_code in (404, 422), (
            f"Payload SQL retornou {response.status_code}: {payload!r}"
        )
        # Nunca expor detalhes do banco no response
        body = response.text.lower()
        for leak_word in ["syntax error", "postgresql", "sqlalchemy", "column", "relation"]:
            assert leak_word not in body, (
                f"Detalhe de banco vazou no response: {leak_word!r}"
            )

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    async def test_evaluation_user_id_injection(self, async_client, auth_headers, payload):
        """user_id no payload de evaluation deve ser tratado como string opaca."""
        response = await async_client.post(
            "/api/v1/evaluate",
            headers=auth_headers,
            json={
                "flag_key": "test-flag",
                "user_id": payload,
                "environment": "production",
            },
        )
        # user_id nunca vai direto ao banco, mas o teste documenta isso
        assert response.status_code in (200, 404, 422)
        assert "syntax error" not in response.text.lower()

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    async def test_search_parameter_injection(self, async_client, auth_headers, payload):
        """Parâmetros de busca na listagem de flags."""
        response = await async_client.get(
            f"/api/v1/flags?search={payload}",
            headers=auth_headers,
        )
        assert response.status_code in (200, 422)
        assert "syntax error" not in response.text.lower()
        # Não deve retornar mais flags do que o normal
        if response.status_code == 200:
            data = response.json()
            assert len(data.get("items", [])) <= 100  # limite razoável
