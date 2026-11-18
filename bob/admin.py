"""One-time administrative commands for a new BOB server."""

import argparse
import getpass
import sys

from sqlalchemy import func, select

from bob import migrate, services
from bob.config import Settings, load_settings
from bob.db import make_engine, make_sessionmaker
from bob.models import User
from bob.security import hash_password


def bootstrap_owner(settings: Settings, email: str, name: str, workspace: str, password: str) -> User:
    """Create the first account and lab workspace, refusing to run on an initialized server."""
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters")
    engine = make_engine(settings.database_url)
    if not migrate.is_current(engine):
        raise ValueError("Database migrations are not current; run python -m bob.migrate first")
    sessionmaker = make_sessionmaker(engine)
    with sessionmaker() as db:
        if db.scalar(select(func.count()).select_from(User)):
            raise ValueError("This server already has an account; bootstrap-owner can run only once")
        user, lab = services.create_user(db, email, name, password)
        lab.name = workspace.strip()
        lab.slug = services.unique_slug(db, workspace)
        db.commit()
        db.refresh(user)
        return user


def create_managed_user(settings: Settings, email: str, name: str, password: str) -> User:
    """Create a server-managed account without giving it an unmanaged personal workspace."""
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters")
    email, name = email.strip().lower(), name.strip()
    if not email or "@" not in email or not name:
        raise ValueError("A valid email address and non-empty name are required")
    engine = make_engine(settings.database_url)
    if not migrate.is_current(engine):
        raise ValueError("Database migrations are not current; run python -m bob.migrate first")
    sessionmaker = make_sessionmaker(engine)
    with sessionmaker() as db:
        if db.scalar(select(User.id).where(User.email == email)):
            raise ValueError("An account with this email already exists")
        user = User(email=email, name=name, password_hash=hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BOB server administration")
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser("bootstrap-owner", help="create the first PI account and lab workspace")
    bootstrap.add_argument("--email", required=True)
    bootstrap.add_argument("--name", required=True)
    bootstrap.add_argument("--workspace", required=True)
    managed = commands.add_parser("create-user", help="create a managed account without a personal workspace")
    managed.add_argument("--email", required=True)
    managed.add_argument("--name", required=True)
    return parser


def _password() -> str | None:
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        print("Passwords do not match", file=sys.stderr)
        return None
    return password


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command in {"bootstrap-owner", "create-user"}:
        password = _password()
        if password is None:
            return 2
        try:
            if args.command == "bootstrap-owner":
                user = bootstrap_owner(load_settings(), args.email, args.name, args.workspace, password)
            else:
                user = create_managed_user(load_settings(), args.email, args.name, password)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.command == "bootstrap-owner":
            print(f"Created {user.email} as owner of {args.workspace.strip()}")
        else:
            print(f"Created managed account {user.email}; invite it to a workspace before use")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
