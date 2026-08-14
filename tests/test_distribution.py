from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

import mjtutor
from mjtutor.service import CoachService, default_database_path
from mjtutor.storage import ReviewRepository

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "mjtutor"


def test_distribution_versions_match() -> None:
    manifest = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert manifest["version"] == project["project"]["version"] == mjtutor.__version__


def test_plugin_starter_prompts_fit_host_limits() -> None:
    manifest = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    prompts = manifest["interface"]["defaultPrompt"]
    assert 1 <= len(prompts) <= 3
    assert all(len(prompt) <= 128 for prompt in prompts)


def test_user_entry_points_do_not_expose_internal_guardrails() -> None:
    manifest = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    entry_points = "\n".join(manifest["interface"]["defaultPrompt"])
    skill_metadata = (
        PLUGIN_ROOT / "skills" / "coach-mahjong-soul" / "agents" / "openai.yaml"
    )
    entry_points += skill_metadata.read_text(encoding="utf-8")
    assert "不要开始教学" not in entry_points
    assert "without starting a coaching review" not in entry_points


def test_profile_payload_does_not_repeat_coaching_policy(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MJTUTOR_DATA_DIR", os.fspath(tmp_path))
    from mjtutor.storage import ReviewRepository

    profile = ReviewRepository(tmp_path / "coach.sqlite3").coaching_profile()
    assert "notice" not in profile
    assert "interpretation_notice" not in profile["observation_summary"]


def test_decision_payload_does_not_repeat_evidence_policy() -> None:
    from mjtutor.models import ReviewDocument

    review = ReviewDocument.from_json(
        json.loads(
            (ROOT / "tests" / "fixtures" / "sample_review.json").read_text(
                encoding="utf-8"
            )
        )
    )
    decision = review.get_decision("k0.0:d0").as_dict()
    assert "evidence_notice" not in decision


def test_plugin_brand_assets_are_packaged() -> None:
    manifest = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    interface = manifest["interface"]
    assert interface["brandColor"] == "#16735B"
    for field, dimensions in (("composerIcon", (32, 32)), ("logo", (512, 512))):
        asset = PLUGIN_ROOT / interface[field].removeprefix("./")
        assert asset.is_file()
        png = asset.read_bytes()
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert (
            int.from_bytes(png[16:20], "big"),
            int.from_bytes(png[20:24], "big"),
        ) == dimensions


def test_example_environment_matches_runtime_defaults() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "~/.local/share/mjtutor" in example
    assert "./data inside this project" not in example
    assert "MJTUTOR_KOROMO_TOKEN" in example
    assert "MJTUTOR_REVIEWER_BIN" not in example
    assert "MJTUTOR_MORTAL_EXE" not in example
    assert "MJTUTOR_MORTAL_CONFIG" not in example
    assert "MJTUTOR_TIMEOUT_SECONDS" not in example


def test_setup_only_reports_current_analysis_providers(tmp_path: Path) -> None:
    setup = CoachService(
        repository=ReviewRepository(tmp_path / "coach.sqlite3")
    ).check_setup()

    assert "reviewer" not in setup
    assert set(setup["providers"]) == {"mortal_web", "koromo_catalog"}
    assert setup["scope"]["source"] == "Mahjong Soul HTTPS paipu URLs"


def test_plugin_does_not_expose_removed_local_mortal_tools() -> None:
    server = (PLUGIN_ROOT / "src" / "mjtutor" / "mcp_server.py").read_text(
        encoding="utf-8"
    )
    skill = (PLUGIN_ROOT / "skills" / "coach-mahjong-soul" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    for removed_name in (
        "inspect_majsoul_log",
        "review_majsoul_hanchan",
        "import_mjai_review",
        "bind_koromo_account",
    ):
        assert f"def {removed_name}(" not in server
        assert f"`{removed_name}`" not in skill
    assert "def bind_majsoul_account(" in server
    assert not (PLUGIN_ROOT / "src" / "mjtutor" / "reviewer.py").exists()


def test_user_facing_account_terms_identify_mahjong_soul_account() -> None:
    server = (PLUGIN_ROOT / "src" / "mjtutor" / "mcp_server.py").read_text(
        encoding="utf-8"
    )
    skill = (PLUGIN_ROOT / "skills" / "coach-mahjong-soul" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    chinese_readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Mahjong Soul profile" in server
    assert "profile UID" in skill
    assert "个人资料”中显示的 UID" in chinese_readme
    assert "牌谱屋内部账号 ID" in chinese_readme


def test_skill_rechecks_async_turnstile_state_before_handoff() -> None:
    skill = (PLUGIN_ROOT / "skills" / "coach-mahjong-soul" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "first review form under `Review your game` or `检讨牌谱`" in skill
    assert "ignore the later `Dispatch a private room` or `派遣个室` form" in skill
    assert "up to 10 seconds at 500-1000 ms intervals" in skill
    assert "button's live `disabled` property" in skill
    assert "Immediately before deciding or clicking" in skill
    assert "this state alone does not reveal whether Turnstile" in skill
    assert "involve the user only if the review button remains unavailable" in skill


def test_mcp_server_reports_package_version(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MJTUTOR_DATA_DIR", os.fspath(tmp_path))
    from mjtutor import mcp_server

    assert mcp_server.mcp.version == mjtutor.__version__


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
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
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
    assert '--with "mahjong>=2.0,<3"' in launcher
    assert '--with "mcp>=2.0,<3"' in launcher
    assert "--isolated" in launcher
    assert "--no-project" in launcher


def test_tile_efficiency_tool_and_skill_guard_are_packaged() -> None:
    server = (PLUGIN_ROOT / "src" / "mjtutor" / "mcp_server.py").read_text(
        encoding="utf-8"
    )
    skill = (PLUGIN_ROOT / "skills" / "coach-mahjong-soul" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "def analyze_tile_efficiency(" in server
    assert "call `analyze_tile_efficiency`" in skill
    assert "Never reconstruct an acceptance count" in skill


def test_readmes_describe_deterministic_tile_efficiency() -> None:
    assert "确定性牌形算法" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert "deterministic hand-shape engine" in (ROOT / "README.en.md").read_text(
        encoding="utf-8"
    )
    assert "決定論的な牌姿計算" in (ROOT / "README.ja.md").read_text(encoding="utf-8")


def test_mcp_app_resource_is_packaged_and_registered() -> None:
    server = (PLUGIN_ROOT / "src" / "mjtutor" / "mcp_server.py").read_text(
        encoding="utf-8"
    )
    app = (PLUGIN_ROOT / "assets" / "game-catalog.html").read_text(encoding="utf-8")
    assert 'CATALOG_URI = "ui://mjtutor/game-catalog.html"' in server
    assert "Apps()" in server
    assert "tools/call" in app
    assert "query_game_catalog" in app
    assert "sendFollowUpMessage" in app
    assert "get_review_viewer" in server
    assert 'game.reviewed ? "看牌" : "复盘"' in app
    assert "不要重新提交 Mortal，并在侧边浏览器打开看牌页面" in app
    assert 'window.location.protocol === "file:"' in app
    assert "这是插件界面文件，不能直接打开" in app
    assert "未收到牌局目录数据" in app


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
