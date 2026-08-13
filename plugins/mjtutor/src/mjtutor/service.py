from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .errors import CoachError, ReviewerError
from .koromo_catalog import (
    DEFAULT_INITIAL_LOOKBACK_DAYS,
    DEFAULT_SYNC_INTERVAL_MINUTES,
    KOROMO_WEB_URL,
    KoromoAccessError,
    KoromoCatalogClient,
    KoromoVerificationRequired,
)
from .logs import LogMetadata, inspect_tenhou_v6_log
from .remote import (
    MortalWebProvider,
    mortal_model_catalog,
    validate_majsoul_url,
    validate_mortal_model_tag,
    validate_mortal_web_language,
)
from .reviewer import MortalReviewer, ReviewerConfig, load_review_file
from .storage import ReviewRepository

ALLOWED_NOTE_KINDS = {"mistake", "style_preference", "question", "understood"}
ALLOWED_PROFILE_KINDS = ALLOWED_NOTE_KINDS | {
    "goal",
    "strength",
    "teaching_preference",
    "pattern",
}
ALLOWED_EVIDENCE_STANCES = {"support", "contradict"}
ALLOWED_PROFILE_ACTIONS = {"confirm", "correct", "reject", "forget"}
DEFAULT_MORTAL_MODEL_SETTING = "default_mortal_model"


