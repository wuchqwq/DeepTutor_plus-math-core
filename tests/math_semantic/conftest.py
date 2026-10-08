"""Keep semantic regression generations offline at the existing provider port."""

import pytest

from .recovery_support import harmless_generation


@pytest.fixture(autouse=True)
def _isolated_math_generation(monkeypatch):
    monkeypatch.setattr(
        "deeptutor.services.llm.factory._complete_with_resolved_config", harmless_generation
    )
