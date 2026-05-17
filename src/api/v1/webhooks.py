"""
Gerenciamento de webhooks: registro, listagem, deleção e despacho com retry.

Backoff exponencial: 3 tentativas; delays 1s → 5s → 25s.
Timeout por request: 5s.
Despacho assíncrono com asyncio.create_task (não-bloqueante).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac
import json
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUserDep, SessionDep, require_role
from src.infra.metrics import webhook_dispatch_total
from src.models.webhook import Webhook, WebhookDelivery
from src.schemas.flag import WebhookCreate, WebhookResponse

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Política de retry: 3 tentativas, delays exponenciais (segundos)
_RETRY_DELAYS = (1, 5, 25)
_HTTP_TIMEOUT = 5.0  # segundos


def _hmac_signature(secret: str, payload_bytes: bytes) -> str:
    """Computa X-Hub-Signature-256 para o payload serializado."""
    digest = _hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _dispatch_with_retry(
    webhook_id: uuid.UUID,
    url: str,
    event: str,
    payload: dict,
    session_factory,
    secret: str | None = None,
) -> None:
    """
    Tenta entregar o evento ao webhook com 3 tentativas e backoff exponencial.
    Assina o payload com HMAC-SHA256 quando o webhook tem secret configurado.
    Registra cada tentativa em webhook_deliveries.
    Executa em background (asyncio.create_task).
    """
    success = False
    last_error: str | None = None

    # Serializa o payload uma única vez para garantir a mesma assinatura em todas as tentativas
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if secret:
        headers["X-Hub-Signature-256"] = _hmac_signature(secret, payload_bytes)

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
            try:
                resp = await client.post(url, content=payload_bytes, headers=headers)
                success = resp.is_success
                last_error = None if success else f"HTTP {resp.status_code}"
            except Exception as exc:
                success = False
                last_error = str(exc)[:2000]

            # Registra tentativa no banco
            async with session_factory() as db_session:
                async with db_session.begin():
                    delivery = WebhookDelivery(
                        id=uuid.uuid4(),
                        webhook_id=webhook_id,
                        event=event,
                        payload=payload,
                        status="success" if success else "failed",
                        attempts=attempt,
                        last_error=last_error,
                        created_at=datetime.now(timezone.utc),
                    )
                    db_session.add(delivery)

            webhook_dispatch_total.labels(
                result="success" if success else "failure"
            ).inc()

            if success:
                return

            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(delay)


def schedule_webhook_dispatch(
    webhook_id: uuid.UUID,
    url: str,
    event: str,
    payload: dict,
    session_factory,
    secret: str | None = None,
) -> None:
    """Dispara tarefa em background — não-bloqueante."""
    asyncio.create_task(
        _dispatch_with_retry(webhook_id, url, event, payload, session_factory, secret=secret)
    )


# ─── CRUD ─────────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("admin", "editor"))],
)
async def register_webhook(
    data: WebhookCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> WebhookResponse:
    webhook = Webhook(
        id=uuid.uuid4(),
        url=str(data.url),
        secret=data.secret,
        events=data.events,
        active=True,
    )
    session.add(webhook)
    await session.flush()
    await session.refresh(webhook)
    return WebhookResponse.model_validate(webhook)


@router.get(
    "",
    response_model=list[WebhookResponse],
    dependencies=[Depends(require_role("admin", "editor"))],
)
async def list_webhooks(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> list[WebhookResponse]:
    result = await session.execute(select(Webhook).where(Webhook.active.is_(True)))
    return [WebhookResponse.model_validate(w) for w in result.scalars().all()]


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role("admin"))],
)
async def delete_webhook(
    webhook_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> None:
    result = await session.execute(
        select(Webhook).where(Webhook.id == webhook_id)
    )
    webhook = result.scalar_one_or_none()
    if webhook is None:
        raise HTTPException(status_code=404, detail="Webhook não encontrado")
    # Soft delete
    webhook.active = False

