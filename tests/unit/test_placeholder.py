"""Placeholder test so pytest runs on the empty package (P0-01)."""

import re

import secretary


def test_package_imports():
    assert re.fullmatch(r"\d+\.\d+\.\d+", secretary.__version__)  # the exact value is bump_version.py's job
