"""
tests/utils/assertions.py — Assertivas customizadas reutilizáveis.
"""
from __future__ import annotations

from typing import Any


def assert_no_sensitive_data(text: str) -> None:
    """Garante que o texto não expõe informações internas do servidor."""
    sensitive_patterns = [
        "Traceback",
        'File "',
        "sqlalchemy",
        "asyncpg",
        "/src/",
        "DETAIL:",
        "HINT:",
    ]
    for pattern in sensitive_patterns:
        assert pattern not in text, (
            f"Dado sensível '{pattern}' encontrado no response"
        )


def assert_valid_evaluation_result(result: dict[str, Any]) -> None:
    """Garante que um resultado de avaliação tem todos os campos obrigatórios."""
    required_fields = ["flag_key", "value", "reason", "environment"]
    for field in required_fields:
        assert field in result, f"Campo obrigatório '{field}' ausente no resultado"
    assert isinstance(result["value"], (bool, str, int, float, type(None)))
    assert result["reason"] in {
        "OVERRIDE",
        "TARGETING_MATCH",
        "ROLLOUT",
        "DEFAULT",
        "FLAG_DISABLED",
        "FLAG_NOT_FOUND",
    }, f"Razão desconhecida: {result['reason']!r}"
