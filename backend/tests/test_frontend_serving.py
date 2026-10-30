from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import mount_frontend


def make_client(tmp_path):
    (tmp_path / "assets").mkdir(parents=True)
    (tmp_path / "index.html").write_text("<!doctype html><title>Mealplan</title>")
    (tmp_path / "assets" / "index-abc.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "secret.txt").write_text("nope")
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    mount_frontend(app, tmp_path)
    return TestClient(app)


def test_spa_routes_assets_and_api(tmp_path):
    client = make_client(tmp_path / "dist")
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/nope").status_code == 404
    deep = client.get("/foods/12")
    assert deep.status_code == 200 and "Mealplan" in deep.text
    assert deep.headers["cache-control"] == "no-cache"
    asset = client.get("/assets/index-abc.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    assert client.get("/favicon.svg").headers["cache-control"] == "no-cache"


def test_no_path_traversal(tmp_path):
    client = make_client(tmp_path / "dist")
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        resp = client.get(path)
        assert "nope" not in resp.text


def test_security_headers_on_api(client):
    resp = client.get("/api/health")
    assert resp.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in resp.headers["content-security-policy"]
    assert "content-security-policy" not in client.get("/docs").headers
