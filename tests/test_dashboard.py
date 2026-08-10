"""Tests for the local control panel."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from whisper_typing import dashboard
from whisper_typing.dashboard import DashboardServer, install_loader, list_loaders


def test_every_bundled_loader_is_offered_with_its_kind() -> None:
    """Test the picker sees the shipped packs and knows which ones are video."""
    loaders = list_loaders()

    assert loaders
    groups = {item["group"] for item in loaders}
    assert {"bazed", "markaryan", "emotes", "parrots"} <= groups
    assert all("/" in item["id"] for item in loaders)
    assert {item["kind"] for item in loaders} <= {"video", "image"}


def test_a_loader_id_cannot_escape_the_assets_folder() -> None:
    """Test the panel refuses to serve arbitrary files off the disk."""
    assert dashboard._safe_loader_path("../../overlay.py") is None  # noqa: SLF001
    assert dashboard._safe_loader_path("bazed/../../__main__.py") is None  # noqa: SLF001
    assert dashboard._safe_loader_path("nope/nope.gif") is None  # noqa: SLF001


def test_installing_a_loader_rewrites_the_single_animation_file(tmp_path: Path) -> None:
    """Test picking a loader replaces exactly the file the overlay reads."""
    source_dir = tmp_path / "loaders" / "pack"
    source_dir.mkdir(parents=True)
    source = source_dir / "one.gif"
    source.write_bytes(b"GIF89a-not-really")
    target = tmp_path / "processing.png"

    with (
        patch.object(dashboard, "LOADERS_DIR", tmp_path / "loaders"),
        patch.object(dashboard, "PROCESSING_ASSET", target),
        patch.object(dashboard.subprocess, "run", side_effect=OSError("no ffmpeg")),
    ):
        install_loader("pack/one.gif")

    # ffmpeg is unavailable here, so the raw copy path must still deliver a file.
    assert target.read_bytes() == b"GIF89a-not-really"


def test_an_unknown_loader_is_rejected_before_touching_the_overlay() -> None:
    """Test a bad id cannot blank out the running animation."""
    target = Path("should-never-be-written.png")

    with (
        patch.object(dashboard, "PROCESSING_ASSET", target),
        pytest.raises(ValueError, match="unknown loader"),
    ):
        install_loader("does/not-exist.gif")

    assert not target.exists()


def test_the_panel_binds_to_loopback_only() -> None:
    """Test the settings API is never exposed to the network."""
    controller = MagicMock()
    server = DashboardServer(controller, port=8791)
    try:
        url = server.start()
        assert url.startswith("http://127.0.0.1:")
        assert server._server is not None  # noqa: SLF001
        assert server._server.server_address[0] == "127.0.0.1"  # noqa: SLF001
    finally:
        server.stop()
