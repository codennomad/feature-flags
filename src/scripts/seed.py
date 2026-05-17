"""
src/scripts/seed.py — Popula o banco com flags e regras de exemplo.

Uso:
    python -m src.scripts.seed
    # ou via Makefile:
    make seed
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select

from src.infra.database import AsyncSessionLocal, connect, disconnect
from src.models.flag import Flag, FlagEnvironmentConfig, FlagRule

log = logging.getLogger(__name__)

# ── Dados de seed ──────────────────────────────────────────────────────────────

SEED_FLAGS = [
    {
        "key": "checkout-v2",
        "name": "Checkout V2",
        "description": "Nova experiência de checkout com one-click payment",
        "flag_type": "boolean",
        "default_value": False,
        "environments": {
            "production": {
                "enabled": True,
                "override": None,
                "rollout_percentage": 10,  # 10% dos usuários em produção
                "rules": [
                    {
                        "name": "Enterprise always on",
                        "priority": 1,
                        "conditions": [
                            {"attribute": "plan", "operator": "eq", "value": "enterprise"}
                        ],
                        "condition_combinator": "AND",
                        "serve": True,
                    }
                ],
            },
            "staging": {
                "enabled": True,
                "override": True,  # 100% em staging para testes
                "rollout_percentage": 100,
                "rules": [],
            },
        },
    },
    {
        "key": "new-pricing-page",
        "name": "Nova Página de Preços",
        "description": "Redesign da página de pricing com comparativo de planos",
        "flag_type": "boolean",
        "default_value": False,
        "environments": {
            "production": {
                "enabled": True,
                "override": None,
                "rollout_percentage": 50,
                "rules": [
                    {
                        "name": "BR users only",
                        "priority": 1,
                        "conditions": [
                            {"attribute": "country", "operator": "eq", "value": "BR"}
                        ],
                        "condition_combinator": "AND",
                        "serve": True,
                    }
                ],
            },
        },
    },
    {
        "key": "dark-mode",
        "name": "Dark Mode",
        "description": "Tema escuro para a interface",
        "flag_type": "boolean",
        "default_value": False,
        "environments": {
            "production": {
                "enabled": True,
                "override": None,
                "rollout_percentage": 100,  # disponível para todos
                "rules": [],
            },
        },
    },
    {
        "key": "api-rate-limit-tier",
        "name": "API Rate Limit Tier",
        "description": "Tier de rate limiting por plano (string flag)",
        "flag_type": "string",
        "default_value": "standard",
        "environments": {
            "production": {
                "enabled": True,
                "override": None,
                "rollout_percentage": 0,
                "rules": [
                    {
                        "name": "Enterprise — unlimited",
                        "priority": 1,
                        "conditions": [
                            {"attribute": "plan", "operator": "eq", "value": "enterprise"}
                        ],
                        "condition_combinator": "AND",
                        "serve": "unlimited",
                    },
                    {
                        "name": "Pro — high",
                        "priority": 2,
                        "conditions": [
                            {"attribute": "plan", "operator": "eq", "value": "pro"}
                        ],
                        "condition_combinator": "AND",
                        "serve": "high",
                    },
                ],
            },
        },
    },
]


# ── Seed function ─────────────────────────────────────────────────────────────


async def seed() -> None:
    """Insere flags de exemplo se não existirem (idempotente por key)."""
    await connect()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            for flag_data in SEED_FLAGS:
                # Verifica se já existe
                existing = await session.scalar(
                    select(Flag).where(Flag.key == flag_data["key"])
                )
                if existing:
                    log.info("Flag '%s' já existe — pulando", flag_data["key"])
                    continue

                flag = Flag(
                    id=uuid.uuid4(),
                    key=flag_data["key"],
                    name=flag_data["name"],
                    description=flag_data.get("description"),
                    flag_type=flag_data["flag_type"],
                    default_value=flag_data["default_value"],
                    environments=flag_data["environments"],
                    version=1,
                    created_by="seed-script",
                )
                session.add(flag)
                log.info("Flag '%s' criada", flag_data["key"])

    log.info("Seed concluído: %d flags processadas", len(SEED_FLAGS))
    await disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(seed())
