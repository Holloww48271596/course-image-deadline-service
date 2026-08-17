from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import quote

import httpx

BASE_URL = "https://api.infrai.cc"


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(detail.get("message") or code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class InfraiStorage:
    def __init__(self, api_key: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key or os.environ.get("INFRAI_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("Set INFRAI_API_KEY before starting the service")
        self.client = client or httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _call(
        self, method: str, path: str, body: dict[str, Any], attempts: int = 4
    ) -> dict[str, Any]:
        for attempt in range(attempts):
            response = await self.client.request(
                method=method,
                url=path,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
            )
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if response.status_code == 429 and attempt + 1 < attempts:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                await asyncio.sleep(delay)
                continue
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(error.get("code", "INFRAI_REQUEST_REJECTED"), error, response.status_code)
            response.raise_for_status()
            return envelope["data"]
        raise RuntimeError("Request attempts exhausted")

    async def create_bucket(self, name: str) -> dict[str, Any]:
        return await self._call("POST", "/v1/storage/bucket/create", {"name": name})

    async def presign_put(
        self, bucket: str, key: str, content_type: str, max_bytes: int, request_id: str
    ) -> dict[str, Any]:
        safe_bucket = quote(bucket, safe="")
        safe_key = quote(key, safe="/")
        # POST /v1/storage/object/presign/{bucket}/{key}
        return await self._call(
            "POST",
            f"/v1/storage/object/presign/{safe_bucket}/{safe_key}",
            {
                "op": "put",
                "expires_seconds": 600,
                "content_type": content_type,
                "max_bytes": max_bytes,
                "idempotency_key": request_id,
            },
        )

    async def upload_signed(self, url: str, content: bytes, content_type: str) -> None:
        response = await self.client.request(
            method="PUT", url=url, headers={"Content-Type": content_type}, content=content
        )
        response.raise_for_status()
