"""Which search groups the plugins' providers belong to."""

from __future__ import annotations


def test_providers_declare_their_groups() -> None:
    from cue_plugins.anime import AnimeProvider
    from cue_plugins.hydra import HydraProvider

    assert AnimeProvider.groups == ("anime",)
    # HydraHD lists movies and series together, so Cue splits them between Movies and Shows.
    assert HydraProvider.groups == ("movies", "shows") and HydraProvider.mixed_media
