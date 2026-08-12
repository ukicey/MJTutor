from __future__ import annotations

import json
import os
from pathlib import Path

import mjtutor
from mjtutor.service import default_database_path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "mjtutor"


def test_plugin_and_python_versions_match() -> None:
    manifest = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == mjtutor.__version__


def test_plugin_is_the_only_codex_runtime_surface() -> None:
    assert not (ROOT / ".codex" / "config.toml").exists()
    project_skills = ROOT / ".agents" / "skills"
    assert not project_skills.exists() or not any(
        path.is_file() for path in project_skills.rglob("*")
    )
    assert (PLUGIN_ROOT / "skills" / "coach-mahjong-soul" / "SKILL.md").is_file()
    assert (PLUGIN_ROOT / ".mcp.json").is_file()
    assert (PLUGIN_ROOT / "assets" / "game-catalog.html").is_file()


def test_marketplace_points_to_plugin() -> None:
    marketplace = json.loads(
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(
            encoding="utf-8"
        )
    )
    assert marketplace["name"] == "mjtutor"
    assert marketplace["plugins"][0]["source"] == {
        "source": "local",
        "path": "./plugins/mjtutor",
    }


def test_default_database_lives_outside_plugin(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("MJTUTOR_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", os.fspath(tmp_path))
    assert default_database_path() == tmp_path / "mjtutor" / "coach.sqlite3"
    assert PLUGIN_ROOT not in default_database_path().parents


def test_launcher_uses_uv_and_external_data_directory() -> None:
    launcher = (PLUGIN_ROOT / "bin" / "mjtutor-mcp").read_text(encoding="utf-8")
    assert "MJTUTOR_DATA_DIR" in launcher
    assert '--with "mcp>=2.0,<3"' in launcher
    assert "--isolated" in launcher


def test_mcp_app_resource_is_packaged_and_registered() -> None:
    server = (PLUGIN_ROOT / "src" / "mjtutor" / "mcp_server.py").read_text(
        encoding="utf-8"
    )
    app = (PLUGIN_ROOT / "assets" / "game-catalog.html").read_text(
        encoding="utf-8"
    )
    assert 'CATALOG_URI = "ui://mjtutor/game-catalog.html"' in server
    assert "Apps()" in server
    assert "tools/call" in app
    assert "query_game_catalog" in app
    assert "sendFollowUpMessage" in app


def test_catalog_tool_keeps_game_rows_out_of_model_content(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MJTUTOR_DATA_DIR", str(tmp_path))
    from mjtutor import mcp_server

    result = mcp_server._catalog_tool_result(
        {
            "items": [{"uuid": "private-game-row"}],
            "total": 1,
            "limit": 20,
            "offset": 0,
            "has_more": False,
            "sync_status": {"accounts": []},
            "catalog_notice": "notice",
        }
    )

    assert "items" not in result.structured_content
    assert result.meta["mjtutor/catalog"]["items"][0]["uuid"] == "private-game-row"
    assert "private-game-row" not in result.content[0].text
