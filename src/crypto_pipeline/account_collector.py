from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid

import requests

from .collector_db import CollectorDatabase

LOGGER = logging.getLogger(__name__)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class AccountCollector:
    def __init__(self, database: CollectorDatabase) -> None:
        self.database = database
        self.access_value = os.getenv("ACCOUNT_ACCESS_VALUE", "")
        self.signing_value = os.getenv("ACCOUNT_SIGNING_VALUE", "")
        self.base_url = os.getenv("ACCOUNT_API_BASE_URL", "https://api.bithumb.com").rstrip("/")
        self.timeout = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
        self.collect_interval = float(os.getenv("ACCOUNT_COLLECT_INTERVAL_SECONDS", "5"))
        self.last_heartbeat = 0.0
        self.session = requests.Session()
        if not self.access_value or not self.signing_value:
            raise ValueError("ACCOUNT_ACCESS_VALUE and ACCOUNT_SIGNING_VALUE are required")

    def _authorization_header(self) -> dict[str, str]:
        payload = {
            "access_key": self.access_value,
            "nonce": str(uuid.uuid4()),
            "timestamp": round(time.time() * 1000),
        }
        encoded_header = _b64url(b'{"alg":"HS256","typ":"JWT"}')
        encoded_payload = _b64url(json.dumps(payload, separators=(",", ":")).encode())
        message = f"{encoded_header}.{encoded_payload}".encode()
        signature = _b64url(
            hmac.new(self.signing_value.encode(), message, hashlib.sha256).digest()
        )
        return {"Authorization": f"Bearer {encoded_header}.{encoded_payload}.{signature}"}

    def _heartbeat(self) -> None:
        now = time.time()
        if now - self.last_heartbeat >= 300:
            self.database.ping()
            self.database.log_event("account_collector", "heartbeat", "SUCCESS", {})
            LOGGER.info("AccountCollector running")
            self.last_heartbeat = now

    def _current_price(self, currency: str) -> float:
        response = self.session.get(
            f"{self.base_url}/public/ticker/{currency}_KRW",
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "0000":
            return 0.0
        return float(payload["data"]["closing_price"])

    def collect_once(self) -> dict[str, float | int]:
        response = self.session.get(
            f"{self.base_url}/v1/accounts",
            headers=self._authorization_header(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        balances = response.json()
        if not isinstance(balances, list):
            raise RuntimeError("unexpected account response")

        total_value = 0.0
        normalized: list[dict] = []
        for item in balances:
            currency = str(item.get("currency", "")).upper()
            balance = float(item.get("balance", 0) or 0)
            locked = float(item.get("locked", 0) or 0)
            average_buy_price = float(item.get("avg_buy_price", 0) or 0)
            quantity = balance + locked
            current_price = 1.0 if currency == "KRW" else self._current_price(currency)
            value = quantity if currency == "KRW" else quantity * current_price
            total_value += value
            normalized.append(
                {
                    "currency": currency,
                    "balance": balance,
                    "locked": locked,
                    "average_buy_price": average_buy_price,
                    "current_price": current_price,
                    "valuation": value,
                }
            )

        self.database.save_account_snapshot("bithumb", total_value, normalized)
        result = {"assets_saved": len(normalized), "total_value": total_value}
        self.database.log_event("account_collector", "collect_once", "SUCCESS", result)
        return result

    def run(self) -> None:
        while True:
            try:
                self._heartbeat()
                self.collect_once()
            except Exception as exc:
                LOGGER.exception("account collection failed: %s", exc)
                self.database.log_event(
                    "account_collector", "collect_once", "ERROR", {"error": str(exc)}
                )
            time.sleep(self.collect_interval)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    database = CollectorDatabase(os.getenv("DATABASE_URL", "sqlite:///data/crypto_pipeline.db"))
    collector = AccountCollector(database)
    try:
        print(collector.collect_once()) if args.once else collector.run()
    finally:
        database.close()


if __name__ == "__main__":
    main()
