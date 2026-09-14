"""Small liveness/readiness HTTP app used by local deployments."""

from __future__ import annotations

from threading import Lock

from flask import Flask, jsonify

app = Flask(__name__)

_ready = False
_ready_lock = Lock()


def set_ready(value: bool = True) -> None:
    global _ready
    with _ready_lock:
        _ready = value


def is_ready() -> bool:
    with _ready_lock:
        return _ready


@app.get("/")
def home():
    return "AI Discord Builder is online 🚀"


@app.get("/healthz")
def healthz():
    """Process liveness endpoint; it intentionally exposes no secrets."""

    return jsonify({"status": "ok", "service": "ai-discord-builder"})


@app.get("/readyz")
def readyz():
    """Readiness endpoint set after the Discord runtime has initialized."""

    if not is_ready():
        return jsonify({"status": "starting"}), 503
    return jsonify({"status": "ready"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
