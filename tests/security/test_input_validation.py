"""
tests/security/test_input_validation.py — Payloads maliciosos e edge cases.

Testa: campos oversized, JSON profundamente aninhado, e caracteres especiais.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.security


OVERSIZED_PAYLOADS = [
    pytest.param("key", "a" * 10_000, id="key-10k"),
    pytest.param("name", "x" * 100_000, id="name-100k"),
    pytest.param("description", "y" * 1_000_000, id="description-1M"),
]

SPECIAL_CHARS = [
    "<script>alert(1)</script>",
    "javascript:alert(1)",
    "../../../etc/passwd",
    "..\\..\\..\\windows\\system32",
    "\x00\x01\x02",  # null bytes
    "\n\r\t",  # control chars
    "🔥" * 1000,  # unicode flood
    "\u202e",  # unicode right-to-left override
]


class TestInputValidation:

    @pytest.mark.parametrize("field,value", OVERSIZED_PAYLOADS)
    async def test_oversized_fields_rejected(self, async_client, admin_token, field, value):
        """Campos com tamanho excessivo devem ser rejeitados com 422."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        payload = {"key": "valid-key", "name": "Valid Name", "default_value": False}
        payload[field] = value

        response = await async_client.post("/api/v1/flags", headers=headers, json=payload)
        assert response.status_code == 422, (
            f"Campo '{field}' com {len(value)} chars deveria ser rejeitado"
        )

    async def test_deeply_nested_json_rejected(self, async_client, admin_token):
        """
        JSON profundamente aninhado pode causar stack overflow durante parsing.
        Limite de profundidade deve ser validado.
        """
        headers = {"Authorization": f"Bearer {admin_token}"}

        def make_nested(depth: int):
            if depth == 0:
                return "value"
            return {"nested": make_nested(depth - 1)}

        deep_json = make_nested(1000)
        response = await async_client.post(
            "/api/v1/flags",
            headers=headers,
            json={"key": "test", "name": "test", "default_value": deep_json},
        )
        assert response.status_code in (400, 413, 422)
