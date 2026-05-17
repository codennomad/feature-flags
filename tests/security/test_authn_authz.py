"""
tests/security/test_authn_authz.py — Autenticação e autorização.

Testa: endpoints sem token (401), JWT expirado, assinatura adulterada,
ataque alg=none, RBAC viewer vs admin, imutabilidade do audit log.
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from tests.conftest import generate_jwt, generate_valid_jwt

pytestmark = pytest.mark.security


class TestAuthentication:

    async def test_all_endpoints_require_authentication(self, async_client):
        """
        Sem token JWT, todos os endpoints retornam 401.
        Nenhum endpoint deve ser acessível sem autenticação.
        """
        endpoints = [
            ("GET", "/api/v1/flags"),
            ("POST", "/api/v1/flags"),
            ("GET", "/api/v1/flags/some-flag"),
            ("PATCH", "/api/v1/flags/some-flag"),
            ("DELETE", "/api/v1/flags/some-flag"),
            ("POST", "/api/v1/evaluate"),
            ("POST", "/api/v1/evaluate/batch"),
            ("GET", "/api/v1/flags/some-flag/audit"),
        ]
        for method, path in endpoints:
            response = await async_client.request(method, path)
            assert response.status_code == 401, (
                f"{method} {path} retornou {response.status_code} sem autenticação"
            )

    async def test_expired_jwt_returns_401(self, async_client):
        """JWT expirado deve ser rejeitado — sem tolerância de clock."""
        expired_token = generate_jwt(
            sub="user-123",
            exp=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        response = await async_client.get(
            "/api/v1/flags",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401

    async def test_tampered_jwt_signature_rejected(self, async_client):
        """JWT com assinatura alterada deve ser rejeitado."""
        valid_token = generate_valid_jwt(sub="user-123")
        # Altera o último caractere da assinatura
        tampered = valid_token[:-1] + ("A" if valid_token[-1] != "A" else "B")
        response = await async_client.get(
            "/api/v1/flags",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert response.status_code == 401

    async def test_none_algorithm_jwt_rejected(self, async_client):
        """
        Ataque clássico: JWT com alg=none.
        Muitas implementações aceitam por engano — a nossa não deve.
        """
        header = (
            base64.urlsafe_b64encode(
                json.dumps({"alg": "none", "typ": "JWT"}).encode()
            )
            .rstrip(b"=")
            .decode()
        )
        payload = (
            base64.urlsafe_b64encode(
                json.dumps({"sub": "admin", "role": "admin", "exp": 9_999_999_999}).encode()
            )
            .rstrip(b"=")
            .decode()
        )
        none_token = f"{header}.{payload}."

        response = await async_client.get(
            "/api/v1/flags",
            headers={"Authorization": f"Bearer {none_token}"},
        )
        assert response.status_code == 401

    async def test_viewer_cannot_modify_flags(self, async_client, viewer_token):
        """Role 'viewer' pode listar mas não pode criar/modificar/deletar."""
        headers = {"Authorization": f"Bearer {viewer_token}"}

        # Pode visualizar
        assert (
            await async_client.get("/api/v1/flags", headers=headers)
        ).status_code == 200

        # Não pode modificar
        assert (
            await async_client.post(
                "/api/v1/flags",
                headers=headers,
                json={"key": "x", "name": "X", "default_value": False},
            )
        ).status_code == 403

        assert (
            await async_client.delete("/api/v1/flags/some-flag", headers=headers)
        ).status_code == 403


class TestAuditTampering:

    async def test_audit_log_has_no_update_endpoint(self, async_client, admin_token):
        """
        O audit log é imutável por design.
        Não deve existir nenhum endpoint para alterar registros de auditoria.
        """
        headers = {"Authorization": f"Bearer {admin_token}"}
        audit_id = "some-real-audit-id"

        for method in ["PUT", "PATCH", "DELETE"]:
            response = await async_client.request(
                method,
                f"/api/v1/audit/{audit_id}",
                headers=headers,
            )
            # Deve retornar 405 (Method Not Allowed) ou 404
            assert response.status_code in (404, 405), (
                f"{method} /api/v1/audit/{audit_id} não deveria existir"
            )

    async def test_audit_entry_created_even_if_main_operation_succeeds(
        self, async_client, db_session, admin_token
    ):
        """
        Criar uma flag DEVE gerar entrada no audit log na mesma transação.
        Sem entrada = sem flag. Isso garante rastreabilidade completa.
        """
        from src.models.audit import AuditLog

        headers = {"Authorization": f"Bearer {admin_token}"}
        flag_data = {
            "key": "audit-test-flag",
            "name": "Audit Test",
            "default_value": False,
        }

        response = await async_client.post("/api/v1/flags", headers=headers, json=flag_data)
        assert response.status_code == 201
        flag_id = response.json()["id"]

        # Verifica que o audit log foi criado
        audit_count = await db_session.scalar(
            select(func.count()).where(AuditLog.flag_id == flag_id)
        )
        assert audit_count == 1, "Nenhuma entrada de audit log foi criada"
