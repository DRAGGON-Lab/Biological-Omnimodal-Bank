import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus


@dataclass(frozen=True)
class Settings:
    environment: str
    mode: str
    data_dir: Path
    database_url: str
    base_iri: str
    secret_key: str
    secure_cookies: bool
    allow_signup: bool
    seed_demo: bool
    auto_migrate: bool
    allowed_hosts: tuple[str, ...]
    # The only SynBioHub servers BOB will contact, so user input cannot point it at other hosts.
    synbiohub_instances: tuple[str, ...] = ("https://synbiohub.org",)
    # Web apps allowed to call BOB from the browser with an API token (never with cookies).
    cors_origins: tuple[str, ...] = ("https://synbiosuite.org",)

    @property
    def artifact_dir(self) -> Path:
        return self.data_dir / "artifacts"


def _from_file(name: str) -> str | None:
    """Read NAME or NAME_FILE, refusing ambiguous or empty secret configuration."""
    value, filename = os.environ.get(name), os.environ.get(name + "_FILE")
    if value and filename:
        raise ValueError(f"Set {name} or {name}_FILE, not both")
    if filename:
        try:
            value = Path(filename).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"Could not read {name}_FILE {filename!r}: {exc}") from exc
        if not value:
            raise ValueError(f"{name}_FILE {filename!r} is empty")
    return value


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw not in {"0", "1"}:
        raise ValueError(f"{name} must be 0 or 1")
    return raw == "1"


def _secret_key(data_dir: Path, production: bool) -> str:
    """Sessions must survive restarts, so a generated key is persisted beside the data."""
    env = _from_file("BOB_SECRET_KEY")
    if env:
        return env
    if production:
        raise ValueError("Production requires BOB_SECRET_KEY or BOB_SECRET_KEY_FILE")
    path = data_dir / "secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_urlsafe(48)
    path.write_text(key, encoding="utf-8")
    return key


def _database_url(data_dir: Path) -> str:
    configured = _from_file("DATABASE_URL")
    if configured:
        return configured
    password_file = os.environ.get("BOB_DB_PASSWORD_FILE")
    if password_file:
        try:
            password = Path(password_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"Could not read BOB_DB_PASSWORD_FILE {password_file!r}: {exc}") from exc
        if not password:
            raise ValueError(f"BOB_DB_PASSWORD_FILE {password_file!r} is empty")
        host = os.environ.get("BOB_DB_HOST", "db")
        port = os.environ.get("BOB_DB_PORT", "5432")
        name = os.environ.get("BOB_DB_NAME", "bob")
        user = os.environ.get("BOB_DB_USER", "bob")
        return f"postgresql+psycopg://{user}:{quote_plus(password)}@{host}:{port}/{name}"
    return f"sqlite:///{(data_dir / 'bob.db').as_posix()}"


def _validate_production(settings: Settings) -> None:
    problems = []
    if settings.seed_demo:
        problems.append("BOB_SEED_DEMO must be 0")
    if settings.allow_signup:
        problems.append("BOB_ALLOW_SIGNUP must be 0")
    if not settings.secure_cookies:
        problems.append("BOB_SECURE_COOKIES must be 1")
    if not settings.base_iri.startswith("https://"):
        problems.append("BOB_BASE_IRI must use https://")
    if settings.database_url.startswith("sqlite"):
        problems.append("production requires PostgreSQL; set DATABASE_URL or BOB_DB_PASSWORD_FILE")
    if not os.environ.get("BOB_ALLOWED_HOSTS"):
        problems.append("BOB_ALLOWED_HOSTS must be set explicitly")
    if any(not origin.startswith("https://") for origin in settings.cors_origins):
        problems.append("every BOB_CORS_ORIGINS entry must use https://")
    if problems:
        raise ValueError("Unsafe production configuration: " + "; ".join(problems))


def load_settings() -> Settings:
    environment = os.environ.get("BOB_ENV", "development").lower()
    if environment not in {"development", "production"}:
        raise ValueError(f"BOB_ENV must be 'development' or 'production', not {environment!r}")
    production = environment == "production"
    mode = os.environ.get("BOB_MODE", "full").lower()
    if mode not in {"full", "api"}:
        raise ValueError(f"BOB_MODE must be 'full' or 'api', not {mode!r}")
    data_dir = Path(os.environ.get("BOB_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "artifacts").mkdir(exist_ok=True)
    database_url = _database_url(data_dir)
    base_iri = os.environ.get("BOB_BASE_IRI", "http://localhost:8000").rstrip("/")
    settings = Settings(
        environment=environment,
        mode=mode,
        data_dir=data_dir,
        database_url=database_url,
        base_iri=base_iri,
        secret_key=_secret_key(data_dir, production),
        secure_cookies=_flag("BOB_SECURE_COOKIES", False),
        allow_signup=_flag("BOB_ALLOW_SIGNUP", not production),
        seed_demo=_flag("BOB_SEED_DEMO", False),
        auto_migrate=_flag("BOB_AUTO_MIGRATE", not production),
        allowed_hosts=tuple(h.strip() for h in os.environ.get("BOB_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()),
        synbiohub_instances=tuple(u.strip().rstrip("/") for u in os.environ.get("BOB_SYNBIOHUB_INSTANCES", "https://synbiohub.org").split(",") if u.strip()),
        cors_origins=tuple(u.strip().rstrip("/") for u in os.environ.get("BOB_CORS_ORIGINS", "https://synbiosuite.org").split(",") if u.strip()),
    )
    if production:
        _validate_production(settings)
    return settings
