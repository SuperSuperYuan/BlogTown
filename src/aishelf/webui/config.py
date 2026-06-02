"""Hermes connection settings, read from the environment.

Mirrors the env vars used by scripts/test_hermes.py so the dev defaults
match the already-verified local server.
"""

from __future__ import annotations

import os

from openai import OpenAI

DEFAULT_BASE_URL = "http://127.0.0.1:8642/v1"
DEFAULT_API_KEY = "EFd96sbMIobQK7pnHHEJ0Ri4VnfYNa_-rTcY8WiTZt4"
DEFAULT_MODEL = "hermes-agent"


def get_settings() -> dict[str, str]:
    return {
        "base_url": os.environ.get("HERMES_BASE_URL", DEFAULT_BASE_URL),
        "api_key": os.environ.get("HERMES_API_KEY", DEFAULT_API_KEY),
        "model": os.environ.get("HERMES_MODEL", DEFAULT_MODEL),
    }


def get_client() -> OpenAI:
    s = get_settings()
    return OpenAI(base_url=s["base_url"], api_key=s["api_key"], timeout=120.0)
