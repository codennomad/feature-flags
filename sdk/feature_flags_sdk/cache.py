"""
Cache TTL local para o SDK — thread-safe.

Chave → valor com timestamp de inserção.
Entradas expiram após `ttl` segundos.
Implementação simples com dict + lock (sem dependências externas).
"""
from __future__ import annotations

import threading
import time
from typing import Any

_SENTINEL = object()


class TTLCache:
    """Cache chave/valor com TTL. Thread-safe via RLock."""

    def __init__(self, ttl: int = 30) -> None:
        self._ttl = ttl
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> Any:
        """Retorna o valor ou _SENTINEL se expirado/não encontrado."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return _SENTINEL
            value, inserted_at = entry
            if time.monotonic() - inserted_at > self._ttl:
                del self._store[key]
                return _SENTINEL
            return value

    def set(self, key: str, value: Any) -> None:
        """Armazena valor com timestamp atual."""
        with self._lock:
            self._store[key] = (value, time.monotonic())

    def invalidate(self, key: str) -> None:
        """Remove uma entrada do cache."""
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        """Limpa todo o cache."""
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)
