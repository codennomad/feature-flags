"""
tests/security/test_sensitive_data.py — Vazamento de dados em respostas e logs.

Verifica que stack traces, tokens JWT e credenciais não aparecem em respostas
de erro nem em logs de produção.
"""
from __future__ import annotations

import logging

import pytest

from tests.conftest import generate_valid_jwt

pytestmark = pytest.mark.security


class TestSensitiveDataLeakage:

    async def test_error_responses_do_not_expose_stack_traces(
        self, async_client, admin_token
    ):
        """
        Em produção, erros 500 não devem expor stack traces ou detalhes internos.
        """
        headers = {"Authorization": f"Bearer {admin_token}"}
        # Acessa uma flag com ID que pode causar erro interno
        response = await async_client.get(
            "/api/v1/flags/flag-that-will-cause-db-error",
            headers=headers,
        )
        body = response.text
        # Nunca expor informações internas do servidor
        for sensitive in [
            "Traceback",
            'File "',
            "line ",
            "sqlalchemy",
            "asyncpg",
            "/src/",
        ]:
            assert sensitive not in body, (
                f"Informação sensível '{sensitive}' exposta no response de erro"
            )

    async def test_api_keys_not_logged(self, caplog, async_client):
        """
        Tokens JWT no header Authorization não devem aparecer em logs.
        Crítico para compliance (PCI-DSS, SOC2).
        """
        real_token = generate_valid_jwt(sub="user-123")
        with caplog.at_level(logging.DEBUG):
            await async_client.get(
                "/api/v1/flags",
                headers={"Authorization": f"Bearer {real_token}"},
            )
        # O token completo não deve aparecer em nenhum log
        for record in caplog.records:
            assert real_token not in record.message, (
                f"Token JWT exposto no log: {record.message[:100]}"
            )
