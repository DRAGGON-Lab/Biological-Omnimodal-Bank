import pytest
from sqlalchemy import select

from bob import migrate
from bob.admin import bootstrap_owner, create_managed_user
from bob.config import load_settings
from bob.db import make_engine, make_sessionmaker
from bob.models import Membership, User, Workspace


def test_bootstrap_owner_creates_exactly_one_lab_owner(data_dir):
    settings = load_settings()
    engine = make_engine(settings.database_url)
    migrate.upgrade(engine)

    user = bootstrap_owner(settings, "pi@lab.test", "Principal Investigator", "Example Lab", "correct horse")
    with make_sessionmaker(engine)() as db:
        membership = db.scalar(select(Membership).where(Membership.user_id == user.id))
        workspace = db.get(Workspace, membership.workspace_id)
        assert membership.role == "owner"
        assert workspace.name == "Example Lab"

    with pytest.raises(ValueError, match="only once"):
        bootstrap_owner(settings, "other@lab.test", "Other", "Other Lab", "correct horse")


def test_bootstrap_owner_refuses_a_short_password(data_dir):
    settings = load_settings()
    engine = make_engine(settings.database_url)
    migrate.upgrade(engine)
    with pytest.raises(ValueError, match="at least 8"):
        bootstrap_owner(settings, "pi@lab.test", "PI", "Lab", "short")


def test_create_managed_user_has_no_unmanaged_workspace(data_dir):
    settings = load_settings()
    engine = make_engine(settings.database_url)
    migrate.upgrade(engine)

    user = create_managed_user(settings, " Student@Example.Test ", " Student ", "temporary horse")

    with make_sessionmaker(engine)() as db:
        assert db.get(User, user.id).email == "student@example.test"
        assert db.scalar(select(Membership).where(Membership.user_id == user.id)) is None

    with pytest.raises(ValueError, match="already exists"):
        create_managed_user(settings, "student@example.test", "Student", "temporary horse")
