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


def _review_with_final_result(*, player_id: int = 0) -> ReviewDocument:
    return ReviewDocument.from_json(
        {
            "player_id": player_id,
            "mjai_log": [
                {"type": "start_game"},
                {"type": "start_kyoku", "scores": [13100, 31000, 1800, 54100]},
                {"type": "reach_accepted", "actor": 3},
                {"type": "hora", "deltas": [-3000, -6000, -3000, 13000]},
                {"type": "end_kyoku"},
                {"type": "end_game"},
            ],
            "review": {
                "model_tag": "4.1b",
                "kyokus": [],
                "total_reviewed": 0,
                "total_matches": 0,
            },
        },
        player_id=player_id,
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
    observations = repository.list_observations(disagreements_only=False)
    assert observations["total"] == 2
    assert observations["observations"][0]["game_key"].startswith("source:")
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
    duplicate_review_id = f"{review_id}-second-model"
    repository.save_review(
        review_id=duplicate_review_id,
        metadata=metadata,
        player_id=0,
        review=review,
    )
    repository.add_profile_evidence(
        item_id=tentative["id"],
        review_id=duplicate_review_id,
        decision_id="k0.0:d0",
        stance="support",
        note="The same paipu was reviewed by another model.",
    )
    compact_item = next(
        item
        for item in repository.list_profile_items()
        if item["id"] == tentative["id"]
    )
    assert compact_item["support_count"] == 2
    assert compact_item["support_game_count"] == 1
    assert compact_item["contradict_game_count"] == 1
    duplicate_game_keys = {
        item["game_key"]
        for item in repository.list_observations(disagreements_only=False)[
            "observations"
        ]
    }
    assert len(duplicate_game_keys) == 1
    observation_summary = repository.observation_summary()
    assert observation_summary["reviewed_games"] == 1
    assert observation_summary["review_reports"] == 2

    revised = repository.revise_profile_item(
        item_id=tentative["id"],
        statement="May push too often while one-shanten against an early riichi.",
        scope={"shanten": 1, "opponent_riichi": True, "riichi_turn_lte": 8},
        confidence=0.55,
    )
    assert revised["confidence"] == 0.55
    assert revised["scope"]["riichi_turn_lte"] == 8
    surfaced = repository.mark_profile_item_surfaced(tentative["id"])
    assert surfaced["surfaced_count"] == 1
    assert surfaced["last_surfaced_at"] is not None
    compact_item = next(
        item
        for item in repository.list_profile_items()
        if item["id"] == tentative["id"]
    )
    assert compact_item["unseen_evidence_count"] == 0

    corrected = repository.resolve_profile_item(
        item_id=tentative["id"],
        action="correct",
        statement="I intentionally accept more risk only when placement requires it.",
        kind="style_preference",
    )
    assert corrected["status"] == "confirmed"
    assert corrected["source"] == "user_corrected"
    with pytest.raises(CoachError, match="Only tentative"):
        repository.revise_profile_item(
            item_id=tentative["id"],
            statement=None,
            scope=None,
            confidence=0.8,
        )

    profile = repository.coaching_profile()
    assert profile["confirmed_profile"][0]["support_count"] == 2
    assert profile["confirmed_profile"][0]["support_game_count"] == 1
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
    assert profile["local_profile"]["accounts"][0]["koromo_account_id"] == account_id
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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
        indexes = {
            row["name"]
            for row in connection.execute("PRAGMA index_list(majsoul_accounts)")
        }
    assert "idx_majsoul_accounts_koromo" in indexes


def test_schema_v6_adds_profile_surface_tracking(tmp_path: Path) -> None:
    database_path = tmp_path / "schema-v6.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE profile_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            PRAGMA user_version = 6;
            """
        )
        timestamp = "2026-01-01T00:00:00+00:00"
        connection.execute(
            """
            INSERT INTO profile_items (
                kind, category, statement, scope_json, status, confidence,
                source, created_at, updated_at
            ) VALUES ('pattern', 'calling', 'May call too often.', '{}',
                      'tentative', 0.4, 'coach_hypothesis', ?, ?)
            """,
            (timestamp, timestamp),
        )

    repository = ReviewRepository(database_path)
    item = repository.list_profile_items()[0]

    assert item["statement"] == "May call too often."
    assert item["last_surfaced_at"] is None
    assert item["surfaced_count"] == 0
    with repository._connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8


def test_schema_v7_backfills_review_rank_and_score(tmp_path: Path) -> None:
    database_path = tmp_path / "schema-v7.sqlite3"
    review = _review_with_final_result(player_id=0)
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
                koromo_account_id INTEGER,
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
            PRAGMA user_version = 7;
            """
        )
        timestamp = "2026-01-01T00:00:00+00:00"
        connection.execute(
            "INSERT INTO local_profile VALUES (1, ?, ?)",
            (timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO reviews VALUES (
                'old-review', 'https://game.maj-soul.com/1/?paipu=old-game',
                'hash', 0, 'LocalPlayer', '四麻南', '4.1b', ?, ?, NULL, NULL
            )
            """,
            (timestamp, json.dumps(review.raw)),
        )

    repository = ReviewRepository(database_path)

    with repository._connect() as connection:
        row = connection.execute(
            "SELECT player_rank, player_score FROM reviews WHERE id = 'old-review'"
        ).fetchone()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
    assert dict(row) == {"player_rank": 3, "player_score": 10100}


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
