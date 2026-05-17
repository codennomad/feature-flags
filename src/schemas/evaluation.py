"""
Pydantic v2 schemas para EvaluationContext e EvaluationResult.
EvaluationContext é o input do motor de avaliação.
EvaluationResult é o output — nunca levanta exceção ao caller.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class EvaluationContext(BaseModel):
    """
    Contexto necessário para avaliar uma flag.
    user_id é obrigatório para rollout determinístico.
    attributes é usado para matching de targeting rules.
    """

    user_id: str = Field(..., min_length=1, max_length=512)
    environment: str = Field(..., min_length=1, max_length=100)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        # user_id é tratado como string opaca — nunca vai direto ao banco
        return v.strip()


class EvaluationResult(BaseModel):
    """
    Resultado de uma avaliação.
    reason documenta por que aquele valor foi escolhido.
    Razões possíveis: OVERRIDE, TARGETING_MATCH, ROLLOUT, DEFAULT, FLAG_DISABLED
    """

    flag_key: str
    value: Any
    reason: str
    environment: str
    flag_version: int = 0


class BatchEvaluationRequest(BaseModel):
    flags: list[str] = Field(..., min_length=1, max_length=50)
    user_id: str = Field(..., min_length=1, max_length=512)
    environment: str = Field(..., min_length=1, max_length=100)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("flags")
    @classmethod
    def validate_flags(cls, v: list[str]) -> list[str]:
        if len(v) > 50:
            raise ValueError("Máximo de 50 flags por batch")
        return v

    @property
    def context(self) -> "EvaluationContext":
        return EvaluationContext(
            user_id=self.user_id,
            environment=self.environment,
            attributes=self.attributes,
        )


class SingleEvaluationRequest(BaseModel):
    flag_key: str = Field(..., min_length=1, max_length=255)
    user_id: str = Field(..., min_length=1, max_length=512)
    environment: str = Field(..., min_length=1, max_length=100)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def context(self) -> "EvaluationContext":
        return EvaluationContext(
            user_id=self.user_id,
            environment=self.environment,
            attributes=self.attributes,
        )


class BatchEvaluationResponse(BaseModel):
    results: list[EvaluationResult]
