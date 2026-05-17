"""
Pydantic v2 schemas para Flag.
Validações de segurança: tamanho máximo em todos os campos de texto.
key é slugified e imutável após criação.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Targeting rules ──────────────────────────────────────────────────────────

VALID_OPERATORS = frozenset(
    ["eq", "neq", "in", "not_in", "contains", "starts_with", "gt", "gte", "lt", "lte"]
)
VALID_COMBINATORS = frozenset(["AND", "OR"])
VALID_FLAG_TYPES = frozenset(["boolean", "string", "number", "json"])


class ConditionSchema(BaseModel):
    attribute: str = Field(..., min_length=1, max_length=100)
    operator: str
    value: Any

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        if v not in VALID_OPERATORS:
            raise ValueError(f"Operador inválido: {v!r}. Válidos: {VALID_OPERATORS}")
        return v


class RuleSchema(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., min_length=1, max_length=255)
    priority: int = Field(..., ge=0, le=9999)
    conditions: list[ConditionSchema] = Field(..., min_length=1)
    condition_combinator: str = Field(default="AND")
    serve: Any  # valor a servir quando a regra bate

    @field_validator("condition_combinator")
    @classmethod
    def validate_combinator(cls, v: str) -> str:
        if v not in VALID_COMBINATORS:
            raise ValueError(f"Combinator inválido: {v!r}. Válidos: AND, OR")
        return v


class EnvironmentConfigSchema(BaseModel):
    enabled: bool = False
    override: Any | None = None
    rollout_percentage: int = Field(default=0, ge=0, le=100)
    rules: list[RuleSchema] = Field(default_factory=list)


# ─── Flag CRUD schemas ────────────────────────────────────────────────────────

class FlagCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)
    flag_type: str = Field(default="boolean")
    default_value: Any
    environments: dict[str, EnvironmentConfigSchema] = Field(default_factory=dict)

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        # Slug: apenas letras minúsculas, números e hífens
        slug = re.sub(r"[^a-z0-9-]", "", v.lower().replace("_", "-"))
        if not slug:
            raise ValueError("key deve conter apenas letras, números e hífens")
        return slug

    @field_validator("flag_type")
    @classmethod
    def validate_flag_type(cls, v: str) -> str:
        if v not in VALID_FLAG_TYPES:
            raise ValueError(f"flag_type inválido: {v!r}. Válidos: {VALID_FLAG_TYPES}")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name não pode ser vazio")
        return v


class FlagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)
    default_value: Any | None = None
    environments: dict[str, EnvironmentConfigSchema] | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "FlagUpdate":
        if all(v is None for v in [self.name, self.description, self.default_value, self.environments]):
            raise ValueError("Ao menos um campo deve ser fornecido para atualização")
        return self


class FlagResponse(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    flag_type: str
    default_value: Any
    environments: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    created_by: str
    version: int

    model_config = {"from_attributes": True}


class FlagListResponse(BaseModel):
    items: list[FlagResponse]
    total: int
    page: int
    page_size: int


# ─── Audit log schemas ────────────────────────────────────────────────────────

class AuditLogResponse(BaseModel):
    id: uuid.UUID
    flag_id: uuid.UUID
    action: str
    actor: str
    changes: dict
    metadata_: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int


# ─── Webhook schemas ──────────────────────────────────────────────────────────

class WebhookCreate(BaseModel):
    url: str = Field(..., min_length=10, max_length=2048)
    events: list[str] = Field(..., min_length=1)
    secret: str | None = Field(default=None, max_length=512)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("https://", "http://")):
            raise ValueError("URL do webhook deve começar com http:// ou https://")
        return v


class WebhookResponse(BaseModel):
    id: uuid.UUID
    url: str
    events: list[str]
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
