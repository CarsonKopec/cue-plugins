# Cue plugins

Plugins for [Cue](https://github.com/CarsonKopec/Cue), the keyboard-driven terminal
media player. Cue installs them from this repository's catalog. In Cue, press `Esc`,
then `p`, and open the **Plugins** tab, or use a terminal:

```bash
cue plugin install anime
```

## What's here

| Plugin | Folder | Adds |
|---|---|---|
| HiAnime | [providers/anime](providers/anime/) | The `anime` provider, in the Anime group: the HiAnime catalog, SUB/DUB, server subtitles, auto-skip |
| HydraHD | [providers/hydra](providers/hydra/) | The `hydra` provider, in the Movies and Shows groups: movies and TV from HydraHD through its VixSrc server, with subtitles |
| ffplay | [players/ffplay](players/ffplay/) | The `ffplay` player: FFmpeg's player, started at your resume point with any headers a source needs |
| Default app | [players/default-app](players/default-app/) | The `default-app` player: local files open in your system's default video app |
| Addic7ed (Gestdown) | [subtitles/gestdown](subtitles/gestdown/) | The `gestdown` subtitle source: TV subtitles from Addic7ed through Gestdown's API, no key needed |
| SubDL | [subtitles/subdl](subtitles/subdl/) | The `subdl` subtitle source: movie and TV subtitles in many languages; needs a free API key from subdl.com |

Plugins are sorted by what they add: `providers/` for media sources, `players/` for
media players, `subtitles/` for subtitle sources. A new kind of plugin gets a new
top-level folder; the build picks it up.
Each plugin needs Cue 0.2.0 or newer (its `requires` says exactly which). Cue 0.3.0
and newer search by group, and providers here name their groups with a `groups`
attribute; a provider that returns both movies and series also sets `mixed_media = True`.
Subtitle sources need Cue 0.5.0 or newer, which searches every subtitle source that's set
up at once. Set them up (a SubDL key, say) in Cue's Plugins menu, on the **Subtitles** tab.

## How Cue gets them

Every push to `main` runs [the Catalog workflow](.github/workflows/catalog.yml). It:

1. checks every plugin,
2. zips each one as `<name>-<version>.zip`,
3. writes `index.json`, with each zip's SHA-256 and a checksum of the plugin's files,
4. uploads them to the release tagged [`catalog`](../../releases/tag/catalog).

Cue's default catalog is that release's `index.json`:

```
https://github.com/CarsonKopec/cue-plugins/releases/download/catalog/index.json
```

Cue refuses a download whose checksum doesn't match the index. A plugin that is
already installed is offered as an update when the catalog has a higher version.

## Changing a plugin

1. Edit it, then **raise `version` in its `plugin.toml`**. Without a new version,
   people who already have it never see the change, so the workflow refuses to
   publish a changed plugin with an old version.
2. Try it in Cue straight from this folder:

   ```bash
   cue plugin install providers/anime --yes
   ```

3. Run the tests, then push to `main`.

## Adding a plugin

Make a folder named after the plugin under `providers/`, `players/` or `subtitles/`,
with a `plugin.toml` and an `__init__.py`:

```toml
[plugin]
name = "my-plugin"            # the folder's name: lowercase letters, digits, - and _
version = "1.0.0"
title = "My Plugin"
description = "One line for Cue's Plugins menu."
author = "you"
homepage = "https://github.com/CarsonKopec/cue-plugins"
requires = "0.2.0"            # the oldest Cue it works with
providers = ["mine"]          # what it registers
players = []
subtitles = []                # subtitle sources (Cue 0.5.0 and newer)
```

A subtitle source registers a `SubtitleBackend` from `cue.subtitles.registry`, whose
`create(options, http, folder)` returns an object with a `name`, an async
`find(show, episode, languages, *, file_path=None)` returning `SubtitleTrack`s, and an
async `fetch(track)` returning the downloaded file's path. Settings it declares (an API
key with `required=True`, say) appear on Cue's Subtitles tab and are stored in
`[subtitles.<name>]`. [subtitles/gestdown](subtitles/gestdown/) is the smallest example.

[Cue's README](https://github.com/CarsonKopec/Cue#writing-a-plugin) covers the plugin
API: registering providers, players and subtitle sources, settings forms, the web toolkit for providers
that read web pages, and `ProcessPlayer` for programs Cue can't control. The plugins
here are working examples. Add tests for it under [tests/](tests/).

## Development

The tests need Cue installed; with Cue checked out next to this folder:

```bash
pip install -e ../Cue pytest pytest-asyncio
```

```bash
python -m pytest
```

[tests/conftest.py](tests/conftest.py) loads every plugin here the way Cue loads installed
plugins, so tests import them as `cue_plugins.<name>` (`cue_plugins.default_app` for
`default-app`). The tests use synthetic HTTP responses and need no network access.

To build the catalog locally into `dist/`, which needs only Python 3.11+:

```bash
python build.py
```

To point Cue at that local build, set `catalog` under `[plugins]` in its
`config.toml` to the path of `dist/index.json`.

## License

GPL-3.0, like Cue. See [LICENSE](LICENSE).
