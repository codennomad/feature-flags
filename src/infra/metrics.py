"""
Todos os métricas Prometheus registradas centralmente.

Importadas pelos módulos que as incrementam (core/evaluation, core/cache, etc.)
NUNCA crie métricas fora deste arquivo.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Avaliação de flags ────────────────────────────────────────────────────────

flag_evaluation_duration_seconds = Histogram(
    "flag_evaluation_duration_seconds",
    "Latência de avaliação de feature flags em segundos",
    labelnames=["flag_key", "environment"],
    buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)

flag_evaluation_total = Counter(
    "flag_evaluation_total",
    "Total de avaliações de feature flags",
    labelnames=["flag_key", "result", "reason"],
)

# ── Cache ─────────────────────────────────────────────────────────────────────

cache_hit_total = Counter(
    "cache_hit_total",
    "Total de hits no cache de flags",
)

cache_miss_total = Counter(
    "cache_miss_total",
    "Total de misses no cache de flags (flag não encontrada)",
)

cache_size_flags = Gauge(
    "cache_size_flags",
    "Número de flags armazenadas no cache local",
)

cache_refresh_duration_seconds = Histogram(
    "cache_refresh_duration_seconds",
    "Duração do warm-up do cache de flags em segundos",
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

# ── Pub/Sub ───────────────────────────────────────────────────────────────────

pubsub_invalidations_total = Counter(
    "pubsub_invalidations_total",
    "Total de mensagens de invalidação recebidas via pub/sub",
    labelnames=["action"],
)

pubsub_lag_seconds = Histogram(
    "pubsub_lag_seconds",
    "Lag entre publicação e processamento da invalidação (segundos)",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)

# ── Webhooks ──────────────────────────────────────────────────────────────────

webhook_dispatch_total = Counter(
    "webhook_dispatch_total",
    "Total de despachos de webhook por resultado",
    labelnames=["result"],
)

webhook_dispatch_duration_seconds = Histogram(
    "webhook_dispatch_duration_seconds",
    "Latência do disparo de webhooks externos (segundos)",
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

# ── DB pool ───────────────────────────────────────────────────────────────────

db_pool_size = Gauge(
    "db_pool_size",
    "Tamanho configurado do pool de conexões com o banco",
)

db_pool_checked_out = Gauge(
    "db_pool_checked_out",
    "Número de conexões atualmente em uso no pool",
)
