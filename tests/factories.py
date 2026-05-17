"""
factories.py — fábricas de objetos de teste.

FlagFactory e RuleFactory retornam dicts prontos para uso em testes
e para alimentar o FlagCache via warm_up().
"""
from __future__ import annotations

import uuid
from typing import Any


class RuleFactory:
    """Fábrica de regras de targeting."""

    @classmethod
    def build(cls, **kwargs: Any) -> dict:
        base: dict = {
            "id": str(uuid.uuid4()),
            "name": kwargs.get("name", "Default Rule"),
            "priority": kwargs.get("priority", 1),
            "conditions": kwargs.get(
                "conditions",
                [{"attribute": "country", "operator": "eq", "value": "BR"}],
            ),
            "condition_combinator": kwargs.get("condition_combinator", "AND"),
            "serve": kwargs.get("serve", True),
        }
        # Permite sobrescrever qualquer campo via kwargs
        for key, value in kwargs.items():
            if key not in base:
                base[key] = value
        return base

    @classmethod
    def build_list(cls, n: int = 1, **kwargs: Any) -> list[dict]:
        return [cls.build(**kwargs) for _ in range(n)]


class FlagFactory:
    """Fábrica de flags de feature."""

    @classmethod
    def build(cls, **kwargs: Any) -> dict:
        key = kwargs.get("key", f"flag-{uuid.uuid4().hex[:8]}")
        rules: list[dict] = kwargs.pop("rules", [])
        env_name: str = kwargs.pop("env", "production")

        default_env: dict = {
            "enabled": True,
            "override": None,
            "rollout_percentage": 100,
            "rules": rules,
        }

        environments: dict[str, dict] = kwargs.get(
            "environments",
            {env_name: default_env},
        )

        flag: dict = {
            "id": kwargs.get("id", str(uuid.uuid4())),
            "key": key,
            "name": kwargs.get("name", f"Flag {key}"),
            "description": kwargs.get("description", ""),
            "flag_type": kwargs.get("flag_type", "boolean"),
            "default_value": kwargs.get("default_value", False),
            "environments": environments,
            "version": kwargs.get("version", 1),
        }

        return flag

    @classmethod
    def build_for_http(cls, **kwargs: Any) -> dict:
        """
        Retorna payload compatível com a API REST (POST /flags).
        Exclui campos gerados automaticamente (id, version).
        """
        flag = cls.build(**kwargs)
        return {
            "key": flag["key"],
            "name": flag["name"],
            "description": flag.get("description", ""),
            "flag_type": flag["flag_type"],
            "default_value": flag["default_value"],
            "environments": flag["environments"],
        }