class CoachService:
    def __init__(
        self,
        *,
        repository: ReviewRepository | None = None,
        reviewer: MortalReviewer | None = None,
        web_provider: MortalWebProvider | None = None,
        koromo_client: KoromoCatalogClient | None = None,
    ) -> None:
        self.repository = repository or ReviewRepository(default_database_path())
        self.reviewer = reviewer or MortalReviewer(ReviewerConfig.from_env())
        self.web_provider = web_provider or MortalWebProvider()
        self.koromo_client = koromo_client or KoromoCatalogClient()

    def check_setup(self) -> dict[str, Any]:
        return {
            "reviewer": self.reviewer.config.status(),
            "database": str(self.repository.database_path),
            "providers": {
                "local_mortal": self.reviewer.config.status(),
                "mortal_web": self.web_provider.status(),
                "koromo_catalog": {
                    **self.koromo_client.status(),
                    "selected_source": True,
                    "identity": "one local profile with confirmed Koromo accounts",
                    "current_stage": "local incremental catalog and MCP App available",
                    "requires_majsoul_login": False,
                },
            },
            "scope": {
                "source": "Mahjong Soul exports or HTTPS paipu URLs",
                "seats": 4,
                "game_length": "hanchan only",
                "data_and_coach": "local only",
            },
            "analysis_preferences": self.analysis_preferences(),
        }

    def analysis_preferences(self) -> dict[str, Any]:
        model_tag = self.repository.get_local_setting(DEFAULT_MORTAL_MODEL_SETTING)
        if not isinstance(model_tag, str) or model_tag not in {
            item["tag"] for item in mortal_model_catalog()
        }:
            model_tag = None
        return {
            "default_mortal_model": model_tag,
            "available_mortal_models": mortal_model_catalog(),
        }

    def set_default_mortal_model(self, model_tag: str) -> dict[str, Any]:
        validated = validate_mortal_model_tag(model_tag)
        self.repository.set_local_setting(DEFAULT_MORTAL_MODEL_SETTING, validated)
        return self.analysis_preferences()

    def clear_default_mortal_model(self) -> dict[str, Any]:
        self.repository.delete_local_setting(DEFAULT_MORTAL_MODEL_SETTING)
        return self.analysis_preferences()

    def prepare_web_review(
        self,
        log_url: str,
        *,
        language: str = "zh-CN",
        model_tag: str | None = None,
        kyokus: str | None = None,
    ) -> dict[str, Any]:
        normalized_log_url = validate_majsoul_url(log_url)
        validate_mortal_web_language(language)
        if model_tag is None:
            preference = self.analysis_preferences()
            model_tag = preference["default_mortal_model"]
            if model_tag is None:
                return {
                    "provider": "mortal_web",
                    "status": "model_preference_required",
                    "majsoul_log_url": normalized_log_url,
                    "available_mortal_models": preference["available_mortal_models"],
                    "automatic_submission": False,
                }
        return self.web_provider.prepare(
            normalized_log_url,
            language=language,
            model_tag=model_tag,
            kyokus=kyokus,
        )

    def import_web_report(
        self,
        report_url: str,
        *,
        source_log_url: str,
    ) -> dict[str, Any]:
        imported = self.web_provider.fetch_report(
            report_url,
            source_log_url=source_log_url,
        )
        review_id = make_review_id(imported.metadata, imported.player_id)
        account_id = self.repository.save_review(
            review_id=review_id,
            metadata=imported.metadata,
            player_id=imported.player_id,
            review=imported.review,
        )
        return {
            "review_id": review_id,
            "source_log_url": source_log_url,
            "report_json_url": imported.report_json_url,
            "account_id": account_id,
            "summary": imported.review.summary(),
        }

    def inspect_log(self, log_path: str) -> dict[str, Any]:
        return inspect_tenhou_v6_log(log_path).as_dict()

    def review_log(
        self,
        log_path: str,
        *,
        player_id: int,
        kyokus: str | None = None,
    ) -> dict[str, Any]:
        result = self.reviewer.review(log_path, player_id=player_id, kyokus=kyokus)
        review_id = make_review_id(result.metadata, player_id)
        account_id = self.repository.save_review(
            review_id=review_id,
            metadata=result.metadata,
            player_id=player_id,
            review=result.review,
        )
        return {
            "review_id": review_id,
            "account_id": account_id,
            "log": result.metadata.as_dict(),
            "summary": result.review.summary(),
        }

    def import_review(
        self,
        review_path: str,
        *,
        source_log_path: str,
        player_id: int,
    ) -> dict[str, Any]:
        if player_id not in range(4):
            raise ReviewerError("player_id must be within 0-3")
        metadata = inspect_tenhou_v6_log(source_log_path)
        review = load_review_file(review_path, player_id=player_id)
        review_id = make_review_id(metadata, player_id)
        account_id = self.repository.save_review(
            review_id=review_id,
            metadata=metadata,
            player_id=player_id,
            review=review,
        )
        return {
            "review_id": review_id,
            "account_id": account_id,
            "summary": review.summary(),
        }

    def bind_koromo_account(
        self,
        *,
        nickname: str,
        koromo_player_id: int,
    ) -> dict[str, Any]:
        return self.repository.bind_koromo_account(
            nickname=nickname,
            koromo_player_id=koromo_player_id,
        )

    def sync_koromo_games(
        self,
        *,
        account_id: int | None = None,
        force: bool = False,
        lookback_days: int = DEFAULT_INITIAL_LOOKBACK_DAYS,
        max_pages: int = 10,
    ) -> dict[str, Any]:
        identity = self.repository.get_local_identity()
        accounts = identity["accounts"]
        if account_id is not None:
            accounts = [
                item for item in accounts if int(item["account_id"]) == account_id
            ]
            if not accounts:
                raise CoachError(f"Koromo account is not bound: {account_id}")
        lookback_days = max(1, min(int(lookback_days), 3650))
        max_pages = max(1, min(int(max_pages), 50))
        results = [
            self._sync_koromo_account(
                account_id=int(account["account_id"]),
                force=force,
                lookback_days=lookback_days,
                max_pages=max_pages,
            )
            for account in accounts
        ]
        return {
            "accounts": results,
            "automatic_policy": (
                "Opening the catalog may trigger an incremental sync after the minimum "
                "interval. No resident background process is installed."
            ),
            "external_analysis_started": False,
        }

    def _sync_koromo_account(
        self,
        *,
        account_id: int,
        force: bool,
        lookback_days: int,
        max_pages: int,
    ) -> dict[str, Any]:
        current = self.repository.get_koromo_sync_status(account_id=account_id)[
            "accounts"
        ][0]
        last_attempt = _parse_timestamp(current.get("last_attempt_at"))
        now = datetime.now(UTC)
        if (
            not force
            and last_attempt is not None
            and now - last_attempt < timedelta(minutes=DEFAULT_SYNC_INTERVAL_MINUTES)
        ):
            return {
                **current,
                "skipped": True,
                "skip_reason": "minimum_sync_interval",
            }

        latest = current.get("latest_game_start")
        if latest is None:
            start_ms = int((now - timedelta(days=lookback_days)).timestamp() * 1000)
        else:
            # Repeat a week so delayed Koromo records are not missed.
            start_ms = max(0, (int(latest) - 7 * 24 * 60 * 60) * 1000)
        end_ms = int(now.timestamp() * 1000)
        fetched: dict[str, dict[str, Any]] = {}
        try:
            for _ in range(max_pages):
                page = self.koromo_client.fetch_games(
                    account_id=account_id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    limit=100,
                )
                for game in page:
                    fetched[game.uuid] = game.as_dict(account_id=account_id)
                if len(page) < 100:
                    break
                oldest_start_ms = min(game.start_time for game in page) * 1000
                if oldest_start_ms <= start_ms:
                    break
                end_ms = oldest_start_ms - 1
        except KoromoVerificationRequired as error:
            state = self.repository.record_koromo_sync(
                account_id=account_id,
                status="verification_required",
                success=False,
                error=str(error),
            )["accounts"][0]
            return {
                **state,
                "skipped": False,
                "fetched": 0,
                "inserted": 0,
                "updated": 0,
                "koromo_web_url": KOROMO_WEB_URL,
            }
        except KoromoAccessError as error:
            state = self.repository.record_koromo_sync(
                account_id=account_id,
                status="unavailable",
                success=False,
                error=str(error),
            )["accounts"][0]
            return {
                **state,
                "skipped": False,
                "fetched": 0,
                "inserted": 0,
                "updated": 0,
                "koromo_web_url": KOROMO_WEB_URL,
            }

        saved = self.repository.save_koromo_games(
            account_id=account_id,
            games=list(fetched.values()),
        )
        latest_game_start = max(
            (int(game["start_time"]) for game in fetched.values()),
            default=None,
        )
        state = self.repository.record_koromo_sync(
            account_id=account_id,
            status="ok",
            success=True,
            latest_game_start=latest_game_start,
        )["accounts"][0]
        return {
            **state,
            "skipped": False,
            "fetched": len(fetched),
            **saved,
        }

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
        auto_sync: bool = False,
    ) -> dict[str, Any]:
        sync = self.sync_koromo_games(account_id=account_id) if auto_sync else None
        result = self.repository.list_koromo_games(
            account_id=account_id,
            rank=rank,
            reviewed=reviewed,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )
        result["sync"] = sync
        result["catalog_notice"] = (
            "Koromo is third-party, delayed, and potentially incomplete. Only cached "
            "public ranked-game metadata is returned; no Mortal analysis is started."
        )
        return result

    def koromo_sync_status(self, *, account_id: int | None = None) -> dict[str, Any]:
        return {
            **self.repository.get_koromo_sync_status(account_id=account_id),
            "provider": self.koromo_client.status(),
            "minimum_sync_interval_minutes": DEFAULT_SYNC_INTERVAL_MINUTES,
        }

    def prepare_selected_game_review(
        self,
        uuid: str,
        *,
        model_tag: str | None = None,
    ) -> dict[str, Any]:
        game = self.repository.get_koromo_game(uuid.strip())
        compact_game = {
            "uuid": game["uuid"],
            "account_id": game["account_id"],
            "account_nickname": game["account_nickname"],
            "mode_label": game["mode_label"],
            "start_time": game["start_time"],
            "player_rank": game["player_rank"],
            "player_score": game["player_score"],
            "paipu_url": game["paipu_url"],
            "reviewed": game["reviewed"],
            "review_id": game["review_id"],
        }
        if game["reviewed"]:
            return {
                "status": "already_reviewed",
                "game": compact_game,
                "review_id": game["review_id"],
                "mortal_web": None,
                "external_analysis_started": False,
            }
        prepared = self.prepare_web_review(
            str(game["paipu_url"]),
            language="zh-CN",
            model_tag=model_tag,
        )
        if prepared["status"] == "model_preference_required":
            return {
                "status": "model_preference_required",
                "game": compact_game,
                "mortal_web": prepared,
                "external_analysis_started": False,
            }
        return {
            "status": "awaiting_human_verification",
            "game": compact_game,
            "mortal_web": prepared,
            "external_analysis_started": False,
        }

    def list_reviews(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.repository.list_reviews(limit=limit)

    def review_summary(self, review_id: str, *, weak_limit: int = 10) -> dict[str, Any]:
        return self.repository.get_review(review_id).summary(weak_limit=weak_limit)

    def decision(
        self,
        review_id: str,
        decision_id: str,
        *,
        candidate_limit: int = 8,
    ) -> dict[str, Any]:
        review = self.repository.get_review(review_id)
        return review.get_decision(decision_id).as_dict(candidate_limit=candidate_limit)

    def record_note(
        self,
        review_id: str,
        decision_id: str,
        *,
        kind: str,
        category: str,
        note: str,
    ) -> dict[str, Any]:
        if kind not in ALLOWED_NOTE_KINDS:
            raise CoachError(
                f"kind must be one of: {', '.join(sorted(ALLOWED_NOTE_KINDS))}"
            )
        category = category.strip()
        note = note.strip()
        if not category or not note:
            raise CoachError("category and note must not be empty")
        return self.repository.add_note(
            review_id=review_id,
            decision_id=decision_id,
            kind=kind,
            category=category,
            note=note,
        )

    def local_observations(
        self,
        *,
        disagreements_only: bool = True,
        actual_type: str | None = None,
        expected_type: str | None = None,
        limit: int = 12,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self.repository.list_observations(
            disagreements_only=disagreements_only,
            actual_type=_optional_text(actual_type),
            expected_type=_optional_text(expected_type),
            limit=limit,
            offset=offset,
        )

    def propose_profile_item(
        self,
        *,
        kind: str,
        category: str,
        statement: str,
        scope: dict[str, Any] | None = None,
        confidence: float,
    ) -> dict[str, Any]:
        kind, category, statement = _validate_profile_text(kind, category, statement)
        confidence = _validate_confidence(confidence)
        return self.repository.create_profile_item(
            kind=kind,
            category=category,
            statement=statement,
            scope=scope or {},
            status="tentative",
            confidence=confidence,
            source="coach_hypothesis",
        )

    def record_profile_memory(
        self,
        *,
        kind: str,
        category: str,
        statement: str,
        scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kind, category, statement = _validate_profile_text(kind, category, statement)
        return self.repository.create_profile_item(
            kind=kind,
            category=category,
            statement=statement,
            scope=scope or {},
            status="confirmed",
            confidence=1.0,
            source="user_confirmed",
        )

    def add_profile_evidence(
        self,
        *,
        item_id: int,
        review_id: str,
        decision_id: str,
        stance: str,
        note: str,
    ) -> dict[str, Any]:
        if stance not in ALLOWED_EVIDENCE_STANCES:
            raise CoachError(
                f"stance must be one of: {', '.join(sorted(ALLOWED_EVIDENCE_STANCES))}"
            )
        note = note.strip()
        if not note:
            raise CoachError("evidence note must not be empty")
        return self.repository.add_profile_evidence(
            item_id=item_id,
            review_id=review_id,
            decision_id=decision_id,
            stance=stance,
            note=note,
        )

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
        if action not in ALLOWED_PROFILE_ACTIONS:
            raise CoachError(
                f"action must be one of: {', '.join(sorted(ALLOWED_PROFILE_ACTIONS))}"
            )
        if action == "correct" and not _optional_text(statement):
            raise CoachError("correct requires a non-empty replacement statement")
        if kind is not None and kind not in ALLOWED_PROFILE_KINDS:
            raise CoachError(
                f"kind must be one of: {', '.join(sorted(ALLOWED_PROFILE_KINDS))}"
            )
        return self.repository.resolve_profile_item(
            item_id=item_id,
            action=action,
            statement=_optional_text(statement),
            kind=kind,
            category=_optional_text(category),
            scope=scope,
        )

    def profile_item(self, item_id: int, *, evidence_limit: int = 20) -> dict[str, Any]:
        return self.repository.get_profile_item(item_id, evidence_limit=evidence_limit)

    def local_profile(
        self,
        *,
        include_rejected: bool = False,
    ) -> dict[str, Any]:
        profile = self.repository.coaching_profile(
            include_rejected=include_rejected,
        )
        profile["analysis_preferences"] = self.analysis_preferences()
        return profile


def default_database_path() -> Path:
    configured = os.environ.get("MJTUTOR_DATA_DIR")
    if configured:
        data_dir = Path(configured).expanduser()
    else:
        configured_home = os.environ.get("XDG_DATA_HOME")
        data_home = (
            Path(configured_home).expanduser()
            if configured_home
            else Path.home() / ".local" / "share"
        )
        data_dir = data_home / "mjtutor"
    return data_dir / "coach.sqlite3"


def make_review_id(metadata: LogMetadata, player_id: int) -> str:
    digest = hashlib.sha256(f"{metadata.sha256}:{player_id}".encode()).hexdigest()
    return digest[:16]


def _validate_profile_text(
    kind: str,
    category: str,
    statement: str,
) -> tuple[str, str, str]:
    if kind not in ALLOWED_PROFILE_KINDS:
        raise CoachError(
            f"kind must be one of: {', '.join(sorted(ALLOWED_PROFILE_KINDS))}"
        )
    category = category.strip()
    statement = statement.strip()
    if not category or not statement:
        raise CoachError("category and statement must not be empty")
    return kind, category, statement


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _validate_confidence(value: float) -> float:
    confidence = float(value)
    if not 0.0 <= confidence <= 1.0:
        raise CoachError("confidence must be between 0 and 1")
    return confidence


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
