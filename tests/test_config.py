import pytest

from bob.config import load_settings


def _production(monkeypatch, tmp_path):
    secret = tmp_path / "app-secret"
    secret.write_text("a-production-secret-with-enough-entropy", encoding="utf-8")
    database = tmp_path / "database-url"
    database.write_text("postgresql+psycopg://bob:secret@db/bob", encoding="utf-8")
    monkeypatch.setenv("BOB_ENV", "production")
    monkeypatch.setenv("BOB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BOB_SECRET_KEY_FILE", str(secret))
    monkeypatch.setenv("DATABASE_URL_FILE", str(database))
    monkeypatch.setenv("BOB_BASE_IRI", "https://bob.example.edu")
    monkeypatch.setenv("BOB_ALLOWED_HOSTS", "bob.example.edu")
    monkeypatch.setenv("BOB_SECURE_COOKIES", "1")
    monkeypatch.setenv("BOB_ALLOW_SIGNUP", "0")
    monkeypatch.setenv("BOB_SEED_DEMO", "0")
    monkeypatch.setenv("BOB_CORS_ORIGINS", "https://suite.example.edu")


def test_production_configuration_is_closed_and_explicit(monkeypatch, tmp_path):
    _production(monkeypatch, tmp_path)
    settings = load_settings()
    assert settings.environment == "production"
    assert settings.database_url.startswith("postgresql+")
    assert settings.secure_cookies is True
    assert settings.allow_signup is False
    assert settings.seed_demo is False
    assert settings.auto_migrate is False


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("BOB_SEED_DEMO", "1", "BOB_SEED_DEMO must be 0"),
        ("BOB_ALLOW_SIGNUP", "1", "BOB_ALLOW_SIGNUP must be 0"),
        ("BOB_SECURE_COOKIES", "0", "BOB_SECURE_COOKIES must be 1"),
        ("BOB_BASE_IRI", "http://bob.example.edu", "BOB_BASE_IRI must use https://"),
        ("BOB_CORS_ORIGINS", "http://suite.example.edu", "BOB_CORS_ORIGINS"),
    ],
)
def test_production_refuses_unsafe_settings(monkeypatch, tmp_path, name, value, message):
    _production(monkeypatch, tmp_path)
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        load_settings()


def test_flags_refuse_ambiguous_values(monkeypatch, tmp_path):
    monkeypatch.setenv("BOB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BOB_ALLOW_SIGNUP", "yes")
    with pytest.raises(ValueError, match="BOB_ALLOW_SIGNUP must be 0 or 1"):
        load_settings()


def test_secret_file_and_environment_value_are_mutually_exclusive(monkeypatch, tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("file-secret", encoding="utf-8")
    monkeypatch.setenv("BOB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BOB_SECRET_KEY", "environment-secret")
    monkeypatch.setenv("BOB_SECRET_KEY_FILE", str(secret))
    with pytest.raises(ValueError, match="not both"):
        load_settings()
