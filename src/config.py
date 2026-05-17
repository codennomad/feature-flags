"""
Configuração centralizada via Pydantic v2 BaseSettings.
Todas as variáveis de ambiente são lidas aqui — NUNCA espalhadas pelo código.
"""
from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

_INSECURE_SECRET_PLACEHOLDER = "CHANGE_ME_IN_PRODUCTION_THIS_IS_NOT_SECURE"


class Settings(BaseSettings):
    # ── Banco de dados ────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/feature_flags",
        description="URL de conexão assíncrona com PostgreSQL (asyncpg)",
    )

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="URL de conexão com Redis",
    )
    redis_pubsub_channel: str = Field(
        default="feature_flags:invalidate",
        description="Canal Redis para invalidação de cache via pub/sub",
    )

    # ── JWT ───────────────────────────────────────────────────────────────────
    # Lido da env var SECRET_KEY. A aplicação recusa inicializar em
    # ENVIRONMENT=production com o valor placeholder.
    secret_key: str = Field(
        default=_INSECURE_SECRET_PLACEHOLDER,
        description="Chave secreta para assinar JWTs (HS256). Defina SECRET_KEY.",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="Algoritmo JWT — NUNCA use 'none'",
    )
    access_token_expire_minutes: int = Field(default=60)

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_limit_evaluation: str = Field(
        default="1000/minute",
        description="Limite de requisições no endpoint de avaliação",
    )

    # ── Aplicação ─────────────────────────────────────────────────────────────
    app_name: str = Field(default="Feature Flags API")
    app_version: str = Field(default="1.0.0")
    debug: bool = Field(default=False)
    # Padrão "development": em produção definir explicitamente ENVIRONMENT=production.
    environment: str = Field(default="development")

    # ── CORS / Trusted Hosts ──────────────────────────────────────────────────
    # Defina ALLOWED_HOSTS como lista separada por vírgula, ex:
    # ALLOWED_HOSTS=api.meudominio.com,api-interno.meudominio.com
    allowed_hosts: list[str] = Field(
        default=["localhost", "127.0.0.1"],
        description="Hosts permitidos pelo TrustedHostMiddleware (ALLOWED_HOSTS).",
    )
    # Defina CORS_ORIGINS como lista separada por vírgula, ex:
    # CORS_ORIGINS=https://app.meudominio.com,https://admin.meudominio.com
    cors_origins: list[str] = Field(
        default=[],
        description="Origens permitidas pelo CORS (CORS_ORIGINS). Vazio = sem origens em prod.",
    )

    # ── SQLAlchemy pool ───────────────────────────────────────────────────────
    db_pool_size: int = Field(default=20)
    db_max_overflow: int = Field(default=10)

    # ── Sentry ───────────────────────────────────────────────────────────────
    # Defina SENTRY_DSN para ativar error tracking e tracing.
    # Deixe vazio para desativar (ex: em desenvolvimento).
    sentry_dsn: str = Field(
        default="",
        description="DSN do Sentry para error tracking/tracing (SENTRY_DSN).",
    )
    sentry_traces_sample_rate: float = Field(
        default=0.1,
        description="Fração de transações amostradas pelo Sentry (0.0–1.0).",
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def _reject_insecure_secret_in_production(self) -> "Settings":
        """Impede a aplicação de subir em produção com a chave JWT placeholder."""
        if (
            self.environment == "production"
            and self.secret_key == _INSECURE_SECRET_PLACEHOLDER
        ):
            raise ValueError(
                "SECRET_KEY não pode ser o valor placeholder em ENVIRONMENT=production. "
                "Defina a variável de ambiente SECRET_KEY com um segredo seguro "
                "(mínimo de 32 bytes de entropia, ex: openssl rand -hex 32)."
            )
        return self


settings = Settings()
