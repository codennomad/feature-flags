"""
Hash determinístico para rollout de feature flags.

Algoritmo: mmh3.hash(f"{flag_key}:{user_id}", seed=42) % 10000
Resultado: inteiro 0-9999 (10000 buckets)
Threshold: rollout_percentage * 100

Por que mmh3:
- Distribuição uniforme validada empiricamente
- < 1 microsegundo por hash
- Determinístico entre processos, threads e restarts
- Sem dependência da stdlib hash() que varia por PYTHONHASHSEED

Por que seed=42:
- Seed fixo garante estabilidade entre deploys
- Mudança de seed = redistribuição de todos os usuários (breaking)
- Documentado no ADR 003
"""
import mmh3

_BUCKETS = 10_000
_SEED = 42


def compute_rollout_hash(flag_key: str, user_id: str) -> int:
    """
    Retorna um inteiro no intervalo [0, 9999].

    O usuário está no rollout se:
        compute_rollout_hash(flag_key, user_id) < rollout_percentage * 100

    Exemplos:
        rollout_percentage=50  → threshold=5000  → ~50% dos usuários
        rollout_percentage=100 → threshold=10000 → todos os usuários
        rollout_percentage=0   → threshold=0     → nenhum usuário
    """
    key = f"{flag_key}:{user_id}"
    # mmh3.hash retorna signed 32-bit int — abs() para garantir positivo
    return abs(mmh3.hash(key, seed=_SEED)) % _BUCKETS


def is_in_rollout(flag_key: str, user_id: str, rollout_percentage: int) -> bool:
    """
    Retorna True se o usuário está incluído no rollout.

    rollout_percentage: 0-100 (inteiro)
    """
    if rollout_percentage <= 0:
        return False
    if rollout_percentage >= 100:
        return True
    threshold = rollout_percentage * 100
    return compute_rollout_hash(flag_key, user_id) < threshold
