"""The version is written in several files; they must agree (scripts/bump_version.py keeps them so)."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("bump_version", ROOT / "scripts" / "bump_version.py")
bump = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump)


def test_every_copy_of_the_version_agrees():
    versions = bump.current_versions()
    assert len(set(versions.values())) == 1, versions


@pytest.fixture
def tree(tmp_path):
    for rel in ("pyproject.toml", "src/secretary/__init__.py", "packaging/version_info.txt", "packaging/installer.iss"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    return tmp_path


def test_set_version_rewrites_every_copy(tree):
    bump.set_version("1.2.3", tree)
    versions = bump.current_versions(tree)
    assert set(versions.values()) == {"1.2.3"}, versions


def test_set_version_keeps_line_endings_and_other_content(tree):
    before = (tree / "pyproject.toml").read_bytes()
    current = bump.current_versions(tree)["pyproject.toml"].encode()
    bump.set_version("9.8.7", tree)
    after = (tree / "pyproject.toml").read_bytes()
    assert (b"\r\n" in before) == (b"\r\n" in after)
    assert after.replace(b"9.8.7", current) == before  # only the version text changed
    assert len(after.splitlines()) == len(before.splitlines())


@pytest.mark.parametrize("bad", ["1.2", "v1.2.3", "1.2.3-rc1", "", "abc"])
def test_set_version_rejects_anything_but_major_minor_patch(tree, bad):
    with pytest.raises(ValueError):
        bump.set_version(bad, tree)
    assert len(set(bump.current_versions(tree).values())) == 1  # nothing was half-written
