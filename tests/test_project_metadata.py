import tomllib
from pathlib import Path

from bob import __version__


def test_project_and_application_versions_match():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__
