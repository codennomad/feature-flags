"""
tests/utils/attack_payloads.py — Payloads de ataque centralizados.

Centralizar facilita manutenção, auditoria e adição de novos vetores.
"""
from __future__ import annotations

# ── SQL Injection ──────────────────────────────────────────────────────────────

SQL_INJECTION_PAYLOADS = [
    "'; DROP TABLE flags; --",
    "' OR '1'='1",
    "' OR 1=1--",
    "'; SELECT * FROM audit_logs; --",
    "1; UPDATE flags SET default_value='{}' WHERE 1=1--",
    "' UNION SELECT id, key, null FROM flags--",
    "\\'; DROP TABLE flags; --",
    "%27 OR %271%27=%271",
    "1' AND SLEEP(5)--",  # blind time-based
    "' AND 1=CAST((SELECT version()) AS INT)--",  # error-based
    "' AND EXTRACTVALUE(1, CONCAT(0x7e, (SELECT version())))--",
]

# ── NoSQL Injection ────────────────────────────────────────────────────────────

NOSQL_INJECTION_PAYLOADS = [
    {"$gt": ""},
    {"$where": "this.key.length > 0"},
    {"$regex": ".*"},
    '{"$gt": ""}',
]

# ── SSTI (Server-Side Template Injection) ─────────────────────────────────────

SSTI_PAYLOADS = [
    "{{7*7}}",
    "${7*7}",
    "#{7*7}",
    "{{config}}",
    "{{request.application.__globals__}}",
    "<%= 7*7 %>",
]

# ── Path Traversal ─────────────────────────────────────────────────────────────

PATH_TRAVERSAL_PAYLOADS = [
    "../../../etc/passwd",
    "..\\..\\..\\windows\\system32",
    "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "....//....//....//etc/passwd",
]

# ── XSS ───────────────────────────────────────────────────────────────────────

XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(1)",
    '"><script>alert(1)</script>',
    "';alert(1)//",
]
