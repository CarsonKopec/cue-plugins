"""Build the plugin catalog: dist/<name>-<version>.zip for every plugin, and dist/index.json.

    python build.py                      # build dist/
    python build.py --check              # only check the plugins
    python build.py --published URL      # also refuse changed plugins whose version wasn't raised

Plugins live one folder deep in a category folder (providers/, players/, ...). Only the
standard library is used, so this runs without Cue installed. Zips are reproducible:
the same files always give the same zip on the same Python, so an unchanged plugin
keeps its checksum. index.json links the zips relatively, so it and the zips are
published side by side (the GitHub release tagged ``catalog``).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import sys
import tomllib
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOT_CATEGORIES = {"tests", "dist", "build"}
NAME = re.compile(r"[a-z][a-z0-9_-]{0,39}")
VERSION = re.compile(r"\d{1,6}(?:\.\d{1,6}){0,3}")
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def plugin_folders(root: Path = ROOT) -> list[tuple[str, Path]]:
    """(category, folder) for every plugin, sorted."""
    found = []
    for category in sorted(p for p in root.iterdir() if p.is_dir()):
        if category.name.startswith(".") or category.name in NOT_CATEGORIES:
            continue
        for folder in sorted(p for p in category.iterdir() if (p / "plugin.toml").is_file()):
            found.append((category.name, folder))
    return found


def packable_files(folder: Path) -> list[Path]:
    return sorted(
        path for path in folder.rglob("*")
        if path.is_file() and path.suffix != ".pyc"
        and not any(part == "__pycache__" or part.startswith(".") for part in path.relative_to(folder).parts)
    )


def read_manifest(folder: Path) -> dict:
    """The [plugin] table, checked the way Cue checks it."""
    where = folder.relative_to(ROOT).as_posix()
    with (folder / "plugin.toml").open("rb") as f:
        table = tomllib.load(f).get("plugin")
    if not isinstance(table, dict):
        raise SystemExit(f"{where}: plugin.toml has no [plugin] table")
    name, version = table.get("name"), table.get("version")
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise SystemExit(f"{where}: name must be lowercase letters, digits, - or _")
    if name != folder.name:
        raise SystemExit(f"{where}: the folder must be named after the plugin ({name})")
    for key in ("version", "requires"):
        value = table.get(key, "0" if key == "requires" else None)
        if not isinstance(value, str) or not VERSION.fullmatch(value):
            raise SystemExit(f"{where}: {key} must be a version number like 1.2.0")
    for key in ("providers", "players"):
        names = table.get(key, [])
        if not isinstance(names, list) or not all(isinstance(item, str) and item for item in names):
            raise SystemExit(f"{where}: {key} must be a list of names")
    if not table.get("providers") and not table.get("players"):
        raise SystemExit(f"{where}: list the providers or players it adds")
    if not (folder / "__init__.py").is_file():
        raise SystemExit(f"{where}: __init__.py is missing")
    return table


def content_digest(folder: Path) -> str:
    """A checksum of the plugin's files themselves, whatever the zip compression does."""
    digest = hashlib.sha256()
    for path in packable_files(folder):
        digest.update(path.relative_to(folder).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def pack(folder: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in packable_files(folder):
            info = zipfile.ZipInfo(path.relative_to(folder).as_posix(), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            bundle.writestr(info, path.read_bytes())
    return buffer.getvalue()


def entries(root: Path = ROOT) -> list[tuple[dict, Path]]:
    """Catalog entries (without checksums of the zips yet) and their folders."""
    result, seen = [], {}
    for category, folder in plugin_folders(root):
        table = read_manifest(folder)
        name = table["name"]
        if name in seen:
            raise SystemExit(f"{name} is in both {seen[name]} and {category}")
        seen[name] = category
        result.append(({
            "name": name,
            "version": table["version"],
            "title": table.get("title", name),
            "description": table.get("description", ""),
            "author": table.get("author", ""),
            "homepage": table.get("homepage", ""),
            "requires": table.get("requires", "0"),
            "category": category,
            "providers": list(table.get("providers", [])),
            "players": list(table.get("players", [])),
            "url": f"{name}-{table['version']}.zip",
            "content": content_digest(folder),
        }, folder))
    if not result:
        raise SystemExit("no plugins found")
    return result


def check_versions(built: list[dict], published_url: str) -> None:
    """Refuse a plugin whose files changed while its version stayed the same."""
    try:
        with urllib.request.urlopen(published_url, timeout=30) as response:
            published = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print("No published catalog yet; nothing to compare.")
            return
        raise
    old = {(entry.get("name"), entry.get("version")): entry.get("content") for entry in published.get("plugins", [])}
    stale = [entry["name"] for entry in built
             if old.get((entry["name"], entry["version"])) not in (None, entry["content"])]
    if stale:
        raise SystemExit(f"changed without a new version: {', '.join(stale)}. Raise version in their plugin.toml.")


def build(output: Path = ROOT / "dist", published: str | None = None) -> list[dict]:
    built = []
    plugins = entries()
    if published:
        check_versions([entry for entry, _ in plugins], published)
    output.mkdir(parents=True, exist_ok=True)
    for stale in output.glob("*.zip"):
        stale.unlink()
    for entry, folder in plugins:
        data = pack(folder)
        (output / entry["url"]).write_bytes(data)
        entry["sha256"] = hashlib.sha256(data).hexdigest()
        built.append(entry)
        print(f"{entry['category']}/{entry['name']} {entry['version']}  {entry['sha256']}")
    (output / "index.json").write_text(json.dumps({"plugins": built}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output / 'index.json'} ({len(built)} plugins)")
    return built


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="check the plugins without building")
    parser.add_argument("--published", metavar="URL", help="the published index.json to compare versions with")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    if args.check:
        plugins = entries()
        print(f"{len(plugins)} plugins OK: {', '.join(entry['name'] for entry, _ in plugins)}")
        return 0
    build(args.output, args.published)
    return 0


if __name__ == "__main__":
    sys.exit(main())
