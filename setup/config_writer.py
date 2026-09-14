"""Safe, small .env writer used by the local-AI setup CLI."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


def build_local_ai_config(
    base_url: str,
    model: str,
    auto_select_model: bool = True,
) -> dict[str, str]:
    """Return only non-secret local-AI settings."""

    return {
        "AI_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": base_url.rstrip("/"),
        "OLLAMA_MODEL": model,
        "LOCAL_AI_MODEL": model,
        "LOCAL_AI_AUTO_SETUP": "false",
        "LOCAL_AI_AUTO_SELECT_MODEL": "true" if auto_select_model else "false",
    }


def update_env_file(
    path: str | Path,
    values: Mapping[str, str],
    create: bool = True,
) -> Path:
    """Update selected keys while preserving unrelated lines and secrets.

    The file is replaced atomically and receives mode 0600 on POSIX systems.
    Existing values for keys in ``values`` are replaced; all other content is
    preserved verbatim.
    """

    destination = Path(path)
    if not destination.exists() and not create:
        raise FileNotFoundError(destination)

    for key, value in values.items():
        if not _ENV_KEY.fullmatch(key):
            raise ValueError(f"Invalid environment key: {key!r}")
        if "\n" in value or "\r" in value:
            raise ValueError(f"Environment value for {key} contains a newline.")

    original = destination.read_text(encoding="utf-8") if destination.exists() else ""
    lines = original.splitlines(keepends=True)
    replaced: set[str] = set()
    output: list[str] = []

    for line in lines:
        match = re.match(r"^(\s*)([A-Z][A-Z0-9_]*)\s*=.*?(\r?\n)?$", line)
        if match and match.group(2) in values:
            key = match.group(2)
            output.append(f"{key}={values[key]}\n")
            replaced.add(key)
        else:
            output.append(line)

    for key, value in values.items():
        if key not in replaced:
            if output and not output[-1].endswith("\n"):
                output.append("\n")
            output.append(f"{key}={value}\n")

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=str(destination.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary:
            temporary.write("".join(output))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, destination)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass

    return destination
