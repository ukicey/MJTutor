from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .context import reconstruct_final_result
from .errors import CoachError, ProfileItemNotFoundError, ReviewNotFoundError
from .koromo import extract_koromo_account_id, extract_paipu_uuid
from .logs import LogMetadata
from .models import ReviewDocument

SCHEMA_VERSION = 8
LOCAL_PROFILE_ID = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS local_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS local_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS majsoul_accounts (
    account_id INTEGER PRIMARY KEY,
    koromo_account_id INTEGER,
    local_profile_id INTEGER NOT NULL DEFAULT 1
        REFERENCES local_profile(id) ON DELETE CASCADE
        CHECK (local_profile_id = 1),
    nickname TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_nicknames (
    account_id INTEGER NOT NULL
        REFERENCES majsoul_accounts(account_id) ON DELETE CASCADE,
    nickname TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (account_id, nickname)
);

CREATE TABLE IF NOT EXISTS koromo_games (
    uuid TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL
        REFERENCES majsoul_accounts(account_id) ON DELETE CASCADE,
    mode_id INTEGER NOT NULL,
    mode_label TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    end_time INTEGER NOT NULL,
    players_json TEXT NOT NULL,
    player_rank INTEGER NOT NULL,
    player_score INTEGER NOT NULL,
    paipu_url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    review_id TEXT REFERENCES reviews(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS koromo_sync_state (
    account_id INTEGER PRIMARY KEY
        REFERENCES majsoul_accounts(account_id) ON DELETE CASCADE,
    last_attempt_at TEXT,
    last_success_at TEXT,
    latest_game_start INTEGER,
    status TEXT NOT NULL DEFAULT 'never',
    last_error TEXT,
    cached_game_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reviews (
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
    player_rank INTEGER,
    player_score INTEGER,
    account_id INTEGER REFERENCES majsoul_accounts(account_id)
);

CREATE TABLE IF NOT EXISTS coaching_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    decision_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    category TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    decision_id TEXT NOT NULL,
    model_tag TEXT NOT NULL,
    round_label TEXT NOT NULL,
    honba INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    tiles_left INTEGER NOT NULL,
    shanten INTEGER NOT NULL,
    furiten INTEGER NOT NULL,
    actual_type TEXT NOT NULL,
    expected_type TEXT NOT NULL,
    actual_action_json TEXT NOT NULL,
    expected_action_json TEXT NOT NULL,
    matches_mortal INTEGER NOT NULL,
    actual_rank INTEGER NOT NULL,
    q_gap REAL NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (review_id, decision_id)
);

CREATE TABLE IF NOT EXISTS profile_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    category TEXT NOT NULL,
    statement TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_surfaced_at TEXT,
    surfaced_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS profile_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_item_id INTEGER NOT NULL
        REFERENCES profile_items(id) ON DELETE CASCADE,
    review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    decision_id TEXT NOT NULL,
    stance TEXT NOT NULL,
    note TEXT NOT NULL,
    model_tag TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (profile_item_id, review_id, decision_id)
);

CREATE INDEX IF NOT EXISTS idx_reviews_account
ON reviews(account_id);

CREATE INDEX IF NOT EXISTS idx_koromo_games_account_start
ON koromo_games(account_id, start_time DESC);

CREATE INDEX IF NOT EXISTS idx_koromo_games_review
ON koromo_games(review_id);

CREATE INDEX IF NOT EXISTS idx_notes_review_decision
ON coaching_notes(review_id, decision_id);

CREATE INDEX IF NOT EXISTS idx_observations_match
ON decision_observations(matches_mortal);

CREATE INDEX IF NOT EXISTS idx_observations_action
ON decision_observations(actual_type, expected_type);

CREATE INDEX IF NOT EXISTS idx_profile_items_status
ON profile_items(status, updated_at);

CREATE INDEX IF NOT EXISTS idx_profile_evidence_item
ON profile_evidence(profile_item_id, stance);
"""


class ReviewRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        migrated = False
        result_backfill_required = False
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("BEGIN IMMEDIATE")
            try:
                if self._requires_single_user_migration(connection):
                    snapshot = self._snapshot_legacy_database(connection)
                    self._validate_legacy_snapshot(snapshot)
                    self._drop_managed_tables(connection)
                    self._execute_schema(connection)
                    self._restore_legacy_snapshot(connection, snapshot)
                    migrated = True
                else:
                    self._execute_schema(connection)
                result_backfill_required = self._ensure_additive_columns(connection)
                now = _now()
                connection.execute(
                    """
                    INSERT INTO local_profile (id, created_at, updated_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (now, now),
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.execute("PRAGMA foreign_keys = ON")
        if migrated:
            self._reindex_all_reviews()
        if migrated or result_backfill_required:
            self._backfill_review_results()

    @staticmethod
    def _execute_schema(connection: sqlite3.Connection) -> None:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                connection.execute(statement)

    @classmethod
    def _ensure_additive_columns(cls, connection: sqlite3.Connection) -> bool:
        review_columns = cls._table_columns(connection, "reviews")
        if "report_json_url" not in review_columns:
            connection.execute("ALTER TABLE reviews ADD COLUMN report_json_url TEXT")
        result_backfill_required = False
        if "player_rank" not in review_columns:
            connection.execute("ALTER TABLE reviews ADD COLUMN player_rank INTEGER")
            result_backfill_required = True
        if "player_score" not in review_columns:
            connection.execute("ALTER TABLE reviews ADD COLUMN player_score INTEGER")
            result_backfill_required = True
        if "koromo_account_id" not in cls._table_columns(
            connection, "majsoul_accounts"
        ):
            connection.execute(
                "ALTER TABLE majsoul_accounts ADD COLUMN koromo_account_id INTEGER"
            )
        profile_columns = cls._table_columns(connection, "profile_items")
        if "last_surfaced_at" not in profile_columns:
            connection.execute(
                "ALTER TABLE profile_items ADD COLUMN last_surfaced_at TEXT"
            )
        if "surfaced_count" not in profile_columns:
            connection.execute(
                "ALTER TABLE profile_items "
                "ADD COLUMN surfaced_count INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_majsoul_accounts_koromo
            ON majsoul_accounts(koromo_account_id)
            WHERE koromo_account_id IS NOT NULL
            """
        )
        connection.execute(
            "UPDATE koromo_games SET players_json = '[]' WHERE players_json != '[]'"
        )
        return result_backfill_required

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            is not None
        )

    @classmethod
    def _table_columns(
        cls,
        connection: sqlite3.Connection,
        table: str,
    ) -> set[str]:
        if not cls._table_exists(connection, table):
            return set()
        return {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }

    @classmethod
    def _requires_single_user_migration(cls, connection: sqlite3.Connection) -> bool:
        if not cls._table_exists(connection, "reviews"):
            return False
        review_columns = cls._table_columns(connection, "reviews")
        observation_columns = cls._table_columns(connection, "decision_observations")
        profile_columns = cls._table_columns(connection, "profile_items")
        return (
            "account_id" not in review_columns
            or "player_key" in review_columns
            or "player_key" in observation_columns
            or "player_key" in profile_columns
            or not cls._table_exists(connection, "local_profile")
            or not cls._table_exists(connection, "majsoul_accounts")
        )

    @classmethod
    def _snapshot_legacy_database(
        cls,
        connection: sqlite3.Connection,
    ) -> dict[str, list[dict[str, Any]]]:
        tables = (
            "local_profile",
            "local_settings",
            "majsoul_accounts",
            "account_nicknames",
            "players",
            "player_nicknames",
            "reviews",
            "coaching_notes",
            "decision_observations",
            "profile_items",
            "profile_evidence",
        )
        snapshot: dict[str, list[dict[str, Any]]] = {}
        for table in tables:
            if cls._table_exists(connection, table):
                snapshot[table] = [
                    dict(row) for row in connection.execute(f"SELECT * FROM {table}")
                ]
            else:
                snapshot[table] = []
        return snapshot

    @staticmethod
    def _validate_legacy_snapshot(
        snapshot: dict[str, list[dict[str, Any]]],
    ) -> None:
        players = snapshot["players"]
        if len(players) > 1:
            raise CoachError(
                "This database contains multiple legacy players. MJTutor will not "
                "merge their profiles automatically; resolve them before single-user "
                "migration."
            )

    @staticmethod
    def _drop_managed_tables(connection: sqlite3.Connection) -> None:
        for table in (
            "profile_evidence",
            "profile_items",
            "decision_observations",
            "coaching_notes",
            "koromo_sync_state",
            "koromo_games",
            "reviews",
            "account_nicknames",
            "majsoul_accounts",
            "local_settings",
            "local_profile",
            "player_nicknames",
            "players",
        ):
            connection.execute(f"DROP TABLE IF EXISTS {table}")

    @staticmethod
    def _restore_legacy_snapshot(
        connection: sqlite3.Connection,
        snapshot: dict[str, list[dict[str, Any]]],
    ) -> None:
        now = _now()
        legacy_player = snapshot["players"][0] if snapshot["players"] else None
        profile_rows = snapshot["local_profile"]
        created_at = (
            str(profile_rows[0].get("created_at", now))
            if profile_rows
            else str(legacy_player.get("created_at", now))
            if legacy_player
            else now
        )
        updated_at = (
            str(profile_rows[0].get("updated_at", now))
            if profile_rows
            else str(legacy_player.get("updated_at", now))
            if legacy_player
            else now
        )
        connection.execute(
            "INSERT INTO local_profile (id, created_at, updated_at) VALUES (1, ?, ?)",
            (created_at, updated_at),
        )

        for row in snapshot["local_settings"]:
            connection.execute(
                """
                INSERT INTO local_settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                """,
                (row["key"], row["value_json"], row["updated_at"]),
            )

        accounts: dict[int, dict[str, Any]] = {}
        for row in snapshot["majsoul_accounts"]:
            account_id = int(row["account_id"])
            accounts[account_id] = row
        legacy_player_key: str | None = None
        if legacy_player is not None:
            legacy_player_key = str(legacy_player["id"])
            account_id = int(legacy_player["koromo_player_id"])
            accounts.setdefault(
                account_id,
                {
                    "account_id": account_id,
                    "nickname": str(legacy_player["nickname"]),
                    "created_at": str(legacy_player["created_at"]),
                    "updated_at": str(legacy_player["updated_at"]),
                },
            )
        for account_id, row in accounts.items():
            connection.execute(
                """
                INSERT INTO majsoul_accounts (
                    account_id, koromo_account_id, local_profile_id, nickname,
                    created_at, updated_at
                ) VALUES (?, ?, 1, ?, ?, ?)
                """,
                (
                    account_id,
                    int(row["koromo_account_id"])
                    if row.get("koromo_account_id") is not None
                    else account_id
                    if "koromo_account_id" not in row or legacy_player is not None
                    else None,
                    str(row["nickname"]),
                    str(row.get("created_at", now)),
                    str(row.get("updated_at", now)),
                ),
            )

        nickname_rows: list[tuple[int, str, str, str, int]] = []
        for row in snapshot["account_nicknames"]:
            account_id = int(row["account_id"])
            if account_id in accounts:
                nickname_rows.append(
                    (
                        account_id,
                        str(row["nickname"]),
                        str(row["first_seen_at"]),
                        str(row["last_seen_at"]),
                        int(row["is_current"]),
                    )
                )
        if legacy_player is not None:
            legacy_account_id = int(legacy_player["koromo_player_id"])
            for row in snapshot["player_nicknames"]:
                if str(row["player_key"]) == legacy_player_key:
                    nickname_rows.append(
                        (
                            legacy_account_id,
                            str(row["nickname"]),
                            str(row["first_seen_at"]),
                            str(row["last_seen_at"]),
                            int(row["is_current"]),
                        )
                    )
        for account_id, account in accounts.items():
            if not any(row[0] == account_id for row in nickname_rows):
                nickname_rows.append(
                    (
                        account_id,
                        str(account["nickname"]),
                        str(account.get("created_at", now)),
                        str(account.get("updated_at", now)),
                        1,
                    )
                )
        connection.executemany(
            """
            INSERT INTO account_nicknames (
                account_id, nickname, first_seen_at, last_seen_at, is_current
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(account_id, nickname) DO UPDATE SET
                first_seen_at = excluded.first_seen_at,
                last_seen_at = excluded.last_seen_at,
                is_current = excluded.is_current
            """,
            nickname_rows,
        )

        account_ids = set(accounts)
        for row in snapshot["reviews"]:
            account_id = row.get("account_id")
            if account_id is not None:
                account_id = int(account_id)
                if account_id not in account_ids:
                    account_id = None
            if (
                account_id is None
                and legacy_player is not None
                and (
                    row.get("player_key") == legacy_player_key
                    or extract_koromo_account_id(str(row["source_path"]))
                    == int(legacy_player["koromo_player_id"])
                )
            ):
                account_id = int(legacy_player["koromo_player_id"])
            connection.execute(
                """
                INSERT INTO reviews (
                    id, source_path, source_sha256, player_id, player_name,
                    rule_display, model_tag, created_at, report_json,
                    report_json_url, account_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["source_path"],
                    row["source_sha256"],
                    row["player_id"],
                    row["player_name"],
                    row["rule_display"],
                    row["model_tag"],
                    row["created_at"],
                    row["report_json"],
                    row.get("report_json_url"),
                    account_id,
                ),
            )

        for row in snapshot["coaching_notes"]:
            connection.execute(
                """
                INSERT INTO coaching_notes (
                    id, review_id, decision_id, kind, category, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(
                    row[key]
                    for key in (
                        "id",
                        "review_id",
                        "decision_id",
                        "kind",
                        "category",
                        "note",
                        "created_at",
                    )
                ),
            )

        observation_fields = (
            "id",
            "review_id",
            "decision_id",
            "model_tag",
            "round_label",
            "honba",
            "turn",
            "tiles_left",
            "shanten",
            "furiten",
            "actual_type",
            "expected_type",
            "actual_action_json",
            "expected_action_json",
            "matches_mortal",
            "actual_rank",
            "q_gap",
            "created_at",
        )
        for row in snapshot["decision_observations"]:
            connection.execute(
                f"""
                INSERT INTO decision_observations ({", ".join(observation_fields)})
                VALUES ({", ".join("?" for _ in observation_fields)})
                """,
                tuple(row[field] for field in observation_fields),
            )

        profile_fields = (
            "id",
            "kind",
            "category",
            "statement",
            "scope_json",
            "status",
            "confidence",
            "source",
            "created_at",
            "updated_at",
        )
        for row in snapshot["profile_items"]:
            connection.execute(
                f"""
                INSERT INTO profile_items ({", ".join(profile_fields)})
                VALUES ({", ".join("?" for _ in profile_fields)})
                """,
                tuple(row[field] for field in profile_fields),
            )

        evidence_fields = (
            "id",
            "profile_item_id",
            "review_id",
            "decision_id",
            "stance",
            "note",
            "model_tag",
            "created_at",
        )
        for row in snapshot["profile_evidence"]:
            connection.execute(
                f"""
                INSERT INTO profile_evidence ({", ".join(evidence_fields)})
                VALUES ({", ".join("?" for _ in evidence_fields)})
                """,
                tuple(row[field] for field in evidence_fields),
            )

    def _reindex_all_reviews(self) -> None:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT id FROM reviews").fetchall()
        for row in rows:
            review_id = str(row["id"])
            try:
                review = self.get_review(review_id)
            except (KeyError, TypeError, ValueError, CoachError):
                continue
            self._index_review_observations(review_id=review_id, review=review)

    def _backfill_review_results(self) -> None:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, report_json, player_id FROM reviews"
            ).fetchall()
            results = []
            for row in rows:
                try:
                    payload = json.loads(str(row["report_json"]))
                except (TypeError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                result = reconstruct_final_result(
                    payload.get("mjai_log"),
                    player_id=int(row["player_id"]),
                )
                if result is None:
                    continue
                results.append(
                    (
                        int(result["player_rank"]),
                        int(result["player_score"]),
                        str(row["id"]),
                    )
                )
            connection.executemany(
                """
                UPDATE reviews
                SET player_rank = ?, player_score = ?
                WHERE id = ?
                """,
                results,
            )
            connection.commit()

    def bind_majsoul_account(
        self,
        *,
        nickname: str,
        majsoul_uid: int,
        koromo_account_id: int | None = None,
    ) -> dict[str, Any]:
        nickname = nickname.strip()
        if not nickname:
            raise CoachError("nickname must not be empty")
        if majsoul_uid <= 0:
            raise CoachError("majsoul_uid must be a positive integer")
        if koromo_account_id is not None and koromo_account_id <= 0:
            raise CoachError("koromo_account_id must be a positive integer")
        now = _now()
        with closing(self._connect()) as connection:
            existing = connection.execute(
                """
                SELECT nickname, koromo_account_id, created_at
                FROM majsoul_accounts
                WHERE account_id = ?
                """,
                (majsoul_uid,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO majsoul_accounts (
                        account_id, koromo_account_id, local_profile_id, nickname,
                        created_at, updated_at
                    ) VALUES (?, ?, 1, ?, ?, ?)
                    """,
                    (majsoul_uid, koromo_account_id, nickname, now, now),
                )
                created_at = now
                previous_koromo_account_id = None
            else:
                created_at = str(existing["created_at"])
                previous_koromo_account_id = (
                    int(existing["koromo_account_id"])
                    if existing["koromo_account_id"] is not None
                    else None
                )
                if str(existing["nickname"]) != nickname:
                    connection.execute(
                        """
                        UPDATE account_nicknames
                        SET is_current = 0
                        WHERE account_id = ?
                        """,
                        (majsoul_uid,),
                    )
                connection.execute(
                    """
                    UPDATE majsoul_accounts
                    SET nickname = ?,
                        koromo_account_id = COALESCE(?, koromo_account_id),
                        updated_at = ?
                    WHERE account_id = ?
                    """,
                    (nickname, koromo_account_id, now, majsoul_uid),
                )
            connection.execute(
                """
                INSERT INTO account_nicknames (
                    account_id, nickname, first_seen_at, last_seen_at, is_current
                ) VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(account_id, nickname) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    is_current = 1
                """,
                (majsoul_uid, nickname, now, now),
            )
            if (
                koromo_account_id is not None
                and koromo_account_id != previous_koromo_account_id
            ):
                connection.execute(
                    "DELETE FROM koromo_games WHERE account_id = ?", (majsoul_uid,)
                )
                connection.execute(
                    "DELETE FROM koromo_sync_state WHERE account_id = ?", (majsoul_uid,)
                )
            connection.execute(
                "UPDATE reviews SET player_name = ? WHERE account_id = ?",
                (nickname, majsoul_uid),
            )
            connection.execute(
                "UPDATE local_profile SET updated_at = ? WHERE id = 1",
                (now,),
            )
            connection.commit()

        effective_koromo_account_id = (
            koromo_account_id
            if koromo_account_id is not None
            else previous_koromo_account_id
        )
        bound_review_ids = self._backfill_account_reviews(
            majsoul_uid=majsoul_uid,
            koromo_account_id=effective_koromo_account_id,
        )
        return {
            "majsoul_uid": majsoul_uid,
            "koromo_account_id": effective_koromo_account_id,
            "nickname": nickname,
            "created_at": created_at,
            "updated_at": now,
            "bound_review_ids": bound_review_ids,
        }

    def get_local_identity(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            profile = connection.execute(
                "SELECT id, created_at, updated_at FROM local_profile WHERE id = 1"
            ).fetchone()
            accounts = connection.execute(
                """
                SELECT a.account_id AS majsoul_uid, a.koromo_account_id,
                       a.nickname, a.created_at, a.updated_at,
                       COUNT(DISTINCT r.id) AS review_count
                FROM majsoul_accounts AS a
                LEFT JOIN reviews AS r ON r.account_id = a.account_id
                GROUP BY a.account_id
                ORDER BY a.updated_at DESC, a.account_id
                """
            ).fetchall()
            histories = connection.execute(
                """
                SELECT account_id, nickname, first_seen_at, last_seen_at, is_current
                FROM account_nicknames
                ORDER BY account_id, is_current DESC, last_seen_at DESC
                """
            ).fetchall()
        by_account: dict[int, list[dict[str, Any]]] = {}
        for row in histories:
            item = dict(row)
            by_account.setdefault(int(item.pop("account_id")), []).append(item)
        account_results = []
        for row in accounts:
            item = dict(row)
            item["review_count"] = int(item["review_count"])
            item["nickname_history"] = by_account.get(int(item["majsoul_uid"]), [])
            account_results.append(item)
        return {
            "id": int(profile["id"]),
            "created_at": str(profile["created_at"]),
            "updated_at": str(profile["updated_at"]),
            "accounts": account_results,
        }

    def get_local_setting(self, key: str) -> Any | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT value_json FROM local_settings WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["value_json"]))

    def set_local_setting(self, key: str, value: Any) -> dict[str, Any]:
        updated_at = _now()
        value_json = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO local_settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, value_json, updated_at),
            )
            connection.commit()
        return {"key": key, "value": value, "updated_at": updated_at}

    def delete_local_setting(self, key: str) -> bool:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "DELETE FROM local_settings WHERE key = ?",
                (key,),
            )
            connection.commit()
        return cursor.rowcount > 0

    def save_koromo_games(
        self,
        *,
        account_id: int,
        games: list[dict[str, Any]],
    ) -> dict[str, int]:
        now = _now()
        inserted = 0
        updated = 0
        with closing(self._connect()) as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM majsoul_accounts WHERE account_id = ?",
                    (account_id,),
                ).fetchone()
                is None
            ):
                raise CoachError(f"Mahjong Soul account is not bound: {account_id}")
            reviews_by_uuid = {
                paipu_uuid: str(row["id"])
                for row in connection.execute(
                    "SELECT id, source_path FROM reviews WHERE account_id = ?",
                    (account_id,),
                ).fetchall()
                if (paipu_uuid := extract_paipu_uuid(str(row["source_path"])))
            }
            for game in games:
                uuid = str(game["uuid"])
                existed = connection.execute(
                    "SELECT 1 FROM koromo_games WHERE uuid = ?",
                    (uuid,),
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO koromo_games (
                        uuid, account_id, mode_id, mode_label, start_time, end_time,
                        players_json, player_rank, player_score, paipu_url,
                        first_seen_at, last_seen_at, review_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(uuid) DO UPDATE SET
                        account_id = excluded.account_id,
                        mode_id = excluded.mode_id,
                        mode_label = excluded.mode_label,
                        start_time = excluded.start_time,
                        end_time = excluded.end_time,
                        players_json = excluded.players_json,
                        player_rank = excluded.player_rank,
                        player_score = excluded.player_score,
                        paipu_url = excluded.paipu_url,
                        last_seen_at = excluded.last_seen_at,
                        review_id = COALESCE(excluded.review_id, koromo_games.review_id)
                    """,
                    (
                        uuid,
                        account_id,
                        int(game["mode_id"]),
                        str(game["mode_label"]),
                        int(game["start_time"]),
                        int(game["end_time"]),
                        "[]",
                        int(game["player_rank"]),
                        int(game["player_score"]),
                        str(game["paipu_url"]),
                        now,
                        now,
                        reviews_by_uuid.get(uuid),
                    ),
                )
                inserted += existed is None
                updated += existed is not None
            connection.commit()
        return {"inserted": inserted, "updated": updated}

    def record_koromo_sync(
        self,
        *,
        account_id: int,
        status: str,
        success: bool,
        latest_game_start: int | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with closing(self._connect()) as connection:
            current = connection.execute(
                "SELECT last_success_at, latest_game_start "
                "FROM koromo_sync_state WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            previous_latest = (
                int(current["latest_game_start"])
                if current is not None and current["latest_game_start"] is not None
                else None
            )
            next_latest = (
                max(
                    value
                    for value in (previous_latest, latest_game_start)
                    if value is not None
                )
                if previous_latest is not None or latest_game_start is not None
                else None
            )
            previous_success = (
                str(current["last_success_at"])
                if current is not None and current["last_success_at"] is not None
                else None
            )
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM koromo_games WHERE account_id = ?",
                    (account_id,),
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO koromo_sync_state (
                    account_id, last_attempt_at, last_success_at, latest_game_start,
                    status, last_error, cached_game_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    last_attempt_at = excluded.last_attempt_at,
                    last_success_at = excluded.last_success_at,
                    latest_game_start = excluded.latest_game_start,
                    status = excluded.status,
                    last_error = excluded.last_error,
                    cached_game_count = excluded.cached_game_count
                """,
                (
                    account_id,
                    now,
                    now if success else previous_success,
                    next_latest,
                    status,
                    error,
                    count,
                ),
            )
            connection.commit()
        return self.get_koromo_sync_status(account_id=account_id)

    def get_koromo_sync_status(
        self,
        *,
        account_id: int | None = None,
    ) -> dict[str, Any]:
        identity = self.get_local_identity()
        accounts = identity["accounts"]
        if account_id is not None:
            accounts = [
                item for item in accounts if int(item["majsoul_uid"]) == account_id
            ]
            if not accounts:
                raise CoachError(f"Mahjong Soul UID is not bound: {account_id}")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM koromo_sync_state ORDER BY account_id"
            ).fetchall()
        states = {int(row["account_id"]): dict(row) for row in rows}
        results = []
        for account in accounts:
            item = {
                "majsoul_uid": int(account["majsoul_uid"]),
                "koromo_account_id": (
                    int(account["koromo_account_id"])
                    if account["koromo_account_id"] is not None
                    else None
                ),
                "nickname": str(account["nickname"]),
                "last_attempt_at": None,
                "last_success_at": None,
                "latest_game_start": None,
                "status": (
                    "never"
                    if account["koromo_account_id"] is not None
                    else "identity_link_required"
                ),
                "last_error": None,
                "cached_game_count": 0,
            }
            state = states.get(item["majsoul_uid"], {})
            if item["koromo_account_id"] is not None:
                item.update(
                    {key: value for key, value in state.items() if key != "account_id"}
                )
            results.append(item)
        return {"accounts": results}

    def list_koromo_games(
        self,
        *,
        majsoul_uid: int | None = None,
        rank: int | None = None,
        reviewed: bool | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        if rank is not None and rank not in range(1, 5):
            raise CoachError("rank must be within 1-4")
        page_limit = max(1, min(int(limit), 100))
        page_offset = max(0, int(offset))
        all_items = self._catalog_items()
        filtered = [
            item
            for item in all_items
            if (majsoul_uid is None or item["majsoul_uid"] == majsoul_uid)
            and (rank is None or item["player_rank"] == rank)
            and (reviewed is None or item["reviewed"] is reviewed)
            and (start_time is None or item["start_time"] >= start_time)
            and (end_time is None or item["start_time"] <= end_time)
        ]
        items = filtered[page_offset : page_offset + page_limit]
        total_reviews = sum(int(item["review_count"]) for item in all_items)
        return {
            "items": items,
            "total": len(filtered),
            "limit": page_limit,
            "offset": page_offset,
            "has_more": page_offset + len(items) < len(filtered),
            "catalog_game_count": len(all_items),
            "catalog_review_count": total_reviews,
        }

    def _catalog_items(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            game_rows = connection.execute(
                """
                SELECT g.*, a.nickname AS account_nickname,
                       a.account_id AS majsoul_uid, a.koromo_account_id
                FROM koromo_games AS g
                JOIN majsoul_accounts AS a ON a.account_id = g.account_id
                ORDER BY g.start_time DESC, g.uuid
                """,
            ).fetchall()
            review_rows = connection.execute(
                """
                SELECT r.id, r.source_path, r.model_tag, r.created_at, r.account_id,
                       r.rule_display, r.player_rank, r.player_score,
                       a.nickname AS account_nickname,
                       a.koromo_account_id
                FROM reviews AS r
                LEFT JOIN majsoul_accounts AS a ON a.account_id = r.account_id
                ORDER BY r.created_at DESC, r.id
                """
            ).fetchall()
        by_uuid: dict[str, dict[str, Any]] = {}
        for row in game_rows:
            item = dict(row)
            item.pop("players_json", None)
            item.pop("account_id", None)
            item.pop("review_id", None)
            item.update(
                {
                    "source": "koromo",
                    "reviewed": False,
                    "review_count": 0,
                    "review_id": None,
                    "review_ids": [],
                    "model_tags": [],
                    "reviews": [],
                }
            )
            by_uuid[str(item["uuid"])] = item
        for row in review_rows:
            paipu_url = str(row["source_path"])
            uuid = extract_paipu_uuid(paipu_url)
            if uuid is None:
                continue
            item = by_uuid.get(uuid)
            if item is None:
                created_at = str(row["created_at"])
                item = {
                    "uuid": uuid,
                    "majsoul_uid": (
                        int(row["account_id"])
                        if row["account_id"] is not None
                        else None
                    ),
                    "koromo_account_id": (
                        int(row["koromo_account_id"])
                        if row["koromo_account_id"] is not None
                        else extract_koromo_account_id(paipu_url)
                    ),
                    "account_nickname": row["account_nickname"],
                    "mode_id": None,
                    "mode_label": "四麻南",
                    "start_time": _timestamp(created_at),
                    "end_time": _timestamp(created_at),
                    "time_accuracy": "imported",
                    "player_rank": row["player_rank"],
                    "player_score": row["player_score"],
                    "paipu_url": paipu_url,
                    "first_seen_at": created_at,
                    "last_seen_at": created_at,
                    "source": "local_review",
                    "reviewed": True,
                    "review_count": 0,
                    "review_id": None,
                    "review_ids": [],
                    "model_tags": [],
                    "reviews": [],
                }
                by_uuid[uuid] = item
            elif item["source"] == "koromo":
                item["source"] = "both"
            if item["player_rank"] is None and row["player_rank"] is not None:
                item["player_rank"] = int(row["player_rank"])
            if item["player_score"] is None and row["player_score"] is not None:
                item["player_score"] = int(row["player_score"])
            review_id = str(row["id"])
            model_tag = str(row["model_tag"])
            item["review_ids"].append(review_id)
            item["review_count"] += 1
            item["review_id"] = item["review_id"] or review_id
            if model_tag not in item["model_tags"]:
                item["model_tags"].append(model_tag)
            item.setdefault("reviews", []).append(
                {
                    "review_id": review_id,
                    "model_tag": model_tag,
                    "created_at": str(row["created_at"]),
                }
            )
            item["reviewed"] = True
        return sorted(
            by_uuid.values(),
            key=lambda item: (int(item["start_time"]), str(item["uuid"])),
            reverse=True,
        )

    def get_catalog_game(self, uuid: str) -> dict[str, Any]:
        game = next(
            (item for item in self._catalog_items() if item["uuid"] == uuid), None
        )
        if game is None:
            raise CoachError(f"Game is not in the local catalog: {uuid}")
        return game

    def save_review(
        self,
        *,
        review_id: str,
        metadata: LogMetadata,
        player_id: int,
        review: ReviewDocument,
        report_json_url: str | None = None,
    ) -> int | None:
        player_name = metadata.player_names[player_id]
        now = _now()
        payload = json.dumps(review.raw, ensure_ascii=False, separators=(",", ":"))
        account_id = self._registered_account_for_source(metadata.path)
        result = reconstruct_final_result(
            review.raw.get("mjai_log"),
            player_id=player_id,
        )
        player_rank = result["player_rank"] if result is not None else None
        player_score = result["player_score"] if result is not None else None
        with closing(self._connect()) as connection:
            if account_id is not None:
                account = connection.execute(
                    "SELECT nickname FROM majsoul_accounts WHERE account_id = ?",
                    (account_id,),
                ).fetchone()
                if account is not None:
                    player_name = str(account["nickname"])
            connection.execute(
                """
                INSERT INTO reviews (
                    id, source_path, source_sha256, player_id, player_name,
                    rule_display, model_tag, created_at, report_json,
                    report_json_url, player_rank, player_score, account_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source_path = excluded.source_path,
                    source_sha256 = excluded.source_sha256,
                    player_id = excluded.player_id,
                    player_name = excluded.player_name,
                    rule_display = excluded.rule_display,
                    model_tag = excluded.model_tag,
                    created_at = excluded.created_at,
                    report_json = excluded.report_json,
                    report_json_url = COALESCE(
                        excluded.report_json_url, reviews.report_json_url
                    ),
                    player_rank = excluded.player_rank,
                    player_score = excluded.player_score,
                    account_id = COALESCE(excluded.account_id, reviews.account_id)
                """,
                (
                    review_id,
                    metadata.path,
                    metadata.sha256,
                    player_id,
                    player_name,
                    metadata.rule_display,
                    review.model_tag,
                    now,
                    payload,
                    report_json_url,
                    player_rank,
                    player_score,
                    account_id,
                ),
            )
            stored = connection.execute(
                "SELECT account_id FROM reviews WHERE id = ?",
                (review_id,),
            ).fetchone()
            account_id = (
                int(stored["account_id"])
                if stored is not None and stored["account_id"] is not None
                else None
            )
            connection.commit()
        paipu_uuid = extract_paipu_uuid(metadata.path)
        if paipu_uuid:
            with closing(self._connect()) as connection:
                connection.execute(
                    "UPDATE koromo_games SET review_id = ? WHERE uuid = ?",
                    (review_id, paipu_uuid),
                )
                connection.commit()
        self._index_review_observations(review_id=review_id, review=review)
        return account_id

    def _registered_account_for_source(self, source: str) -> int | None:
        koromo_account_id = extract_koromo_account_id(source)
        if koromo_account_id is None:
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT account_id
                FROM majsoul_accounts
                WHERE koromo_account_id = ?
                """,
                (koromo_account_id,),
            ).fetchone()
        return int(row["account_id"]) if row is not None else None

    def _backfill_account_reviews(
        self,
        *,
        majsoul_uid: int,
        koromo_account_id: int | None,
    ) -> list[str]:
        if koromo_account_id is None:
            return []
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, source_path FROM reviews WHERE account_id IS NULL"
            ).fetchall()
            matching = [
                str(row["id"])
                for row in rows
                if extract_koromo_account_id(str(row["source_path"]))
                == koromo_account_id
            ]
            connection.executemany(
                """
                UPDATE reviews
                SET account_id = ?,
                    player_name = (
                        SELECT nickname
                        FROM majsoul_accounts
                        WHERE account_id = ?
                    )
                WHERE id = ?
                """,
                ((majsoul_uid, majsoul_uid, review_id) for review_id in matching),
            )
            connection.commit()
        for review_id in matching:
            self._index_review_observations(
                review_id=review_id,
                review=self.get_review(review_id),
            )
        return matching

    def _index_review_observations(
        self,
        *,
        review_id: str,
        review: ReviewDocument,
    ) -> int:
        now = _now()
        rows = [
            (
                review_id,
                decision.decision_id,
                review.model_tag,
                decision.round_label,
                decision.honba,
                decision.turn,
                decision.tiles_left,
                decision.shanten,
                int(decision.furiten),
                str(decision.actual.get("type", "unknown")),
                str(decision.expected.get("type", "unknown")),
                json.dumps(decision.actual, ensure_ascii=False, separators=(",", ":")),
                json.dumps(
                    decision.expected, ensure_ascii=False, separators=(",", ":")
                ),
                int(decision.matches_mortal),
                decision.actual_index + 1,
                decision.q_gap,
                now,
            )
            for decision in review.decisions
        ]
        with closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM decision_observations WHERE review_id = ?",
                (review_id,),
            )
            connection.executemany(
                """
                INSERT INTO decision_observations (
                    review_id, decision_id, model_tag, round_label, honba,
                    turn, tiles_left, shanten, furiten, actual_type,
                    expected_type, actual_action_json, expected_action_json,
                    matches_mortal, actual_rank, q_gap, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            connection.commit()
        return len(rows)

    def list_reviews(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT r.id, r.source_path, r.report_json_url,
                       r.player_id,
                       COALESCE(a.nickname, r.player_name) AS player_name,
                       r.rule_display, r.model_tag, r.created_at,
                       a.account_id AS majsoul_uid,
                       a.nickname AS account_nickname
                FROM reviews AS r
                LEFT JOIN majsoul_accounts AS a ON a.account_id = r.account_id
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_review_metadata(self, review_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT r.id, r.source_path, r.report_json_url, r.player_id,
                       COALESCE(a.nickname, r.player_name) AS player_name,
                       r.rule_display, r.model_tag, r.created_at,
                       a.account_id AS majsoul_uid,
                       a.nickname AS account_nickname
                FROM reviews AS r
                LEFT JOIN majsoul_accounts AS a ON a.account_id = r.account_id
                WHERE r.id = ?
                """,
                (review_id,),
            ).fetchone()
        if row is None:
            raise ReviewNotFoundError(f"Review not found: {review_id}")
        return dict(row)

    def get_review(self, review_id: str) -> ReviewDocument:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT report_json, player_id FROM reviews WHERE id = ?",
                (review_id,),
            ).fetchone()
        if row is None:
            raise ReviewNotFoundError(f"Review not found: {review_id}")
        return ReviewDocument.from_json(
            json.loads(row["report_json"]),
            player_id=int(row["player_id"]),
        )

    def add_note(
        self,
        *,
        review_id: str,
        decision_id: str,
        kind: str,
        category: str,
        note: str,
    ) -> dict[str, Any]:
        review = self.get_review(review_id)
        review.get_decision(decision_id)
        now = _now()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO coaching_notes (
                    review_id, decision_id, kind, category, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (review_id, decision_id, kind, category, note, now),
            )
            connection.commit()
            note_id = cursor.lastrowid
        return {
            "id": note_id,
            "review_id": review_id,
            "decision_id": decision_id,
            "kind": kind,
            "category": category,
            "note": note,
            "created_at": now,
        }

    def observation_summary(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            totals = connection.execute(
                """
                SELECT COUNT(*) AS decision_count,
                       COUNT(DISTINCT o.review_id) AS review_reports,
                       COUNT(DISTINCT r.source_path) AS reviewed_games,
                       COALESCE(SUM(o.matches_mortal), 0) AS mortal_matches
                FROM decision_observations AS o
                JOIN reviews AS r ON r.id = o.review_id
                """
            ).fetchone()
            models = connection.execute(
                """
                SELECT o.model_tag,
                       COUNT(DISTINCT r.source_path) AS reviewed_games,
                       COUNT(DISTINCT o.review_id) AS review_reports,
                       COUNT(*) AS decision_count,
                       SUM(o.matches_mortal) AS mortal_matches
                FROM decision_observations AS o
                JOIN reviews AS r ON r.id = o.review_id
                GROUP BY o.model_tag
                ORDER BY reviewed_games DESC, o.model_tag
                """
            ).fetchall()
            patterns = connection.execute(
                """
                SELECT o.actual_type, o.expected_type,
                       COUNT(DISTINCT r.source_path || ':' || o.decision_id) AS count
                FROM decision_observations AS o
                JOIN reviews AS r ON r.id = o.review_id
                WHERE o.matches_mortal = 0
                GROUP BY o.actual_type, o.expected_type
                ORDER BY count DESC, o.actual_type, o.expected_type
                LIMIT 12
                """
            ).fetchall()
        decision_count = int(totals["decision_count"])
        mortal_matches = int(totals["mortal_matches"])
        return {
            "reviewed_games": int(totals["reviewed_games"]),
            "review_reports": int(totals["review_reports"]),
            "decision_count": decision_count,
            "mortal_matches": mortal_matches,
            "match_rate": mortal_matches / decision_count if decision_count else None,
            "by_model": [dict(row) for row in models],
            "disagreement_action_patterns": [dict(row) for row in patterns],
        }

    def list_observations(
        self,
        *,
        disagreements_only: bool = True,
        actual_type: str | None = None,
        expected_type: str | None = None,
        limit: int = 12,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if disagreements_only:
            clauses.append("matches_mortal = 0")
        if actual_type:
            clauses.append("actual_type = ?")
            parameters.append(actual_type)
        if expected_type:
            clauses.append("expected_type = ?")
            parameters.append(expected_type)
        page_limit = max(1, min(limit, 50))
        page_offset = max(0, offset)
        where = " AND ".join(clauses) if clauses else "1 = 1"
        with closing(self._connect()) as connection:
            total = connection.execute(
                f"SELECT COUNT(*) AS count FROM decision_observations WHERE {where}",
                parameters,
            ).fetchone()
            rows = connection.execute(
                f"""
                SELECT o.review_id, o.decision_id, o.model_tag, o.round_label,
                       o.honba, o.turn, o.tiles_left, o.shanten, o.furiten,
                       o.actual_type, o.expected_type, o.actual_action_json,
                       o.expected_action_json, o.matches_mortal, o.actual_rank,
                       o.q_gap, r.source_path
                FROM decision_observations AS o
                JOIN reviews AS r ON r.id = o.review_id
                WHERE {where}
                ORDER BY o.created_at DESC, o.review_id, o.decision_id
                LIMIT ? OFFSET ?
                """,
                (*parameters, page_limit, page_offset),
            ).fetchall()
        observations = []
        for row in rows:
            item = dict(row)
            item["game_key"] = _source_game_key(item.pop("source_path"))
            item["actual"] = json.loads(item.pop("actual_action_json"))
            item["expected"] = json.loads(item.pop("expected_action_json"))
            item["matches_mortal"] = bool(item["matches_mortal"])
            item["furiten"] = bool(item["furiten"])
            observations.append(item)
        total_count = int(total["count"])
        return {
            "total": total_count,
            "offset": page_offset,
            "limit": page_limit,
            "observations": observations,
            "next_offset": (
                page_offset + len(observations)
                if page_offset + len(observations) < total_count
                else None
            ),
        }

    def create_profile_item(
        self,
        *,
        kind: str,
        category: str,
        statement: str,
        scope: dict[str, Any],
        status: str,
        confidence: float,
        source: str,
    ) -> dict[str, Any]:
        now = _now()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO profile_items (
                    kind, category, statement, scope_json, status,
                    confidence, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    category,
                    statement,
                    json.dumps(scope, ensure_ascii=False, separators=(",", ":")),
                    status,
                    confidence,
                    source,
                    now,
                    now,
                ),
            )
            connection.commit()
            item_id = int(cursor.lastrowid)
        return self.get_profile_item(item_id)

    def get_profile_item(
        self,
        item_id: int,
        *,
        evidence_limit: int = 20,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM profile_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise ProfileItemNotFoundError(f"Profile item not found: {item_id}")
            evidence = connection.execute(
                """
                SELECT e.id, e.review_id, e.decision_id, e.stance, e.note,
                       e.model_tag, e.created_at, r.source_path
                FROM profile_evidence AS e
                JOIN reviews AS r ON r.id = e.review_id
                WHERE e.profile_item_id = ?
                ORDER BY e.created_at DESC
                LIMIT ?
                """,
                (item_id, max(1, min(evidence_limit, 100))),
            ).fetchall()
        result = _profile_item_dict(row)
        result["evidence"] = []
        for evidence_row in evidence:
            evidence_item = dict(evidence_row)
            evidence_item["game_key"] = _source_game_key(
                evidence_item.pop("source_path")
            )
            result["evidence"].append(evidence_item)
        return result

    def list_profile_items(
        self,
        *,
        include_rejected: bool = False,
    ) -> list[dict[str, Any]]:
        status_clause = "" if include_rejected else "WHERE p.status != 'rejected'"
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT p.*,
                       SUM(CASE WHEN e.stance = 'support' THEN 1 ELSE 0 END)
                           AS support_count,
                       SUM(CASE WHEN e.stance = 'contradict' THEN 1 ELSE 0 END)
                           AS contradict_count,
                       COUNT(DISTINCT CASE WHEN e.stance = 'support'
                           THEN r.source_path END) AS support_game_count,
                       COUNT(DISTINCT CASE WHEN e.stance = 'contradict'
                           THEN r.source_path END) AS contradict_game_count,
                       SUM(CASE WHEN e.id IS NOT NULL AND (
                           p.last_surfaced_at IS NULL
                           OR e.created_at > p.last_surfaced_at
                       ) THEN 1 ELSE 0 END) AS unseen_evidence_count
                FROM profile_items AS p
                LEFT JOIN profile_evidence AS e ON e.profile_item_id = p.id
                LEFT JOIN reviews AS r ON r.id = e.review_id
                {status_clause}
                GROUP BY p.id
                ORDER BY
                    CASE p.status
                        WHEN 'confirmed' THEN 0
                        WHEN 'tentative' THEN 1
                        ELSE 2
                    END,
                    p.updated_at DESC
                """
            ).fetchall()
        return [_profile_item_dict(row) for row in rows]

    def revise_profile_item(
        self,
        *,
        item_id: int,
        statement: str | None,
        scope: dict[str, Any] | None,
        confidence: float,
    ) -> dict[str, Any]:
        current = self.get_profile_item(item_id, evidence_limit=1)
        if current["status"] != "tentative":
            raise CoachError("Only tentative profile items can be revised by the coach")
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE profile_items
                SET statement = ?, scope_json = ?, confidence = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    statement if statement is not None else current["statement"],
                    json.dumps(
                        scope if scope is not None else current["scope"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    confidence,
                    now,
                    item_id,
                ),
            )
            connection.commit()
        return self.get_profile_item(item_id)

    def mark_profile_item_surfaced(self, item_id: int) -> dict[str, Any]:
        self.get_profile_item(item_id, evidence_limit=1)
        surfaced_at = _now()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE profile_items
                SET last_surfaced_at = ?, surfaced_count = surfaced_count + 1
                WHERE id = ?
                """,
                (surfaced_at, item_id),
            )
            connection.commit()
        return self.get_profile_item(item_id)

    def add_profile_evidence(
        self,
        *,
        item_id: int,
        review_id: str,
        decision_id: str,
        stance: str,
        note: str,
    ) -> dict[str, Any]:
        self.get_profile_item(item_id, evidence_limit=1)
        review = self.get_review(review_id)
        review.get_decision(decision_id)
        with closing(self._connect()) as connection:
            review_row = connection.execute(
                "SELECT model_tag FROM reviews WHERE id = ?",
                (review_id,),
            ).fetchone()
            if review_row is None:
                raise ReviewNotFoundError(f"Review not found: {review_id}")
            now = _now()
            connection.execute(
                """
                INSERT INTO profile_evidence (
                    profile_item_id, review_id, decision_id, stance, note,
                    model_tag, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_item_id, review_id, decision_id) DO UPDATE SET
                    stance = excluded.stance,
                    note = excluded.note,
                    model_tag = excluded.model_tag,
                    created_at = excluded.created_at
                """,
                (
                    item_id,
                    review_id,
                    decision_id,
                    stance,
                    note,
                    str(review_row["model_tag"]),
                    now,
                ),
            )
            connection.execute(
                "UPDATE profile_items SET updated_at = ? WHERE id = ?",
                (now, item_id),
            )
            connection.commit()
        return self.get_profile_item(item_id)

    def resolve_profile_item(
        self,
        *,
        item_id: int,
        action: str,
        statement: str | None = None,
        kind: str | None = None,
        category: str | None = None,
        scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.get_profile_item(item_id, evidence_limit=1)
        if action == "forget":
            with closing(self._connect()) as connection:
                connection.execute("DELETE FROM profile_items WHERE id = ?", (item_id,))
                connection.commit()
            return {"forgotten": True, "item_id": item_id}

        status = "confirmed" if action in {"confirm", "correct"} else "rejected"
        source = "user_corrected" if action == "correct" else f"user_{status}"
        now = _now()
        next_statement = statement if statement is not None else current["statement"]
        next_kind = kind if kind is not None else current["kind"]
        next_category = category if category is not None else current["category"]
        next_scope = scope if scope is not None else current["scope"]
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE profile_items
                SET statement = ?, kind = ?, category = ?, scope_json = ?,
                    status = ?, source = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    next_statement,
                    next_kind,
                    next_category,
                    json.dumps(next_scope, ensure_ascii=False, separators=(",", ":")),
                    status,
                    source,
                    now,
                    item_id,
                ),
            )
            connection.commit()
        return self.get_profile_item(item_id)

    def coaching_profile(
        self,
        *,
        include_rejected: bool = False,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            totals = connection.execute(
                """
                SELECT kind, category, COUNT(*) AS count
                FROM coaching_notes
                GROUP BY kind, category
                ORDER BY count DESC, category ASC
                """
            ).fetchall()
            recent = connection.execute(
                """
                SELECT review_id, decision_id, kind, category, note, created_at
                FROM coaching_notes
                ORDER BY created_at DESC
                LIMIT 30
                """
            ).fetchall()
        items = self.list_profile_items(include_rejected=include_rejected)
        return {
            "local_profile": self.get_local_identity(),
            "confirmed_profile": [
                item for item in items if item["status"] == "confirmed"
            ],
            "tentative_profile": [
                item for item in items if item["status"] == "tentative"
            ],
            "rejected_profile": [
                item for item in items if item["status"] == "rejected"
            ],
            "explicit_note_counts": [dict(row) for row in totals],
            "recent_explicit_notes": [dict(row) for row in recent],
            "observation_summary": self.observation_summary(),
        }


def _profile_item_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["scope"] = json.loads(result.pop("scope_json"))
    if "support_count" in result:
        result["support_count"] = int(result["support_count"] or 0)
    if "contradict_count" in result:
        result["contradict_count"] = int(result["contradict_count"] or 0)
    if "support_game_count" in result:
        result["support_game_count"] = int(result["support_game_count"] or 0)
    if "contradict_game_count" in result:
        result["contradict_game_count"] = int(result["contradict_game_count"] or 0)
    if "unseen_evidence_count" in result:
        result["unseen_evidence_count"] = int(result["unseen_evidence_count"] or 0)
    if "surfaced_count" in result:
        result["surfaced_count"] = int(result["surfaced_count"] or 0)
    return result


def _source_game_key(source_path: str) -> str:
    paipu_uuid = extract_paipu_uuid(source_path)
    if paipu_uuid:
        return f"paipu:{paipu_uuid}"
    digest = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]
    return f"source:{digest}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
