"""Docker-backed tests run only when the pure-ftpd containers are reachable."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("GIT_FTP_TEST_FTP_ADDR"):
        return
    skip = pytest.mark.skip(reason="GIT_FTP_TEST_FTP_ADDR not set (docker job only)")
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip)
