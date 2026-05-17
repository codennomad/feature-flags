# ADR 001: Por que não usar LaunchDarkly (ou outro SaaS de feature flags)

**Data:** 2024-01-01  
**Status:** Aceito  
**Autores:** @codennomad

---

## Contexto

O time precisa de uma solução de feature flags para gradual rollout, A/B testing e kill switches em produção. Existem soluções SaaS maduras no mercado (LaunchDarkly, Split.io, Flagsmith Cloud, etc.) e alternativas self-hosted (Unleash, Flagsmith CE, Flipt).

A decisão central é: **construir internamente ou usar um produto existente?**

---

## Opções avaliadas

### Opção 1 — LaunchDarkly (SaaS)
- **Prós:** SDKs para 20+ linguagens, streaming em tempo real, dashboard rico, suporte enterprise
- **Contras:** Custo USD 8-20/seat/mês (escala com usuários), dados de usuário enviados a terceiros (bloqueio LGPD/GDPR para alguns clientes), vendor lock-in, latência adicional em cada avaliação (round-trip ao servidor), indisponibilidade do LaunchDarkly = indisponibilidade das avaliações

### Opção 2 — Split.io (SaaS)
- Mesmas tradeoffs que o LaunchDarkly com custo ainda maior

### Opção 3 — Unleash Community Edition (self-hosted)
- **Prós:** Open source, self-hosted, zero custo de licença
- **Contras:** Stack NodeJS (incompatível com nosso Python/FastAPI), SDK menos flexível, UI mais limitada, sem suporte a JSON flags nativamente

### Opção 4 — Construir internamente (decisão tomada)
- **Prós:** Latência < 1ms (avaliação em memória sem I/O), controle total dos dados (compliance LGPD), custo zero de licença, integração nativa com nosso stack, lógica de rollout transparente e auditável
- **Contras:** Custo de manutenção, surface de segurança maior, sem SDKs prontos para todas as linguagens

---

## Decisão

**Construir uma solução própria** com avaliação 100% em memória via cache local + pub/sub Redis para invalidação. Nenhum dado de usuário sai do processo de avaliação.

Arquitetura central:
```
Request → EvaluationEngine (RAM) → EvaluationResult
              ↑
          FlagCache ←── Redis pub/sub (invalidação em < 100ms)
              ↑
          PostgreSQL (source of truth)
```

---

## Consequências

**Positivas:**
- SLA de latência de avaliação: p99 < 1ms (provado em testes de CI)
- Zero dependência externa no hot path de avaliação
- Dados de usuários nunca saem da infraestrutura própria

**Negativas:**
- Precisamos manter SDKs (Python implementado na Phase 6)
- Ausência de dashboard SaaS — compensada pela API REST + audit log
- Custo de operação da infraestrutura (PostgreSQL + Redis)

---

## Quando revisar esta decisão

- Se o volume de flags ultrapassar 10.000 (pressão no cache em memória)
- Se for necessário SDK para linguagem sem suporte (iOS nativo, Rust, etc.)
- Se o custo de manutenção superar 20% do tempo do time
