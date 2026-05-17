# ADR 003: Hash determinístico com mmh3 para rollout gradual

**Data:** 2024-01-01  
**Status:** Aceito  
**Autores:** @codennomad

---

## Contexto

O sistema de gradual rollout precisa decidir, de forma determinística e estável, se um usuário específico está incluído em um percentual de uma flag. A função de hash deve satisfazer:

1. **Determinismo:** mesmo input sempre produz mesmo output entre processos, deploys, linguagens
2. **Uniformidade:** 50% de rollout deve incluir ~50% dos usuários, provável estatisticamente
3. **Independência entre flags:** ativar "flag A" para user-1 não deve implicar "flag B" ativada para o mesmo user-1
4. **Performance:** < 1µs por hash (não pode degradar o p99 de avaliação)

---

## Opções avaliadas

### Opção 1 — Python built-in `hash()`
```python
hash(f"{flag_key}:{user_id}") % 10000
```

**Descartado:** `PYTHONHASHSEED` é randomizado por processo em Python 3.3+. Um usuário em rollout em um processo pode estar fora do rollout em outro. Fatal para sistemas distribuídos.

### Opção 2 — MD5 / SHA-256 (stdlib `hashlib`)
```python
int(hashlib.md5(key.encode()).hexdigest(), 16) % 10000
```

**Prós:** Determinístico e portável  
**Contras:** ~300-500ns (MD5) a ~1000ns (SHA-256) — 10-50x mais lento que mmh3, criptograficamente inseguro (MD5), overhead de bytes→int

### Opção 3 — FNV-1a (implementação manual)
**Prós:** Muito rápido, determinístico  
**Contras:** Distribuição não-uniforme em strings longas, sem biblioteca padrão Python, manutenção da implementação

### Opção 4 — mmh3 (MurmurHash3) com seed fixo (decisão tomada)
```python
abs(mmh3.hash(f"{flag_key}:{user_id}", seed=42)) % 10_000
```

**Prós:** ~50-80ns por hash, distribuição uniforme comprovada (usado pelo Cassandra, Redis, etc.), seed fixo = estabilidade entre deploys, binding C nativo (sem GIL overhead significativo)  
**Contras:** Dependência externa (mas madura e amplamente usada)

---

## Decisão

**mmh3 com seed=42** e 10.000 buckets.

### Por que 10.000 buckets?
- Permite representar percentuais fracionados (0.5% = threshold 50 de 10.000)
- Granularidade suficiente para qualquer caso de uso prático
- `mmh3.hash()` retorna int 32-bit — módulo 10.000 é trivial

### Por que seed=42?
- Seed fixo e documentado garante que a distribuição é estável entre:
  - Deploys, restarts, scaling horizontal
  - Linguagens diferentes (Python SDK, futuros SDKs)
- **CRÍTICO:** mudar o seed redistribui TODOS os usuários em TODOS os rollouts — é uma breaking change

### Fórmula canônica
```python
key = f"{flag_key}:{user_id}"
bucket = abs(mmh3.hash(key, seed=42)) % 10_000
in_rollout = bucket < (rollout_percentage * 100)
```

### Propriedade de independência entre flags
A combinação `flag_key:user_id` garante que flags diferentes produzem hashes independentes para o mesmo usuário. Teste de correlação entre "flag-a" e "flag-b" com 10.000 usuários confirma correlação de ~50% (esperado para variáveis independentes).

---

## Consequências

**Positivas:**
- Avaliação de rollout em < 100ns (não aparece no p99 de 1ms)
- Estável cross-process, cross-restart, cross-language (seed documentado)
- Distribuição uniforme validada por testes de propriedade (test_hashing.py)

**Negativas:**
- Dependência de `mmh3` (C extension) — não funciona em ambientes sem compilador
- Seed=42 é um contrato implícito — documentado aqui para SDKs futuros

---

## Quando revisar esta decisão

- Se for necessário suporte a rollout por atributos de usuário (hoje é só `user_id`)
- Se `mmh3` ficar abandonado ou com CVEs
- Se precisarmos de rollout > 100% granularidade (e.g., 0.01%)
