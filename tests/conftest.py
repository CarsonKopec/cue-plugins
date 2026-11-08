"""Load the plugins in this repo the way Cue does, so tests can import cue_plugins.<name>.

Needs Cue 0.2 or newer installed (pip install -e path/to/Cue, or from GitHub).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cue.plugins import PluginManager
from cue.store import Store

ROOT = Path(__file__).resolve().parent.parent

for category in ("providers", "players", "subtitles"):
    for _plugin in PluginManager(ROOT / category).load_enabled():
        assert _plugin.loaded, f"{_plugin.name}: {_plugin.error}"


@pytest.fixture(autouse=True)
def cue_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep tests away from the real %APPDATA%\\cue."""
    home = tmp_path / "cue-home"
    monkeypatch.setenv("CUE_HOME", str(home))
    return home


@pytest.fixture
def store():
    db = Store(":memory:")
    yield db
    db.close()
