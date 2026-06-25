from fastapi.testclient import TestClient
from aishelf.site.app import app

client = TestClient(app)


def test_genesis_page_renders():
    r = client.get("/genesis")
    assert r.status_code == 200
    body = r.text
    assert 'class="genesis"' in body
    assert "创世" in body
    assert "COSMOGONY" in body
    assert "卡俄斯" in body  # 四神之一
    assert "/static/genesis.css" in body
    assert "/static/genesis.js" in body
