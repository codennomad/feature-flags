# ADR 002: Eventual consistency via pub/sub vs. consistência forte

**Data:** 2024-01-01  
**Status:** Aceito  
**Autores:** @codennomad

---

## Contexto

O sistema mantém um cache local por processo para avaliação em memória (< 1ms). Quando uma flag é modificada via API, todos os processos precisam atualizar seus caches. A questão é: **como garantir que todos os processos vejam a versão mais recente?**

Existem dois modelos principais de sincronização: **polling** e **pub/sub**.

---

## Opções avaliadas

### Opção 1 — Polling periódico (strong consistency com tolerância de staleness)
Cada processo consulta o banco a cada N segundos.

```
Processo A → SELECT * FROM flags WHERE version > $last_version (a cada 5s)
```

**Prós:** Simples de implementar, sem dependência de Redis, auto-recuperação automática  
**Contras:** Staleness garantida de até N segundos, pressão em banco com muitas réplicas, todos os processos consultam ao mesmo tempo (thundering herd)

### Opção 2 — Redis pub/sub com invalidação por chave (decisão tomada)
Após cada escrita no banco, publica mensagem no canal `feature_flags:invalidate`.

```
API escrita → PostgreSQL (commit) → PUBLISH feature_flags:invalidate {flag_key, version, action}
                                          ↓
                          Todos os processos subscribed → cache.invalidate(flag_key)
```

**Prós:** Propagação em < 50ms (tipicamente < 10ms), sem pressão em banco, granular (só a flag modificada é invalidada), baixo overhead por processo  
**Contras:** Se Redis cair, invalidações ficam pendentes (janela de inconsistência), conexão persistente por processo, race condition possível entre versões

### Opção 3 — Read-through cache com TTL fixo
Cache expira automaticamente após N segundos. Sem mecanismo de invalidação.

**Prós:** Extremamente simples  
**Contras:** Staleness sempre presente mesmo sem mudanças, não adequado para kill switches de emergência

---

## Decisão

**Pub/sub Redis** com canal dedicado `feature_flags:invalidate`.

Formato da mensagem:
```json
{"flag_key": "checkout-v2", "version": 42, "action": "updated"}
```

Cada processo listener recebe a mensagem e invalida/atualiza apenas a flag afetada no cache local. A versão (`version`) permite detectar mensagens duplicadas ou fora de ordem.

**Garantia de consistência:** Eventual, com janela típica de < 50ms. Para kill switches de emergência, isso é adequado — a flag estará desabilitada em todos os processos em menos de um segundo.

---

## Tradeoffs aceitos

| Cenário | Comportamento |
|---------|---------------|
| Redis offline (breve) | Cache fica com versões anteriores. Após reconexão, processos não recuperam mensagens perdidas automaticamente — use `version` para detectar |
| Redis offline (longo) | Próximo restart do processo carrega versão atual do banco via `warm_up()` |
| Race condition de versões | Mensagem com version < versão do cache local é ignorada |
| Reinício de processo | `warm_up()` no lifespan garante estado consistente antes de aceitar requests |

---

## Consequências

**Positivas:**
- Kill switches propagam em < 1s para todos os processos
- Sem polling = sem pressão em banco durante operação normal
- Cache por processo = zero I/O no hot path de avaliação

**Negativas:**
- Redis é dependência crítica para consistência (não para availability — o sistema continua funcionando com dados stale)
- Processos recém-iniciados DEVEM completar `warm_up()` antes de aceitar requests (garantido pelo lifespan)

---

## Quando revisar esta decisão

- Se Redis passar a ser ponto único de falha inaceitável para o negócio
- Se a janela de eventual consistency (< 1s) for insuficiente para requisitos de compliance
- Se o número de processos tornaria o fanout de pub/sub ineficiente (> 1000 subscribers)
