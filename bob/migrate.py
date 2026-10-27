"""Schema migrations. `python -m bob.migrate revision "message"` records a new one."""

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(engine: Engine) -> None:
    cfg = alembic_config(engine.url.render_as_string(hide_password=False))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


def main(argv: list[str]) -> int:
    from bob.config import load_settings

    settings = load_settings()
    cfg = alembic_config(settings.database_url)
    if argv[:1] == ["revision"]:
        command.revision(cfg, message=argv[1] if len(argv) > 1 else "change", autogenerate=True)
    else:
        command.upgrade(cfg, "head")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
