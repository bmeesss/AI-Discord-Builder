"""Small liveness/readiness HTTP app used by local deployments.

/healthz — process liveness only (never exposes secrets).
/readyz  — readiness: Discord runtime is up AND every required runtime
           component (database backend, migrations) reported ready.
"""

from __future__ import annotations

from threading import Lock

from flask import Flask, jsonify

app = Flask(__name__)

_ready = False
_ready_lock = Lock()

_components: dict[str, dict[str, object]] = {}
_components_lock = Lock()


def set_ready(value: bool = True) -> None:
    global _ready
    with _ready_lock:
        _ready = value


def is_ready() -> bool:
    with _ready_lock:
        return _ready


def set_component(name: str, ok: bool, detail: str = "") -> None:
    """Report one runtime component's health (thread-safe)."""

    with _components_lock:
        _components[name] = {"ok": bool(ok), "detail": detail[:200]}


def get_components() -> dict[str, dict[str, object]]:
    with _components_lock:
        return {name: dict(info) for name, info in _components.items()}


def clear_components() -> None:
    with _components_lock:
        _components.clear()


def evaluate_readiness() -> tuple[dict, int]:
    """Aggregate readiness; pure logic kept separate for unit tests."""

    components = get_components()
    discord_ready = is_ready()
    unhealthy = {
        name: info["detail"]
        for name, info in components.items()
        if not info["ok"]
    }

    if discord_ready and not unhealthy:
        return {
            "status": "ready",
            "components": components,
        }, 200

    return {
        "status": "not ready",
        "discord": "ready" if discord_ready else "starting",
        "components": components,
    }, 503


@app.get("/")
def home():
    return "AI Discord Builder is online 🚀"


@app.get("/healthz")
def healthz():
    """Process liveness endpoint; it intentionally exposes no secrets."""

    return jsonify({"status": "ok", "service": "ai-discord-builder"})


@app.get("/readyz")
def readyz():
    """Readiness: Discord runtime and required components (database)."""

    payload, status = evaluate_readiness()
    return jsonify(payload), status


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
