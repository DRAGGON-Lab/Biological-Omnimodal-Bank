import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    mode: str
    data_dir: Path
    database_url: str
    base_iri: str
    secret_key: str
    secure_cookies: bool
    allow_signup: bool
    allowed_hosts: tuple[str, ...]
    # The only SynBioHub servers BOB will contact, so user input cannot point it at other hosts.
    synbiohub_instances: tuple[str, ...] = ("https://synbiohub.org",)
    # Web apps allowed to call BOB from the browser with an API token (never with cookies).
    cors_origins: tuple[str, ...] = ("https://synbiosuite.org",)

    @property
    def artifact_dir(self) -> Path:
        return self.data_dir / "artifacts"


def _secret_key(data_dir: Path) -> str:
    """Sessions must survive restarts, so a generated key is persisted beside the data."""
    env = os.environ.get("BOB_SECRET_KEY")
    if env:
        return env
    path = data_dir / "secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_urlsafe(48)
    path.write_text(key, encoding="utf-8")
    return key


def load_settings() -> Settings:
    mode = os.environ.get("BOB_MODE", "full").lower()
    if mode not in {"full", "api"}:
        raise ValueError(f"BOB_MODE must be 'full' or 'api', not {mode!r}")
    data_dir = Path(os.environ.get("BOB_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "artifacts").mkdir(exist_ok=True)
    database_url = os.environ.get("DATABASE_URL", f"sqlite:///{(data_dir / 'bob.db').as_posix()}")
    base_iri = os.environ.get("BOB_BASE_IRI", "http://localhost:8000").rstrip("/")
    return Settings(
        mode=mode,
        data_dir=data_dir,
        database_url=database_url,
        base_iri=base_iri,
        secret_key=_secret_key(data_dir),
        secure_cookies=os.environ.get("BOB_SECURE_COOKIES", "0") == "1",
        allow_signup=os.environ.get("BOB_ALLOW_SIGNUP", "1") == "1",
        allowed_hosts=tuple(h.strip() for h in os.environ.get("BOB_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()),
        synbiohub_instances=tuple(u.strip().rstrip("/") for u in os.environ.get("BOB_SYNBIOHUB_INSTANCES", "https://synbiohub.org").split(",") if u.strip()),
        cors_origins=tuple(u.strip().rstrip("/") for u in os.environ.get("BOB_CORS_ORIGINS", "https://synbiosuite.org").split(",") if u.strip()),
    )
