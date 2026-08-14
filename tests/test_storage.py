import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from mjtutor.errors import CoachError
from mjtutor.koromo import encode_paipu_account_id
from mjtutor.logs import LogMetadata, inspect_tenhou_v6_log
from mjtutor.models import ReviewDocument
from mjtutor.service import make_review_id
from mjtutor.storage import ReviewRepository

FIXTURES = Path(__file__).parent / "fixtures"


def _review_fixture() -> tuple[LogMetadata, ReviewDocument, dict[str, object]]:
    metadata = inspect_tenhou_v6_log(FIXTURES / "sample_hanchan.json")
    raw = json.loads((FIXTURES / "sample_review.json").read_text(encoding="utf-8"))
    return metadata, ReviewDocument.from_json(raw), raw


def _paipu_metadata(metadata: LogMetadata, koromo_account_id: int) -> LogMetadata:
    encoded = encode_paipu_account_id(koromo_account_id)
    return replace(
        metadata,
        path=f"https://game.maj-soul.com/1/?paipu=260618-example_a{encoded}",
    )


def test_review_feedback_and_observations_are_local_without_account(
    tmp_path: Path,
) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    metadata, review, _ = _review_fixture()
    review_id = make_review_id(metadata, 0)

    assert (
        repository.save_review(
            review_id=review_id,
            metadata=metadata,
            player_id=0,
            review=review,
        )
        is None
    )
    note = repository.add_note(
        review_id=review_id,
        decision_id="k0.0:d0",
        kind="mistake",
        category="tile_efficiency",
        note="Held the pair without comparing shapes.",
    )

    assert repository.list_reviews()[0]["id"] == review_id
    assert repository.get_review(review_id).model_tag == "mortal-test"
    assert repository.observation_summary()["decision_count"] == 2
    assert repository.list_observations(disagreements_only=False)["total"] == 2
    assert note["category"] == "tile_efficiency"
    profile = repository.coaching_profile()
    assert profile["local_profile"]["id"] == 1
    assert profile["explicit_note_counts"][0]["count"] == 1


