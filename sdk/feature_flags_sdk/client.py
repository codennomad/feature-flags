"""
Feature Flags SDK — cliente Python thread-safe com cache TTL local.

Interface pública:
    from feature_flags_sdk import FlagClient

    client = FlagClient(api_url="...", api_key="sk-...", cache_ttl=30)
    is_enabled = client.is_enabled("my-flag", user_id="user-123")
    variant = client.get_variant("experiment", user_id="user-123",
                                  attributes={"country": "BR"})

Contrato:
    - NUNCA levanta exceção para o caller
    - Retorna sempre o default em caso de falha
    - Loga warnings (não erros fatais) em caso de problema
    - Cache local com TTL para reduzir latência e dependência da rede
    - Thread-safe (pode ser compartilhado entre threads)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from .cache import TTLCache

log = logging.getLogger(__name__)

_SENTINEL = object()


class FlagClient:
    """
    Cliente de feature flags thread-safe com cache TTL local.

    Em caso de erro na rede ou na API, retorna o valor default silenciosamente
    (warning no log, nunca exception propagada para o caller).
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        cache_ttl: int = 30,
        default_timeout: float = 0.5,
        environment: str = "production",
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._environment = environment
        self._default_timeout = default_timeout
        self._cache: TTLCache = TTLCache(ttl=cache_ttl)
        self._lock = threading.Lock()  # protege criação do client HTTP
        self._http: httpx.Client | None = None

    def _get_http_client(self) -> httpx.Client:
        """Lazy init do cliente HTTP — thread-safe via lock."""
        if self._http is None:
            with self._lock:
                if self._http is None:
                    self._http = httpx.Client(
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        timeout=self._default_timeout,
                    )
        return self._http

    def _evaluate(
        self,
        flag_key: str,
        user_id: str,
        attributes: dict[str, Any] | None = None,
    ) -> Any:
        """
        Avalia a flag via API (com cache).
        Retorna _SENTINEL em caso de erro.
        """
        cache_key = f"{flag_key}:{user_id}:{self._environment}"
        cached = self._cache.get(cache_key)
        if cached is not _SENTINEL:
            return cached

        try:
            client = self._get_http_client()
            resp = client.post(
                f"{self._api_url}/api/v1/evaluate",
                json={
                    "flag_key": flag_key,
                    "user_id": user_id,
                    "environment": self._environment,
                    "attributes": attributes or {},
                },
            )
            resp.raise_for_status()
            result = resp.json()
            value = result.get("value")
            self._cache.set(cache_key, value)
            return value

        except httpx.TimeoutException:
            log.warning("Timeout ao avaliar flag '%s' para user '%s'", flag_key, user_id)
            return _SENTINEL
        except httpx.HTTPStatusError as exc:
            log.warning(
                "Erro HTTP %d ao avaliar flag '%s': %s",
                exc.response.status_code, flag_key, exc.response.text[:200],
            )
            return _SENTINEL
        except Exception as exc:
            log.warning("Erro inesperado ao avaliar flag '%s': %s", flag_key, exc)
            return _SENTINEL

    def is_enabled(
        self,
        flag_key: str,
        user_id: str,
        default: bool = False,
        attributes: dict[str, Any] | None = None,
    ) -> bool:
        """
        Retorna True se a flag está ativa para o usuário.
        Nunca levanta exceção — retorna `default` em caso de falha.
        """
        value = self._evaluate(flag_key, user_id, attributes)
        if value is _SENTINEL:
            return default
        try:
            return bool(value)
        except Exception:
            return default

    def get_variant(
        self,
        flag_key: str,
        user_id: str,
        default: Any = None,
        attributes: dict[str, Any] | None = None,
    ) -> Any:
        """
        Retorna o valor da flag (qualquer tipo) para o usuário.
        Nunca levanta exceção — retorna `default` em caso de falha.
        """
        value = self._evaluate(flag_key, user_id, attributes)
        if value is _SENTINEL:
            return default
        return value

    def close(self) -> None:
        """Fecha o cliente HTTP. Chame ao encerrar a aplicação."""
        if self._http is not None:
            self._http.close()
            self._http = None

    def __enter__(self) -> "FlagClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
