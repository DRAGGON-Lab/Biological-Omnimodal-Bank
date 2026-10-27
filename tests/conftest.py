import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from bob import designs, synbiohub
from bob.fixtures import SYNBIOHUB, synthetic_design_sbol, synthetic_gen5_workbook

# Set to a throwaway PostgreSQL database to run the suite there; it is emptied before every test.
TEST_DATABASE_URL = os.environ.get("BOB_TEST_DATABASE_URL")


def _empty_postgres(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BOB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BOB_MODE", "api")
    monkeypatch.setenv("BOB_BASE_IRI", "https://bob.test")
    monkeypatch.setenv("BOB_ALLOWED_HOSTS", "testserver")
    monkeypatch.delenv("BOB_ALLOW_SIGNUP", raising=False)
    monkeypatch.delenv("BOB_SEED_DEMO", raising=False)
    if TEST_DATABASE_URL:
        _empty_postgres(TEST_DATABASE_URL)
        monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    return tmp_path / "data"


class FakeSynBioHub:
    """Answers BOB's design reads with the synthetic designs, as SynBioHub's recursive SBOL would."""

    def __init__(self, token: str | None):
        self.token = token
        self.docs = synthetic_design_sbol()
        self.asked: list[tuple[str, str | None]] = []

    def __call__(self, url: str, token: str | None):
        self.asked.append((url, token))
        if self.token and token != self.token:
            raise synbiohub.SynBioHubError("SynBioHub asked for a sign-in: login required", 401)
        doc = self.docs.get(url.removesuffix("/sbol"))
        if doc is None:
            raise synbiohub.SynBioHubError("SynBioHub answered 404: not found", 404)
        return SimpleNamespace(content=doc)


@pytest.fixture
def fake_synbiohub(data_dir, monkeypatch):
    """Request it before `client`, so the app starts knowing the fake SynBioHub. Set `.token` to make the designs private."""
    monkeypatch.setenv("BOB_SYNBIOHUB_INSTANCES", f"https://synbiohub.org,{SYNBIOHUB}")
    fake = FakeSynBioHub(None)
    monkeypatch.setattr(synbiohub, "request_sbol", fake)
    designs._cache.clear()
    yield fake
    designs._cache.clear()


@pytest.fixture
def client(data_dir):
    from bob.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="session")
def plate_bytes() -> bytes:
    return synthetic_gen5_workbook()


def signup(client: TestClient, email: str, name: str = "Tester", password: str = "correct horse") -> dict:
    r = client.post("/api/auth/signup", json={"email": email, "name": name, "password": password})
    assert r.status_code == 201, r.text
    return client.get("/api/auth/me").json()
