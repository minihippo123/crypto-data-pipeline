from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import time
import uuid

import requests

from .collector_db import CollectorDatabase


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class AccountCollector:
    def __init__(self, database: CollectorDatabase) -> None:
        self.database = database
        self.access_value = os.getenv("ACCOUNT_ACCESS_VALUE", "")
        self.signing_value = os.getenv("ACCOUNT_SIGNING_VALUE", "")
        self.base_url = os.getenv("ACCOUNT_API_BASE_URL", "https://api.bithumb.com").rstrip("/")
        self.timeout = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
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

    def collect_once(self) -> dict[str, float | int]:
        response = requests.get(
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
            currency = str(item.get("currency", ""))
            balance = float(item.get("balance", 0) or 0)
            locked = float(item.get("locked", 0) or 0)
            normalized.append({"currency": currency, "balance": balance, "locked": locked})
            if currency == "KRW":
                total_value += balance + locked
                continue
            ticker = requests.get(
                f"{self.base_url}/public/ticker/{currency}_KRW",
                timeout=self.timeout,
            )
            ticker.raise_for_status()
            payload = ticker.json()
            if payload.get("status") == "0000":
                total_value += (balance + locked) * float(payload["data"]["closing_price"])

        self.database.save_account_snapshot("bithumb", total_value, normalized)
        return {"assets_saved": len(normalized), "total_value": total_value}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--sleep", type=float, default=60.0)
    args = parser.parse_args()
    database = CollectorDatabase(os.getenv("DATABASE_URL", "sqlite:///data/crypto_pipeline.db"))
    collector = AccountCollector(database)
    try:
        while True:
            print(collector.collect_once())
            if not args.loop:
                break
            time.sleep(args.sleep)
    finally:
        database.close()


if __name__ == "__main__":
    main()
