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
from typing import Any, AsyncIterator

import httpx

from app.config import AI_STREAM_READ_TIMEOUT, AI_TIMEOUT
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

    async def stream_sse(
        self,
        base_url: str,
        endpoint: str,
        payload: dict[str, Any],
    ) -> AsyncIterator[tuple[str, Any]]:
        """
        POST a JSON body and yield Server-Sent Events as (event_type, data).

        Keep-alive comment lines are yielded as ("keepalive", None) so the
        caller can pass them on. Raises AIResponseException when the service
        answers with a non-200 status (e.g. the stream endpoint doesn't exist
        on that service) so the caller can fall back to the normal call.
        Leaving the `async for` early (client disconnect, Stop button) closes
        the HTTP connection, which is how the AI service learns to cancel.
        """

        url = self._build_url(base_url, endpoint)
        timeout = httpx.Timeout(
            connect=10.0,
            read=float(AI_STREAM_READ_TIMEOUT),
            write=60.0,
            pool=10.0,
        )

        try:
            async with self._client.stream(
                "POST",
                url,
                json=payload,
                timeout=timeout,
                headers={"Accept": "text/event-stream"},
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise AIResponseException(
                        status_code=response.status_code,
                        detail=body[:500],
                    )

                event_type = "message"
                data_lines: list[str] = []

                async for line in response.aiter_lines():
                    if line == "":
                        if data_lines:
                            raw = "\n".join(data_lines)
                            try:
                                data = json.loads(raw)
                            except ValueError:
                                data = {"text": raw}
                            yield event_type, data
                        event_type = "message"
                        data_lines = []
                    elif line.startswith(":"):
                        yield "keepalive", None
                    elif line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())

        except httpx.TimeoutException as exc:
            raise AITimeoutException(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AIConnectionException(str(exc)) from exc

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