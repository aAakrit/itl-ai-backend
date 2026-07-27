"""
Shared HTTP client used by all external AI providers.

Responsibilities
----------------
- Reuse a single httpx.AsyncClient
- JSON requests
- Multipart requests
- Common timeout
- Error handling
- Response parsing

This class contains NO business logic.
Providers are responsible for deciding which endpoint to call.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import AI_TIMEOUT
from .exceptions import (
    AIConnectionException,
    AIResponseException,
    AITimeoutException,
    AIInvalidResponseException,
)


class GatewayClient:
    """
    Shared async HTTP client for all AI providers.
    """

    def __init__(self, timeout: int = AI_TIMEOUT):
        self.timeout = timeout

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=float(timeout),
                write=60.0,
                pool=10.0,
            ),
            follow_redirects=True,
        )

    async def close(self) -> None:
        """
        Close the underlying connection pool.
        """
        await self._client.aclose()

    def _build_url(
        self,
        base_url: str,
        endpoint: str,
    ) -> str:
        """
        Build the full request URL.
        """

        if not base_url:
            raise AIConnectionException(
                "AI service URL is not configured."
            )

        return f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict:
        """
        Validate and parse the HTTP response.
        """

        response.raise_for_status()

        if not response.content:
            return {}

        try:
            return response.json()
        except ValueError as exc:
            raise AIInvalidResponseException(
                "AI service returned invalid JSON."
            ) from exc

    @staticmethod
    def _handle_exception(exc: Exception) -> None:
        """
        Translate httpx exceptions into application exceptions.
        """

        if isinstance(exc, httpx.TimeoutException):
            raise AITimeoutException(str(exc)) from exc

        if isinstance(exc, httpx.HTTPStatusError):
            raise AIResponseException(
                status_code=exc.response.status_code,
                detail=exc.response.text,
            ) from exc

        if isinstance(exc, httpx.HTTPError):
            raise AIConnectionException(str(exc)) from exc

        raise exc

    async def get(
        self,
        base_url: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict:
        """
        Execute a GET request.
        """

        try:
            response = await self._client.get(
                self._build_url(base_url, endpoint),
                params=params,
            )

            return self._parse_response(response)

        except Exception as exc:
            self._handle_exception(exc)

    async def post_json(
        self,
        base_url: str,
        endpoint: str,
        payload: dict[str, Any],
    ) -> dict:
        """
        Execute a JSON POST request.
        """

        try:
            response = await self._client.post(
                self._build_url(base_url, endpoint),
                json=payload,
            )

            return self._parse_response(response)

        except Exception as exc:
            self._handle_exception(exc)

    async def post_multipart(
        self,
        base_url: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict:
        """
        Execute a multipart/form-data POST request.

        Used by:
        - Notice Reply Agent
        - Document Summarizer
        """

        try:
            response = await self._client.post(
                self._build_url(base_url, endpoint),
                data=data or {},
                files=files or {},
            )

            return self._parse_response(response)

        except Exception as exc:
            self._handle_exception(exc)

    async def post_multipart_sse(
        self,
        base_url: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict:
        """
        Execute a multipart/form-data POST whose response is a
        Server-Sent-Events stream (Document Summarizer confirmed against
        the vendor API doc, Section 5.1) — NOT a single JSON body, so
        `post_multipart`'s `response.json()` would raise on it.

        Each event line looks like `data: {"content": "..."}`, ending with
        `data: {"done": true}`, or `data: {"success": false, "error": "..."}`
        on failure. Chunks are concatenated into one `content` string so
        callers can treat this exactly like any other JSON-returning
        provider call — streaming this incrementally to the frontend is a
        separate, larger change (would need SSE end-to-end, not just here).
        """

        try:
            async with self._client.stream(
                "POST",
                self._build_url(base_url, endpoint),
                data=data or {},
                files=files or {},
            ) as response:
                response.raise_for_status()

                content_parts: list[str] = []
                error: str | None = None

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue

                    raw = line[len("data:"):].strip()
                    if not raw:
                        continue

                    try:
                        event = json.loads(raw)
                    except ValueError:
                        continue

                    if event.get("done"):
                        break
                    if event.get("success") is False:
                        error = event.get("error", "Summarization failed.")
                        break
                    if "content" in event:
                        content_parts.append(event["content"])

                if error:
                    raise AIResponseException(status_code=response.status_code, detail=error)

                return {"success": True, "content": "".join(content_parts)}

        except AIResponseException:
            raise
        except Exception as exc:
            self._handle_exception(exc)

    async def health(
        self,
        base_url: str,
        endpoint: str = "/api/health",
    ) -> dict:
        """
        Convenience helper for checking service health.
        """

        return await self.get(
            base_url=base_url,
            endpoint=endpoint,
        )


# Shared singleton instance
gateway_client = GatewayClient()