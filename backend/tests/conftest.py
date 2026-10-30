import json
import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789-abcdefghijkl")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db, make_engine
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# Tests run on in-memory SQLite by default; set TEST_DATABASE_URL (e.g. a scratch PostgreSQL
# database) to run them against another engine. That database is wiped for every test.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def db_session():
    if TEST_DATABASE_URL:
        engine = make_engine(TEST_DATABASE_URL)
        Base.metadata.drop_all(engine)
    else:
        engine = make_engine("sqlite://", poolclass=StaticPool)  # one shared in-memory connection per test
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def register(client: TestClient, email: str = "a@example.com", password: str = "correct horse battery") -> dict:
    resp = client.post("/api/auth/register", json={"email": email, "password": password, "display_name": "A"})
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def user_client(client):
    register(client)
    return client
