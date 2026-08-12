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
