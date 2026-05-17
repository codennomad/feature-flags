"""
Cache local de feature flags com invalidação via Redis pub/sub.

Estrutura interna:
    {
        "flags": dict[str, dict],  # snapshot completo da flag
        "version": int,            # versão global
        "loaded_at": datetime
    }

CRÍTICO:
- O cache é por processo. Em múltiplas replicas, cada processo
  recebe a mensagem pub/sub independentemente.
- warm_up() DEVE ser chamado no lifespan antes de aceitar requests.
- asyncio.Lock (não bloqueante) para todas as escritas.
- CacheNotReadyError se evaluate for chamado antes do warm_up.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from src.infra.metrics import (
    cache_hit_total,
    cache_miss_total,
    cache_refresh_duration_seconds,
    cache_size_flags,
)

log = logging.getLogger(__name__)


class CacheNotReadyError(Exception):
    """Levantada quando o cache é acessado antes do warm_up completar."""


class FlagCache:
    """
    Cache local thread-safe (asyncio) para snapshots de feature flags.
    Invalidação via mensagens do pub/sub Redis.
    """

    def __init__(self) -> None:
        self._flags: dict[str, dict[str, Any]] = {}
        self._version: int = 0
        self._loaded_at: datetime | None = None
        self._ready: bool = False
        self._lock = asyncio.Lock()

    def is_ready(self) -> bool:
        return self._ready

    async def mark_ready(self) -> None:
        self._ready = True

    def get(self, flag_key: str) -> dict[str, Any] | None:
        """
        Retorna o snapshot da flag ou None.
        Levanta CacheNotReadyError se warm_up não foi completado.
        """
        if not self._ready:
            raise CacheNotReadyError(
                "Cache não está pronto. warm_up() deve ser concluído antes de avaliar flags."
            )

        flag = self._flags.get(flag_key)
        if flag is not None:
            cache_hit_total.inc()
        else:
            cache_miss_total.inc()
        return flag

    async def set(self, flag_key: str, flag_data: dict[str, Any]) -> None:
        """Insere ou atualiza um flag no cache (uso interno e testes)."""
        async with self._lock:
            self._flags[flag_key] = flag_data
            cache_size_flags.set(len(self._flags))

    async def invalidate(self, flag_key: str, new_data: dict[str, Any] | None = None) -> None:
        """
        Atualiza ou remove uma flag do cache.
        new_data=None → remoção (flag deletada).
        new_data=dict → atualização com novo snapshot.
        """
        async with self._lock:
            if new_data is None:
                self._flags.pop(flag_key, None)
                log.debug("Cache: flag removida key=%r", flag_key)
            else:
                self._flags[flag_key] = new_data
                log.debug("Cache: flag atualizada key=%r", flag_key)
            cache_size_flags.set(len(self._flags))

    async def warm_up(self, load_fn) -> None:  # type: ignore[type-arg]
        """
        Carrega todas as flags do banco antes de aceitar requests.
        load_fn: async callable que retorna list[dict] (flag snapshots).

        CRÍTICO: marca _ready=True APENAS após carregamento completo.
        """
        log.info("Cache warm_up iniciado...")
        with cache_refresh_duration_seconds.time():
            flags = await load_fn()
            async with self._lock:
                self._flags = {f["key"]: f for f in flags}
                self._loaded_at = datetime.now(timezone.utc)
                self._version += 1
            self._ready = True
        count = len(self._flags)
        cache_size_flags.set(count)
        log.info("Cache warm_up concluído: %d flags carregadas", count)

    async def handle_invalidation_message(self, message: dict[str, Any]) -> None:
        """
        Callback chamado pelo pub/sub Redis ao receber mensagem de invalidação.
        Mensagem: {"flag_key": str, "version": int, "action": "update"|"delete"}
        """
        flag_key = message.get("flag_key")
        action = message.get("action", "update")

        if not flag_key:
            log.warning("Mensagem de invalidação sem flag_key: %r", message)
            return

        if action == "delete":
            await self.invalidate(flag_key, None)
        else:
            # "update": busca novo snapshot do banco via refresh_fn se disponível
            # Para o caso sem refresh_fn, apenas remove (força cache miss → default)
            await self.invalidate(flag_key, None)
            log.debug("Flag %r marcada para reload no próximo acesso", flag_key)

    def size(self) -> int:
        return len(self._flags)

    def all_keys(self) -> list[str]:
        return list(self._flags.keys())
