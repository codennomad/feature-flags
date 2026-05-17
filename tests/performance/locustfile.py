"""
tests/performance/locustfile.py — Cenário realista de carga.

Rode com:
  locust -f tests/performance/locustfile.py --headless -u 500 -r 50 -t 60s
"""
from __future__ import annotations

from locust import HttpUser, between, task


class FeatureFlagUser(HttpUser):
    wait_time = between(0.001, 0.01)  # 100-1000 RPS por usuário

    def on_start(self) -> None:
        # Autentica uma vez
        resp = self.client.post(
            "/api/v1/auth/token",
            json={"api_key": "load-test-key"},
        )
        self.token = resp.json().get("access_token", "invalid")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task(10)  # 10x mais frequente que escrita
    def evaluate_flag(self) -> None:
        self.client.post(
            "/api/v1/evaluate",
            headers=self.headers,
            json={
                "flag_key": "checkout-v2",
                "user_id": f"user-{self.user_id % 10_000}",
                "environment": "production",
                "attributes": {"country": "BR", "plan": "pro"},
            },
            name="/api/v1/evaluate",
        )

    @task(1)
    def batch_evaluate(self) -> None:
        self.client.post(
            "/api/v1/evaluate/batch",
            headers=self.headers,
            json={
                "flags": ["checkout-v2", "new-pricing", "dark-mode"],
                "user_id": f"user-{self.user_id % 10_000}",
                "environment": "production",
            },
            name="/api/v1/evaluate/batch",
        )

    @task(1)
    def list_flags(self) -> None:
        self.client.get("/api/v1/flags", headers=self.headers)
