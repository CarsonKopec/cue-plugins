"""build.py: every plugin is valid, zips are reproducible, and changed plugins need a new version."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

import build
from cue.plugins.catalog import parse_catalog
from cue.plugins.manifest import read_manifest


def test_every_plugin_is_valid_for_cue() -> None:
    plugins = build.entries()
    assert {entry["category"] for entry, _ in plugins} == {"providers", "players"}
    for entry, folder in plugins:
        manifest = read_manifest(folder)  # Cue's own check
        assert (manifest.name, manifest.version) == (entry["name"], entry["version"])
        assert entry["providers"] if entry["category"] == "providers" else entry["players"]


def test_build_is_reproducible_and_readable_by_cue(tmp_path: Path) -> None:
    first = build.build(tmp_path / "a")
    second = build.build(tmp_path / "b")
    assert [entry["sha256"] for entry in first] == [entry["sha256"] for entry in second]
    index = json.loads((tmp_path / "a" / "index.json").read_text(encoding="utf-8"))
    catalog = parse_catalog(index, "https://github.com/o/cue-plugins/releases/download/catalog/index.json")
    assert {entry.manifest.name for entry in catalog} == {entry["name"] for entry in first}
    assert catalog[0].url.startswith("https://github.com/o/cue-plugins/releases/download/catalog/")
    with zipfile.ZipFile(tmp_path / "a" / first[0]["url"]) as bundle:
        names = bundle.namelist()
    assert "plugin.toml" in names and not any("__pycache__" in name for name in names)


class _Published(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_changed_plugin_needs_a_new_version(monkeypatch: pytest.MonkeyPatch) -> None:
    built = [entry for entry, _ in build.entries()]
    same = {"plugins": built}
    changed = {"plugins": [{**built[0], "content": "0" * 64}, *built[1:]]}
    newer = {"plugins": [{**built[0], "version": "0.9.0", "content": "0" * 64}, *built[1:]]}

    def serve(document):
        monkeypatch.setattr(build.urllib.request, "urlopen",
                            lambda url, timeout: _Published(json.dumps(document).encode()))

    serve(same)
    build.check_versions(built, "https://example.test/index.json")
    serve(newer)  # an older published version with other files is fine
    build.check_versions(built, "https://example.test/index.json")
    serve(changed)
    with pytest.raises(SystemExit, match=f"changed without a new version: {built[0]['name']}"):
        build.check_versions(built, "https://example.test/index.json")
