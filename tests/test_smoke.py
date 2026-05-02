"""Smoke test: package imports cleanly and version is exposed."""

import src


def test_package_version_exposed() -> None:
    assert isinstance(src.__version__, str)
    assert src.__version__ != ""
