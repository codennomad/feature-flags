"""
Flag SQLAlchemy model.
key é slugified e IMUTÁVEL após criação.
environments é JSONB: {"production": {...}, "staging": {...}}
version é incrementado a cada mudança para invalidação de cache.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infra.database import Base


class Flag(Base):
    __tablename__ = "flags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    flag_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="boolean"
    )
    # Valor padrão quando nenhuma regra bate — qualquer tipo JSON
    default_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Dict de ambientes: {"production": {enabled, override, rollout_percentage, rules}}
    environments: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    # Incrementado a cada mudança — usado para invalidação de cache
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    def __repr__(self) -> str:
        return f"<Flag key={self.key!r} version={self.version}>"
