"""
AuditLog SQLAlchemy model — IMUTÁVEL por design.
Não existe endpoint de UPDATE ou DELETE para esta tabela.
Todo endpoint que modifica uma flag DEVE inserir uma entrada aqui
na mesma transação (jamais fora dela).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infra.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    flag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("flags.id", ondelete="RESTRICT"),  # RESTRICT: protege histórico
        nullable=False,
        index=True,
    )
    # Ações possíveis: created, updated, enabled, disabled, rule_added,
    # rule_updated, rule_deleted, deleted
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    # Diff: {"before": {...}, "after": {...}}
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Metadados opcionais: IP, user_agent, request_id
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # PROPOSITALMENTE sem updated_at — auditoria não tem update

    def __repr__(self) -> str:
        return f"<AuditLog flag_id={self.flag_id} action={self.action!r}>"
