"""Live smoke test against a running Hermes server. Skipped unless `-m network`."""

import pytest
from fastapi.testclient import TestClient

from aishelf.webui.app import app

pytestmark = pytest.mark.network


def test_live_chat_round_trip():
    client = TestClient(app)
    resp = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "请只回复：ok"}]},
    )
    assert resp.status_code == 200
    deltas = [
        line for line in resp.text.splitlines()
        if line.startswith("data: ") and '"delta"' in line
    ]
    assert deltas, "expected at least one streamed delta from Hermes"
