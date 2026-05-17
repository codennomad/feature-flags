"""
EnvironmentConfig — configuração de uma flag por ambiente.
Armazenado como JSONB dentro da coluna `environments` da Flag.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TargetingRule:
    id: str
    name: str
    priority: int
    conditions: list[dict[str, Any]]
    condition_combinator: str  # "AND" | "OR"
    serve: Any  # valor servido quando a regra bate

    @classmethod
    def from_dict(cls, data: dict) -> "TargetingRule":
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            priority=data.get("priority", 0),
            conditions=data.get("conditions", []),
            condition_combinator=data.get("condition_combinator", "AND"),
            serve=data.get("serve"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "priority": self.priority,
            "conditions": self.conditions,
            "condition_combinator": self.condition_combinator,
            "serve": self.serve,
        }


@dataclass
class EnvironmentConfig:
    enabled: bool = False
    override: Any | None = None  # None = sem override; qualquer valor = force-serve
    rollout_percentage: int = 0   # 0-100
    rules: list[TargetingRule] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "EnvironmentConfig":
        rules = [TargetingRule.from_dict(r) for r in data.get("rules", [])]
        rules.sort(key=lambda r: r.priority)
        return cls(
            enabled=data.get("enabled", False),
            override=data.get("override"),
            rollout_percentage=data.get("rollout_percentage", 0),
            rules=rules,
        )

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "override": self.override,
            "rollout_percentage": self.rollout_percentage,
            "rules": [r.to_dict() for r in self.rules],
        }
