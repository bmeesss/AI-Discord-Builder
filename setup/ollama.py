"""Read-only detection and explicit lifecycle operations for Ollama."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from ai.providers.ollama import normalize_ollama_url


class OllamaSetupError(RuntimeError):
    """An Ollama setup operation failed."""


@dataclass(frozen=True, slots=True)
class OllamaStatus:
    base_url: str
    installed: bool
    running: bool
    version: str | None
    models: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["models"] = list(self.models)
        return value


JsonRequester = Callable[[str, str, dict[str, Any] | None, int], dict[str, Any]]
CommandRunner = Callable[[Sequence[str], int], tuple[int, str, str]]


class OllamaManager:
    """Manage a host or Docker-reachable Ollama HTTP endpoint.

    Constructing this class is safe.  Installing or starting software only
    occurs when the corresponding methods are explicitly called by the setup
    flow after user approval.
    """

    def __init__(
        self,
        base_url: str,
        executable: str | None = None,
        requester: JsonRequester | None = None,
        command_runner: CommandRunner | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = normalize_ollama_url(base_url)
        self.executable = executable or shutil.which("ollama")
        self._requester = requester or _request_json
        self._command_runner = command_runner or _run_command
        self._sleep = sleep

    def status(self) -> OllamaStatus:
        installed = bool(self.executable)
        version = self.version()

        try:
            data = self._requester(
                "GET",
                self._url("/api/tags"),
                None,
                5,
            )
            models = tuple(sorted(_model_names(data)))
            return OllamaStatus(
                base_url=self.base_url,
                installed=installed,
                running=True,
                version=version,
                models=models,
            )
        except OllamaSetupError as exc:
            return OllamaStatus(
                base_url=self.base_url,
                installed=installed,
                running=False,
                version=version,
                error=str(exc),
            )

    def version(self) -> str | None:
        if not self.executable:
            return None
        returncode, stdout, _stderr = self._command_runner(
            [self.executable, "--version"],
            5,
        )
        if returncode != 0:
            return None
        return stdout.strip() or None

    def healthcheck(self) -> bool:
        try:
            self._requester("GET", self._url("/api/tags"), None, 5)
        except OllamaSetupError:
            return False
        return True

    def list_models(self) -> tuple[str, ...]:
        data = self._requester("GET", self._url("/api/tags"), None, 10)
        return tuple(sorted(_model_names(data)))

    def model_available(self, model: str) -> bool:
        return model.strip() in set(self.list_models())

    def start(self, startup_timeout: int = 30) -> None:
        """Start a local executable and wait for its HTTP endpoint.

        A remote/Docker endpoint with no local executable is not started here;
        its lifecycle belongs to Docker or the remote runtime.
        """

        if self.healthcheck():
            return
        if not self.executable:
            # Installation may have happened after this manager was created.
            self.executable = shutil.which("ollama")
        if not self.executable:
            raise OllamaSetupError(
                "Ollama is not running and no local Ollama executable was found."
            )

        try:
            subprocess.Popen(
                [self.executable, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise OllamaSetupError("Ollama could not be started.") from exc

        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            if self.healthcheck():
                return
            self._sleep(1)

        raise OllamaSetupError(
            f"Ollama did not become healthy within {startup_timeout} seconds."
        )

    def pull_model(self, model: str, timeout: int = 3600) -> None:
        target = model.strip()
        if not target:
            raise OllamaSetupError("A model name is required before pulling a model.")

        try:
            self._requester(
                "POST",
                self._url("/api/pull"),
                {"name": target, "stream": False},
                timeout,
            )
        except OllamaSetupError as exc:
            raise OllamaSetupError(
                f"Model {target} could not be downloaded from Ollama."
            ) from exc

    def test_model(self, model: str, timeout: int = 180) -> str:
        target = model.strip()
        try:
            response = self._requester(
                "POST",
                self._url("/api/chat"),
                {
                    "model": target,
                    "messages": [
                        {
                            "role": "user",
                            "content": "Reply with exactly the word OK.",
                        }
                    ],
                    "stream": False,
                },
                timeout,
            )
        except OllamaSetupError as exc:
            raise OllamaSetupError(
                f"Ollama model {target} did not respond successfully."
            ) from exc

        message = response.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not content:
            content = response.get("response")
        if not isinstance(content, str) or not content.strip():
            raise OllamaSetupError(f"Ollama model {target} returned an empty response.")
        return content.strip()

    def _url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/", path.lstrip("/"))


def _model_names(data: dict[str, Any]) -> set[str]:
    models = data.get("models", [])
    if not isinstance(models, list):
        return set()
    return {
        item["name"]
        for item in models
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def _request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    timeout: int,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310 - URL is validated
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise OllamaSetupError(
            f"Ollama returned HTTP {exc.code} for {method} {url}."
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise OllamaSetupError(
            "Ollama is not reachable at the configured base URL."
        ) from exc

    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OllamaSetupError("Ollama returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise OllamaSetupError("Ollama returned an unexpected response.")
    return data


def _run_command(command: Sequence[str], timeout: int) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return result.returncode, result.stdout or "", result.stderr or ""
