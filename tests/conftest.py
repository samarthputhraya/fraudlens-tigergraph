"""Every test writes its audit entries to a temporary folder, never to the real runs/audit log."""
from __future__ import annotations

import pytest

from agent import safety


@pytest.fixture(autouse=True)
def _isolated_audit_log(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "AUDIT_DIR", tmp_path / "audit")