def test_review_preserves_mortal_report_url(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    metadata, review, _ = _review_fixture()
    review_id = make_review_id(metadata, 0)
    report_url = "https://mjai.ekyu.moe/report/synthetic.json"

    repository.save_review(
        review_id=review_id,
        metadata=metadata,
        player_id=0,
        review=review,
        report_json_url=report_url,
    )

    assert repository.get_review_metadata(review_id)["report_json_url"] == report_url
    assert repository.list_reviews()[0]["report_json_url"] == report_url


def test_local_settings_round_trip_and_delete(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")

    assert repository.get_local_setting("default_mortal_model") is None
    saved = repository.set_local_setting("default_mortal_model", "4.1c")

    assert saved["value"] == "4.1c"
    assert repository.get_local_setting("default_mortal_model") == "4.1c"
    assert repository.delete_local_setting("default_mortal_model") is True
    assert repository.delete_local_setting("default_mortal_model") is False
    assert repository.get_local_setting("default_mortal_model") is None


def test_account_binding_backfills_provenance_and_tracks_nicknames(
    tmp_path: Path,
) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    metadata, review, _ = _review_fixture()
    majsoul_uid = 12_345_678
    koromo_account_id = 8_765_432
    metadata = _paipu_metadata(metadata, koromo_account_id)
    review_id = make_review_id(metadata, 0)
    repository.save_review(
        review_id=review_id,
        metadata=metadata,
        player_id=0,
        review=review,
    )

    account = repository.bind_majsoul_account(
        nickname="Asapin",
        majsoul_uid=majsoul_uid,
        koromo_account_id=koromo_account_id,
    )

    assert account["majsoul_uid"] == majsoul_uid
    assert account["koromo_account_id"] == koromo_account_id
    assert account["bound_review_ids"] == [review_id]
    assert repository.list_reviews()[0]["majsoul_uid"] == majsoul_uid
    assert repository.list_reviews()[0]["player_name"] == "Asapin"
    assert repository.get_review_metadata(review_id)["player_name"] == "Asapin"
    assert repository.observation_summary()["decision_count"] == 2

    repository.bind_majsoul_account(
        nickname="New Asapin",
        majsoul_uid=majsoul_uid,
        koromo_account_id=koromo_account_id,
    )
    identity = repository.get_local_identity()
    refreshed = identity["accounts"][0]

    assert refreshed["nickname"] == "New Asapin"
    assert [item["nickname"] for item in refreshed["nickname_history"]] == [
        "New Asapin",
        "Asapin",
    ]
    assert refreshed["nickname_history"][0]["is_current"] == 1
    assert refreshed["nickname_history"][1]["is_current"] == 0


def test_reimport_keeps_account_provenance(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    metadata, review, _ = _review_fixture()
    majsoul_uid = 9_876
    koromo_account_id = 7_654
    repository.bind_majsoul_account(
        nickname="Owner",
        majsoul_uid=majsoul_uid,
        koromo_account_id=koromo_account_id,
    )
    paipu_metadata = _paipu_metadata(metadata, koromo_account_id)
    review_id = make_review_id(paipu_metadata, 0)

    assert (
        repository.save_review(
            review_id=review_id,
            metadata=paipu_metadata,
            player_id=0,
            review=review,
        )
        == majsoul_uid
    )
    assert repository.list_reviews()[0]["player_name"] == "Owner"
    assert (
        repository.save_review(
            review_id=review_id,
            metadata=metadata,
            player_id=0,
            review=review,
        )
        == majsoul_uid
    )
    assert repository.list_reviews()[0]["majsoul_uid"] == majsoul_uid


def test_profile_items_use_single_local_owner(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    metadata, review, _ = _review_fixture()
    review_id = make_review_id(metadata, 0)
    repository.save_review(
        review_id=review_id,
        metadata=metadata,
        player_id=0,
        review=review,
    )

    tentative = repository.create_profile_item(
        kind="pattern",
        category="push_fold",
        statement="May push too often while one-shanten against riichi.",
        scope={"shanten": 1, "opponent_riichi": True},
        status="tentative",
        confidence=0.6,
        source="coach_hypothesis",
    )
    repository.add_profile_evidence(
        item_id=tentative["id"],
        review_id=review_id,
        decision_id="k0.0:d0",
        stance="support",
        note="Chose the lower-ranked discard.",
    )
    with_evidence = repository.add_profile_evidence(
        item_id=tentative["id"],
        review_id=review_id,
        decision_id="k0.0:d1",
        stance="contradict",
        note="Matched Mortal in another decision.",
    )

    assert {item["stance"] for item in with_evidence["evidence"]} == {
        "support",
        "contradict",
    }
    corrected = repository.resolve_profile_item(
        item_id=tentative["id"],
        action="correct",
        statement="I intentionally accept more risk only when placement requires it.",
        kind="style_preference",
    )
    assert corrected["status"] == "confirmed"
    assert corrected["source"] == "user_corrected"

    profile = repository.coaching_profile()
    assert profile["confirmed_profile"][0]["support_count"] == 1
    assert profile["confirmed_profile"][0]["contradict_count"] == 1

    rejected = repository.create_profile_item(
        kind="pattern",
        category="calling",
        statement="May call too frequently.",
        scope={},
        status="tentative",
        confidence=0.4,
        source="coach_hypothesis",
    )
    repository.resolve_profile_item(item_id=rejected["id"], action="reject")
    assert all(item["id"] != rejected["id"] for item in repository.list_profile_items())
    forgotten = repository.resolve_profile_item(
        item_id=rejected["id"],
        action="forget",
    )
    assert forgotten == {"forgotten": True, "item_id": rejected["id"]}


def test_original_database_migrates_and_preserves_review_and_note(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    metadata, review, raw = _review_fixture()
    review_id = make_review_id(metadata, 0)
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE reviews (
                id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                player_id INTEGER NOT NULL,
                player_name TEXT NOT NULL,
                rule_display TEXT NOT NULL,
                model_tag TEXT NOT NULL,
                created_at TEXT NOT NULL,
                report_json TEXT NOT NULL
            );
            CREATE TABLE coaching_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
                decision_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                category TEXT NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO reviews VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?)",
            (
                review_id,
                metadata.path,
                metadata.sha256,
                metadata.player_names[0],
                metadata.rule_display,
                review.model_tag,
                "2026-01-01T00:00:00+00:00",
                json.dumps(raw),
            ),
        )
        connection.execute(
            """
            INSERT INTO coaching_notes (
                review_id, decision_id, kind, category, note, created_at
            ) VALUES (?, 'k0.0:d0', 'mistake', 'shape', 'legacy note', ?)
            """,
            (review_id, "2026-01-01T00:00:01+00:00"),
        )

    repository = ReviewRepository(database_path)

    with repository._connect() as connection:
        review_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(reviews)")
        }
    assert "account_id" in review_columns
    assert "player_key" not in review_columns
    assert repository.list_reviews()[0]["id"] == review_id
    assert repository.observation_summary()["decision_count"] == 2
    assert repository.coaching_profile()["explicit_note_counts"][0]["count"] == 1


def test_current_single_player_database_migrates_account_and_profile(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "multi-user.sqlite3"
    metadata, review, raw = _review_fixture()
    account_id = 1_355_604
    player_key = f"koromo:{account_id}"
    review_id = make_review_id(metadata, 0)
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE players (
                id TEXT PRIMARY KEY,
                koromo_player_id INTEGER NOT NULL UNIQUE,
                nickname TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE player_nicknames (
                player_key TEXT NOT NULL,
                nickname TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                is_current INTEGER NOT NULL,
                PRIMARY KEY (player_key, nickname)
            );
            CREATE TABLE reviews (
                id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                player_id INTEGER NOT NULL,
                player_name TEXT NOT NULL,
                rule_display TEXT NOT NULL,
                model_tag TEXT NOT NULL,
                created_at TEXT NOT NULL,
                report_json TEXT NOT NULL,
                player_key TEXT
            );
            CREATE TABLE profile_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_key TEXT NOT NULL,
                kind TEXT NOT NULL,
                category TEXT NOT NULL,
                statement TEXT NOT NULL,
                scope_json TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        timestamps = ("2026-01-01T00:00:00+00:00",) * 2
        connection.execute(
            "INSERT INTO players VALUES (?, ?, 'Old Nick', ?, ?)",
            (player_key, account_id, *timestamps),
        )
        connection.execute(
            "INSERT INTO player_nicknames VALUES (?, 'Old Nick', ?, ?, 1)",
            (player_key, *timestamps),
        )
        connection.execute(
            "INSERT INTO reviews VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?)",
            (
                review_id,
                metadata.path,
                metadata.sha256,
                metadata.player_names[0],
                metadata.rule_display,
                review.model_tag,
                timestamps[0],
                json.dumps(raw),
                player_key,
            ),
        )
        connection.execute(
            """
            INSERT INTO profile_items (
                player_key, kind, category, statement, scope_json, status,
                confidence, source, created_at, updated_at
            ) VALUES (?, 'goal', 'learning', 'Review every week.', '{}',
                      'confirmed', 1.0, 'user_confirmed', ?, ?)
            """,
            (player_key, *timestamps),
        )

    repository = ReviewRepository(database_path)
    profile = repository.coaching_profile()

    assert profile["local_profile"]["accounts"][0]["majsoul_uid"] == account_id
    assert (
        profile["local_profile"]["accounts"][0]["koromo_account_id"]
        == account_id
    )
    assert repository.list_reviews()[0]["majsoul_uid"] == account_id
    assert profile["confirmed_profile"][0]["statement"] == "Review every week."
    assert repository.observation_summary()["decision_count"] == 2


def test_schema_v5_adds_separate_koromo_account_id(tmp_path: Path) -> None:
    database_path = tmp_path / "schema-v5.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE local_profile (
                id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE majsoul_accounts (
                account_id INTEGER PRIMARY KEY,
                local_profile_id INTEGER NOT NULL,
                nickname TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE reviews (
                id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                player_id INTEGER NOT NULL,
                player_name TEXT NOT NULL,
                rule_display TEXT NOT NULL,
                model_tag TEXT NOT NULL,
                created_at TEXT NOT NULL,
                report_json TEXT NOT NULL,
                report_json_url TEXT,
                account_id INTEGER
            );
            PRAGMA user_version = 5;
            """
        )
        timestamp = "2026-01-01T00:00:00+00:00"
        connection.execute(
            "INSERT INTO local_profile VALUES (1, ?, ?)", (timestamp, timestamp)
        )
        connection.execute(
            "INSERT INTO majsoul_accounts VALUES (?, 1, ?, ?, ?)",
            (12_345_678, "LocalPlayer", timestamp, timestamp),
        )

    repository = ReviewRepository(database_path)
    identity = repository.get_local_identity()["accounts"][0]

    assert identity["majsoul_uid"] == 12_345_678
    assert identity["koromo_account_id"] is None
    with repository._connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        indexes = {
            row["name"]
            for row in connection.execute("PRAGMA index_list(majsoul_accounts)")
        }
    assert "idx_majsoul_accounts_koromo" in indexes


def test_multiple_legacy_players_are_not_silently_merged(tmp_path: Path) -> None:
    database_path = tmp_path / "multiple.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE players (
                id TEXT PRIMARY KEY,
                koromo_player_id INTEGER NOT NULL UNIQUE,
                nickname TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE reviews (
                id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                player_id INTEGER NOT NULL,
                player_name TEXT NOT NULL,
                rule_display TEXT NOT NULL,
                model_tag TEXT NOT NULL,
                created_at TEXT NOT NULL,
                report_json TEXT NOT NULL,
                player_key TEXT
            );
            """
        )
        connection.executemany(
            "INSERT INTO players VALUES (?, ?, ?, 'now', 'now')",
            (("koromo:1", 1, "One"), ("koromo:2", 2, "Two")),
        )

    with pytest.raises(CoachError, match="multiple legacy players"):
        ReviewRepository(database_path)

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 2
