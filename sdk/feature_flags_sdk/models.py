"""
Modelos de dados públicos do SDK.

Sem dependências de Pydantic — o SDK é instalável de forma standalone
sem impor dependências ao caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvaluationResult:
    """Resultado de avaliação de uma feature flag."""

    flag_key: str
    value: Any
    reason: str
    environment: str
    flag_version: int = 0


@dataclass
class FlagValue:
    """Valor resumido de uma flag com status de ativação e variante."""

    enabled: bool
    variant: Any = field(default=None)
