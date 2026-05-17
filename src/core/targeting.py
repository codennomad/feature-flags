"""
Motor de targeting — avalia regras de targeting por atributo.

Operadores suportados:
    eq, neq, in, not_in, contains, starts_with, gt, gte, lt, lte

Combinadores: AND (todos os conditions devem passar) | OR (qualquer condition)
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Mapa de operadores para funções de avaliação
# Cada função recebe (valor_do_atributo, valor_da_regra) → bool


def _op_eq(attr: Any, val: Any) -> bool:
    return attr == val


def _op_neq(attr: Any, val: Any) -> bool:
    return attr != val


def _op_in(attr: Any, val: Any) -> bool:
    if not isinstance(val, list):
        return False
    return attr in val


def _op_not_in(attr: Any, val: Any) -> bool:
    if not isinstance(val, list):
        return True
    return attr not in val


def _op_contains(attr: Any, val: Any) -> bool:
    if not isinstance(attr, str) or not isinstance(val, str):
        return False
    return val in attr


def _op_starts_with(attr: Any, val: Any) -> bool:
    if not isinstance(attr, str) or not isinstance(val, str):
        return False
    return attr.startswith(val)


def _op_gt(attr: Any, val: Any) -> bool:
    try:
        return float(attr) > float(val)
    except (TypeError, ValueError):
        return False


def _op_gte(attr: Any, val: Any) -> bool:
    try:
        return float(attr) >= float(val)
    except (TypeError, ValueError):
        return False


def _op_lt(attr: Any, val: Any) -> bool:
    try:
        return float(attr) < float(val)
    except (TypeError, ValueError):
        return False


def _op_lte(attr: Any, val: Any) -> bool:
    try:
        return float(attr) <= float(val)
    except (TypeError, ValueError):
        return False


_OPERATORS: dict[str, Any] = {
    "eq": _op_eq,
    "neq": _op_neq,
    "in": _op_in,
    "not_in": _op_not_in,
    "contains": _op_contains,
    "starts_with": _op_starts_with,
    "gt": _op_gt,
    "gte": _op_gte,
    "lt": _op_lt,
    "lte": _op_lte,
}


def evaluate_condition(condition: dict[str, Any], attributes: dict[str, Any]) -> bool:
    """Avalia uma única condição contra os atributos do contexto."""
    attribute = condition.get("attribute", "")
    operator = condition.get("operator", "eq")
    expected_value = condition.get("value")

    actual_value = attributes.get(attribute)
    op_fn = _OPERATORS.get(operator)

    if op_fn is None:
        log.warning("Operador desconhecido: %r — condição falha", operator)
        return False

    try:
        return op_fn(actual_value, expected_value)
    except Exception as exc:
        log.warning("Erro ao avaliar condição %r: %s", condition, exc)
        return False


def evaluate_rule(rule: dict[str, Any], attributes: dict[str, Any]) -> bool:
    """
    Avalia todas as condições de uma regra.
    combinator AND: todas devem passar.
    combinator OR: qualquer uma deve passar.
    """
    conditions = rule.get("conditions", [])
    if not conditions:
        return False

    combinator = rule.get("condition_combinator", "AND").upper()

    if combinator == "AND":
        return all(evaluate_condition(c, attributes) for c in conditions)
    elif combinator == "OR":
        return any(evaluate_condition(c, attributes) for c in conditions)
    else:
        log.warning("Combinator desconhecido: %r — usando AND", combinator)
        return all(evaluate_condition(c, attributes) for c in conditions)


def find_matching_rule(
    rules: list[dict[str, Any]], attributes: dict[str, Any]
) -> dict[str, Any] | None:
    """
    Procura a primeira regra que bate (top-down, baseado em priority).
    Regras DEVEM estar ordenadas por priority (crescente) antes de chamar.
    """
    for rule in rules:
        if evaluate_rule(rule, attributes):
            return rule
    return None
