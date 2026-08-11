from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from .errors import CoachError, ReviewerError
from .logs import LogMetadata, inspect_tenhou_v6_log
from .remote import MortalWebProvider
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


class CoachService:
    def __init__(
        self,
        *,
        repository: ReviewRepository | None = None,
        reviewer: MortalReviewer | None = None,
        web_provider: MortalWebProvider | None = None,
    ) -> None:
        self.repository = repository or ReviewRepository(default_database_path())
        self.reviewer = reviewer or MortalReviewer(ReviewerConfig.from_env())
        self.web_provider = web_provider or MortalWebProvider()

    def check_setup(self) -> dict[str, Any]:
        return {
            "reviewer": self.reviewer.config.status(),
            "database": str(self.repository.database_path),
            "providers": {
                "local_mortal": self.reviewer.config.status(),
                "mortal_web": self.web_provider.status(),
                "koromo_catalog": {
                    "selected_source": True,
                    "identity": "one local profile with confirmed Koromo accounts",
                    "coverage": "four-player Gold, Jade, and Throne ranked rooms",
                    "current_stage": "local account binding ready; incremental game sync pending",
                    "requires_majsoul_login": False,
                },
            },
            "scope": {
                "source": "Mahjong Soul exports or HTTPS paipu URLs",
                "seats": 4,
                "game_length": "hanchan only",
                "data_and_coach": "local only",
            },
        }

    def prepare_web_review(
        self,
        log_url: str,
        *,
        language: str = "zh-CN",
        model_tag: str = "4.1b",
        kyokus: str | None = None,
    ) -> dict[str, Any]:
        return self.web_provider.prepare(
            log_url,
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
        return self.repository.coaching_profile(
            include_rejected=include_rejected,
        )


def default_database_path() -> Path:
    configured = os.environ.get("MJTUTOR_DATA_DIR")
    if configured:
        data_dir = Path(configured).expanduser()
    else:
        data_dir = Path(__file__).resolve().parents[2] / "data"
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
