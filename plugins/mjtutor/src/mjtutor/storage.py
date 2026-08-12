from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import CoachError, ProfileItemNotFoundError, ReviewNotFoundError
from .koromo import extract_koromo_player_id, extract_paipu_uuid
from .logs import LogMetadata
from .models import ReviewDocument

SCHEMA_VERSION = 3
LOCAL_PROFILE_ID = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS local_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS majsoul_accounts (
    account_id INTEGER PRIMARY KEY,
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
    updated_at TEXT NOT NULL
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

    @staticmethod
    def _execute_schema(connection: sqlite3.Connection) -> None:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                connection.execute(statement)

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
                "This database contains multiple legacy players. MJTutor will not merge "
                "their profiles automatically; resolve them before single-user migration."
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
                    account_id, local_profile_id, nickname, created_at, updated_at
                ) VALUES (?, 1, ?, ?, ?)
                """,
                (
                    account_id,
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
                    or extract_koromo_player_id(str(row["source_path"]))
                    == int(legacy_player["koromo_player_id"])
                )
            ):
                account_id = int(legacy_player["koromo_player_id"])
            connection.execute(
                """
                INSERT INTO reviews (
                    id, source_path, source_sha256, player_id, player_name,
                    rule_display, model_tag, created_at, report_json, account_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                INSERT INTO decision_observations ({', '.join(observation_fields)})
                VALUES ({', '.join('?' for _ in observation_fields)})
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
                INSERT INTO profile_items ({', '.join(profile_fields)})
                VALUES ({', '.join('?' for _ in profile_fields)})
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
                INSERT INTO profile_evidence ({', '.join(evidence_fields)})
                VALUES ({', '.join('?' for _ in evidence_fields)})
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

    def bind_koromo_account(
        self,
        *,
        nickname: str,
        koromo_player_id: int,
    ) -> dict[str, Any]:
        nickname = nickname.strip()
        if not nickname:
            raise CoachError("nickname must not be empty")
        if koromo_player_id <= 0:
            raise CoachError("koromo_player_id must be a positive integer")
        now = _now()
        with closing(self._connect()) as connection:
            existing = connection.execute(
                """
                SELECT nickname, created_at
                FROM majsoul_accounts
                WHERE account_id = ?
                """,
                (koromo_player_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO majsoul_accounts (
                        account_id, local_profile_id, nickname, created_at, updated_at
                    ) VALUES (?, 1, ?, ?, ?)
                    """,
                    (koromo_player_id, nickname, now, now),
                )
                created_at = now
            else:
                created_at = str(existing["created_at"])
                if str(existing["nickname"]) != nickname:
                    connection.execute(
                        """
                        UPDATE account_nicknames
                        SET is_current = 0
                        WHERE account_id = ?
                        """,
                        (koromo_player_id,),
                    )
                connection.execute(
                    """
                    UPDATE majsoul_accounts
                    SET nickname = ?, updated_at = ?
                    WHERE account_id = ?
                    """,
                    (nickname, now, koromo_player_id),
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
                (koromo_player_id, nickname, now, now),
            )
            connection.execute(
                "UPDATE local_profile SET updated_at = ? WHERE id = 1",
                (now,),
            )
            connection.commit()

        bound_review_ids = self._backfill_account_reviews(koromo_player_id)
        return {
            "account_id": koromo_player_id,
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
                SELECT a.account_id, a.nickname, a.created_at, a.updated_at,
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
            item["nickname_history"] = by_account.get(int(item["account_id"]), [])
            account_results.append(item)
        return {
            "id": int(profile["id"]),
            "created_at": str(profile["created_at"]),
            "updated_at": str(profile["updated_at"]),
            "accounts": account_results,
        }

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
            if connection.execute(
                "SELECT 1 FROM majsoul_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone() is None:
                raise CoachError(f"Koromo account is not bound: {account_id}")
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
                        json.dumps(
                            game["players"], ensure_ascii=False, separators=(",", ":")
                        ),
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
                "SELECT last_success_at, latest_game_start FROM koromo_sync_state WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            previous_latest = (
                int(current["latest_game_start"])
                if current is not None and current["latest_game_start"] is not None
                else None
            )
            next_latest = max(
                value
                for value in (previous_latest, latest_game_start)
                if value is not None
            ) if previous_latest is not None or latest_game_start is not None else None
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
            accounts = [item for item in accounts if int(item["account_id"]) == account_id]
            if not accounts:
                raise CoachError(f"Koromo account is not bound: {account_id}")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM koromo_sync_state ORDER BY account_id"
            ).fetchall()
        states = {int(row["account_id"]): dict(row) for row in rows}
        results = []
        for account in accounts:
            item = {
                "account_id": int(account["account_id"]),
                "nickname": str(account["nickname"]),
                "last_attempt_at": None,
                "last_success_at": None,
                "latest_game_start": None,
                "status": "never",
                "last_error": None,
                "cached_game_count": 0,
            }
            item.update(states.get(item["account_id"], {}))
            results.append(item)
        return {"accounts": results}

    def list_koromo_games(
        self,
        *,
        account_id: int | None = None,
        rank: int | None = None,
        reviewed: bool | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        conditions: list[str] = []
        parameters: list[Any] = []
        if account_id is not None:
            conditions.append("g.account_id = ?")
            parameters.append(account_id)
        if rank is not None:
            if rank not in range(1, 5):
                raise CoachError("rank must be within 1-4")
            conditions.append("g.player_rank = ?")
            parameters.append(rank)
        if reviewed is not None:
            conditions.append("g.review_id IS NOT NULL" if reviewed else "g.review_id IS NULL")
        if start_time is not None:
            conditions.append("g.start_time >= ?")
            parameters.append(start_time)
        if end_time is not None:
            conditions.append("g.start_time <= ?")
            parameters.append(end_time)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        page_limit = max(1, min(int(limit), 100))
        page_offset = max(0, int(offset))
        with closing(self._connect()) as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM koromo_games AS g {where}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT g.*, a.nickname AS account_nickname
                FROM koromo_games AS g
                JOIN majsoul_accounts AS a ON a.account_id = g.account_id
                {where}
                ORDER BY g.start_time DESC, g.uuid
                LIMIT ? OFFSET ?
                """,
                (*parameters, page_limit, page_offset),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["players"] = json.loads(item.pop("players_json"))
            item["reviewed"] = item["review_id"] is not None
            items.append(item)
        return {
            "items": items,
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
            "has_more": page_offset + len(items) < total,
        }

    def get_koromo_game(self, uuid: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT g.*, a.nickname AS account_nickname
                FROM koromo_games AS g
                JOIN majsoul_accounts AS a ON a.account_id = g.account_id
                WHERE g.uuid = ?
                """,
                (uuid,),
            ).fetchone()
        if row is None:
            raise CoachError(f"Koromo game is not cached: {uuid}")
        item = dict(row)
        item["players"] = json.loads(item.pop("players_json"))
        item["reviewed"] = item["review_id"] is not None
        return item

    def save_review(
        self,
        *,
        review_id: str,
        metadata: LogMetadata,
        player_id: int,
        review: ReviewDocument,
    ) -> int | None:
        player_name = metadata.player_names[player_id]
        now = _now()
        payload = json.dumps(review.raw, ensure_ascii=False, separators=(",", ":"))
        account_id = self._registered_account_for_source(metadata.path)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO reviews (
                    id, source_path, source_sha256, player_id, player_name,
                    rule_display, model_tag, created_at, report_json, account_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source_path = excluded.source_path,
                    source_sha256 = excluded.source_sha256,
                    player_id = excluded.player_id,
                    player_name = excluded.player_name,
                    rule_display = excluded.rule_display,
                    model_tag = excluded.model_tag,
                    created_at = excluded.created_at,
                    report_json = excluded.report_json,
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
        account_id = extract_koromo_player_id(source)
        if account_id is None:
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT account_id FROM majsoul_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        return int(row["account_id"]) if row is not None else None

    def _backfill_account_reviews(self, account_id: int) -> list[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, source_path FROM reviews WHERE account_id IS NULL"
            ).fetchall()
            matching = [
                str(row["id"])
                for row in rows
                if extract_koromo_player_id(str(row["source_path"])) == account_id
            ]
            connection.executemany(
                "UPDATE reviews SET account_id = ? WHERE id = ?",
                ((account_id, review_id) for review_id in matching),
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
                json.dumps(decision.expected, ensure_ascii=False, separators=(",", ":")),
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
                SELECT r.id, r.source_path, r.player_id, r.player_name,
                       r.rule_display, r.model_tag, r.created_at, r.account_id,
                       a.nickname AS account_nickname
                FROM reviews AS r
                LEFT JOIN majsoul_accounts AS a ON a.account_id = r.account_id
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

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
                       COUNT(DISTINCT review_id) AS reviewed_games,
                       COALESCE(SUM(matches_mortal), 0) AS mortal_matches
                FROM decision_observations
                """
            ).fetchone()
            models = connection.execute(
                """
                SELECT model_tag, COUNT(DISTINCT review_id) AS reviewed_games,
                       COUNT(*) AS decision_count,
                       SUM(matches_mortal) AS mortal_matches
                FROM decision_observations
                GROUP BY model_tag
                ORDER BY reviewed_games DESC, model_tag
                """
            ).fetchall()
            patterns = connection.execute(
                """
                SELECT actual_type, expected_type, COUNT(*) AS count
                FROM decision_observations
                WHERE matches_mortal = 0
                GROUP BY actual_type, expected_type
                ORDER BY count DESC, actual_type, expected_type
                LIMIT 12
                """
            ).fetchall()
        decision_count = int(totals["decision_count"])
        mortal_matches = int(totals["mortal_matches"])
        return {
            "reviewed_games": int(totals["reviewed_games"]),
            "decision_count": decision_count,
            "mortal_matches": mortal_matches,
            "match_rate": mortal_matches / decision_count if decision_count else None,
            "by_model": [dict(row) for row in models],
            "disagreement_action_patterns": [dict(row) for row in patterns],
            "interpretation_notice": (
                "These are objective action comparisons, not stable traits. "
                "Q values and match rates from different Mortal model tags must not be merged "
                "into a universal skill score."
            ),
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
                SELECT review_id, decision_id, model_tag, round_label, honba,
                       turn, tiles_left, shanten, furiten, actual_type,
                       expected_type, actual_action_json, expected_action_json,
                       matches_mortal, actual_rank, q_gap
                FROM decision_observations
                WHERE {where}
                ORDER BY created_at DESC, review_id, decision_id
                LIMIT ? OFFSET ?
                """,
                (*parameters, page_limit, page_offset),
            ).fetchall()
        observations = []
        for row in rows:
            item = dict(row)
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
                SELECT id, review_id, decision_id, stance, note, model_tag, created_at
                FROM profile_evidence
                WHERE profile_item_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (item_id, max(1, min(evidence_limit, 100))),
            ).fetchall()
        result = _profile_item_dict(row)
        result["evidence"] = [dict(item) for item in evidence]
        result["evidence_notice"] = (
            "support and contradict examples are references to reviewed decisions; "
            "use get_decision for the full table context."
        )
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
                           AS contradict_count
                FROM profile_items AS p
                LEFT JOIN profile_evidence AS e ON e.profile_item_id = p.id
                {status_clause}
                GROUP BY p.id
                ORDER BY
                    CASE p.status WHEN 'confirmed' THEN 0 WHEN 'tentative' THEN 1 ELSE 2 END,
                    p.updated_at DESC
                """
            ).fetchall()
        return [_profile_item_dict(row) for row in rows]

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
            "confirmed_profile": [item for item in items if item["status"] == "confirmed"],
            "tentative_profile": [item for item in items if item["status"] == "tentative"],
            "rejected_profile": [item for item in items if item["status"] == "rejected"],
            "explicit_note_counts": [dict(row) for row in totals],
            "recent_explicit_notes": [dict(row) for row in recent],
            "observation_summary": self.observation_summary(),
            "notice": (
                "Confirmed items reflect explicit user confirmation. Tentative items are "
                "coach hypotheses and must remain confidence-labelled and context-specific. "
                "Objective observations and Mortal disagreement are not automatically weaknesses."
            ),
        }


def _profile_item_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["scope"] = json.loads(result.pop("scope_json"))
    if "support_count" in result:
        result["support_count"] = int(result["support_count"] or 0)
    if "contradict_count" in result:
        result["contradict_count"] = int(result["contradict_count"] or 0)
    return result


def _now() -> str:
    return datetime.now(UTC).isoformat()
