"""Ollama provider and small asynchronous HTTP client.

Ollama is intentionally accessed over HTTP instead of through a Python Ollama
SDK.  This keeps local-AI support optional and works for both a host process
(`http://localhost:11434`) and a Docker service (`http://ollama:11434`).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urljoin, urlparse

from ai.providers.base import ProviderError, ProviderHealth

logger = logging.getLogger("ai_discord_builder.ai.providers.ollama")


class OllamaHTTPClient:
    """Minimal async HTTP client for the Ollama API.

    A client can be injected into :class:`OllamaProvider` in tests.  Production
    uses aiohttp lazily, so cloud-only installations do not import it while
    selecting Groq or OpenAI.
    """

    def __init__(self, base_url: str, timeout: int = 60) -> None:
        self.base_url = normalize_ollama_url(base_url)
        self.timeout = timeout

    async def get(self, path: str, timeout: int | None = None) -> dict[str, Any]:
        return await self.request("GET", path, timeout=timeout)

    async def post(
        self,
        path: str,
        payload: dict[str, Any],
        timeout: int | None = None,
    ) -> dict[str, Any]:
        return await self.request("POST", path, payload, timeout=timeout)

    async def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        try:
            import aiohttp
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise ProviderError(
                "The aiohttp dependency is required for Ollama support."
            ) from exc

        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        request_timeout = aiohttp.ClientTimeout(total=timeout or self.timeout)

        try:
            async with (
                aiohttp.ClientSession(timeout=request_timeout) as session,
                session.request(
                    method,
                    url,
                    json=payload,
                    headers={"Accept": "application/json"},
                ) as response,
            ):
                body = await response.text()
                if response.status >= 400:
                    raise ProviderError(
                        f"Ollama returned HTTP {response.status} for {path}."
                    )
                if not body.strip():
                    return {}
                try:
                    data = json.loads(body)
                except (TypeError, ValueError) as exc:
                    raise ProviderError(
                        f"Ollama returned invalid JSON for {path}."
                    ) from exc
                if not isinstance(data, dict):
                    raise ProviderError(
                        f"Ollama returned an unexpected response for {path}."
                    )
                return data
        except ProviderError:
            raise
        except asyncio.TimeoutError as exc:
            raise ProviderError(
                f"Ollama request timed out after {timeout or self.timeout} seconds."
            ) from exc
        except aiohttp.ClientError as exc:
            raise ProviderError(
                "Ollama is not reachable at the configured base URL."
            ) from exc


def normalize_ollama_url(base_url: str) -> str:
    """Validate and normalize an Ollama HTTP(S) base URL."""

    value = (base_url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "OLLAMA_BASE_URL must be an absolute http:// or https:// URL."
        )
    return value


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: int = 60,
        http_client: OllamaHTTPClient | Any | None = None,
    ) -> None:
        if not model or not model.strip():
            raise ProviderError("OLLAMA_MODEL is required when AI_PROVIDER=ollama.")

        self.model = model.strip()
        self._timeout = timeout
        self._http = http_client or OllamaHTTPClient(base_url, timeout=timeout)
        self.base_url = normalize_ollama_url(base_url)

    async def healthcheck(self) -> ProviderHealth:
        try:
            data = await self._http.get("/api/tags")
            models = _model_names(data)
        except (ProviderError, OSError, ValueError) as exc:
            logger.info("Ollama health check failed: %s", exc)
            return ProviderHealth(
                ok=False,
                provider=self.name,
                model=self.model,
                message=(
                    "Ollama is not reachable. Start Ollama or check "
                    "OLLAMA_BASE_URL."
                ),
                model_available=False,
            )

        available = self.model in models
        return ProviderHealth(
            ok=True,
            provider=self.name,
            model=self.model,
            message=(
                "Ollama is reachable and the configured model is available."
                if available
                else "Ollama is reachable, but the configured model is not pulled."
            ),
            model_available=available,
        )

    async def model_available(self, model: str | None = None) -> bool:
        target = model or self.model
        data = await self._http.get("/api/tags")
        return target in _model_names(data)

    async def pull_model(self, model: str | None = None) -> None:
        target = (model or self.model).strip()
        if not target:
            raise ProviderError("Cannot pull an empty Ollama model name.")

        try:
            await self._http.post(
                "/api/pull",
                {"name": target, "stream": False},
                timeout=max(self._timeout, 3600),
            )
        except ProviderError:
            logger.exception("Ollama model pull failed for %s", target)
            raise ProviderError(
                f"Ollama could not pull model {target}."
            ) from None

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            # Ollama's JSON format flag is the local equivalent of the cloud
            # providers' response_format option.
            "format": "json",
            "options": {"temperature": 0.3},
        }

        try:
            response = await self._http.post(
                "/api/chat",
                payload,
                timeout=self._timeout,
            )
        except ProviderError:
            logger.exception("Ollama chat request failed")
            raise ProviderError(
                "Ollama could not generate a response. Check that the model is available."
            ) from None

        message = response.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        # Older Ollama endpoints may return /api/generate-style responses.
        if not content:
            content = response.get("response")

        if not isinstance(content, str) or not content.strip():
            raise ProviderError("Ollama returned an empty model response.")
        return content

    async def test_model(self) -> ProviderHealth:
        try:
            if not await self.model_available():
                return ProviderHealth(
                    ok=False,
                    provider=self.name,
                    model=self.model,
                    message=f"Ollama model {self.model} is not pulled.",
                    model_available=False,
                )

            content = await self._http.post(
                "/api/chat",
                {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": "Reply with exactly the word OK.",
                        }
                    ],
                    "stream": False,
                },
                timeout=self._timeout,
            )
            message = content.get("message")
            text = message.get("content") if isinstance(message, dict) else content.get("response")
            if not isinstance(text, str) or not text.strip():
                raise ProviderError("Ollama returned no test response.")
        except ProviderError:
            logger.exception("Ollama model test failed")
            return ProviderHealth(
                ok=False,
                provider=self.name,
                model=self.model,
                message="Ollama model test failed.",
                model_available=False,
            )

        return ProviderHealth(
            ok=True,
            provider=self.name,
            model=self.model,
            message="Ollama model test succeeded.",
            model_available=True,
        )


def _model_names(data: dict[str, Any]) -> set[str]:
    models = data.get("models", [])
    if not isinstance(models, list):
        return set()

    names: set[str] = set()
    for item in models:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])
    return names
