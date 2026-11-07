"""Placeholder test so pytest runs on the empty package (P0-01)."""

import secretary


def test_package_imports():
    assert secretary.__version__ == "0.1.0"
