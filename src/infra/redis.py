"""
Redis connection pool + pub/sub listener para invalidação de cache.

Invalidação via pub/sub (NÃO polling).
Canal: settings.redis_pubsub_channel (default: feature_flags:invalidate)

Formato da mensagem publicada:
    {"flag_key": "...", "version": N, "action": "update|delete"}
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

import redis.asyncio as aioredis

from src.config import settings

log = logging.getLogger(__name__)

_client: aioredis.Redis | None = None
_pubsub: aioredis.client.PubSub | None = None
_listener_task: asyncio.Task | None = None
_invalidation_handlers: list[Callable[[dict], None]] = []


async def connect() -> None:
    """Inicializa o pool de conexões Redis."""
    global _client
    _client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    # Valida conectividade
    await _client.ping()
    log.info("Conexão com Redis estabelecida")


async def disconnect() -> None:
    """Fecha conexões Redis e cancela o listener de pub/sub."""
    global _client, _pubsub, _listener_task

    if _listener_task and not _listener_task.done():
        _listener_task.cancel()
        try:
            await _listener_task
        except asyncio.CancelledError:
            pass

    if _client:
        await _client.aclose()

    log.info("Conexão com Redis encerrada")


def register_invalidation_handler(callback: Callable[[dict], None]) -> None:
    """Registra um callback para receber mensagens de invalidação."""
    _invalidation_handlers.append(callback)


async def publish_invalidation(flag_key: str, version: int, action: str) -> None:
    """Publica mensagem de invalidação de cache."""
    if _client is None:
        raise RuntimeError("Redis não conectado")
    message = json.dumps({"flag_key": flag_key, "version": version, "action": action})
    await _client.publish(settings.redis_pubsub_channel, message)
    log.debug("Invalidação publicada: flag_key=%s version=%s action=%s", flag_key, version, action)


async def start_listener() -> None:
    """Inicia o loop de escuta do pub/sub em background."""
    global _listener_task
    _listener_task = asyncio.create_task(_listen_for_invalidations())
    log.info("Listener pub/sub iniciado no canal: %s", settings.redis_pubsub_channel)


# Delays de backoff para reconexão ao Redis (segundos)
_RECONNECT_DELAYS = (1, 2, 5, 10, 30)


async def _listen_for_invalidations() -> None:
    """Loop de escuta com reconexão automática em caso de falha de rede."""
    if _client is None:
        raise RuntimeError("Redis não conectado")

    attempt = 0
    while True:
        pubsub = _client.pubsub()
        try:
            await pubsub.subscribe(settings.redis_pubsub_channel)
            log.info("[pub/sub] subscrito ao canal: %s", settings.redis_pubsub_channel)
            attempt = 0  # reconectou com sucesso — reseta o contador

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    for handler in _invalidation_handlers:
                        if asyncio.iscoroutinefunction(handler):
                            asyncio.create_task(handler(data))
                        else:
                            handler(data)
                except (json.JSONDecodeError, Exception) as exc:
                    log.warning("[pub/sub] erro ao processar mensagem: %s", exc)

        except asyncio.CancelledError:
            # Cancelamento intencional (shutdown) — encerra sem retry
            log.info("[pub/sub] listener cancelado")
            return
        except Exception as exc:
            log.error("[pub/sub] conexão perdida: %s", exc)
        finally:
            try:
                await pubsub.unsubscribe(settings.redis_pubsub_channel)
                await pubsub.aclose()
            except Exception:
                pass

        delay = _RECONNECT_DELAYS[min(attempt, len(_RECONNECT_DELAYS) - 1)]
        log.info("[pub/sub] reconectando em %ds (tentativa %d)...", delay, attempt + 1)
        await asyncio.sleep(delay)
        attempt += 1
