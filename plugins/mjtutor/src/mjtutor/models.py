from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .context import reconstruct_decision_contexts
from .errors import ReviewerError


@dataclass(frozen=True)
class Candidate:
    action: dict[str, Any]
    q_value: float
    probability: float

    @classmethod
    def from_json(cls, raw: Any) -> Candidate:
        if not isinstance(raw, dict) or not isinstance(raw.get("action"), dict):
            raise ReviewerError("Review candidate is missing its action")
        return cls(
            action=raw["action"],
            q_value=float(raw.get("q_value", 0.0)),
            probability=float(raw.get("prob", 0.0)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "q_value": self.q_value,
            "probability": self.probability,
        }


@dataclass(frozen=True)
class Decision:
    decision_id: str
    round_label: str
    honba: int
    index: int
    turn: int
    tiles_left: int
    hand_state: dict[str, Any]
    expected: dict[str, Any]
    actual: dict[str, Any]
    matches_mortal: bool
    shanten: int
    furiten: bool
    actual_index: int
    candidates: tuple[Candidate, ...]
    last_actor: int | None
    tile: str | None
    at_self_chi_pon: bool
    at_self_riichi: bool
    at_opponent_kakan: bool
    public_context: dict[str, Any] | None = None

    @classmethod
    def from_json(
        cls,
        raw: Any,
        *,
        kyoku: int,
        honba: int,
        index: int,
    ) -> Decision:
        if not isinstance(raw, dict):
            raise ReviewerError("Review decision must be a JSON object")
        details = raw.get("details")
        if not isinstance(details, list) or not details:
            raise ReviewerError("Review decision has no Mortal candidates")
        candidates = tuple(Candidate.from_json(item) for item in details)
        actual_index = int(raw.get("actual_index", -1))
        if actual_index not in range(len(candidates)):
            raise ReviewerError("Review decision has an invalid actual_index")

        label = round_label(kyoku)
        return cls(
            decision_id=f"k{kyoku}.{honba}:d{index}",
            round_label=label,
            honba=honba,
            index=index,
            turn=int(raw.get("junme", 0)),
            tiles_left=int(raw.get("tiles_left", 0)),
            hand_state=_dict_or_empty(raw.get("state")),
            expected=_dict_or_empty(raw.get("expected")),
            actual=_dict_or_empty(raw.get("actual")),
            matches_mortal=bool(raw.get("is_equal", False)),
            shanten=int(raw.get("shanten", 0)),
            furiten=bool(raw.get("at_furiten", False)),
            actual_index=actual_index,
            candidates=candidates,
            last_actor=(
                int(raw["last_actor"])
                if isinstance(raw.get("last_actor"), int)
                else None
            ),
            tile=str(raw["tile"]) if isinstance(raw.get("tile"), str) else None,
            at_self_chi_pon=bool(raw.get("at_self_chi_pon", False)),
            at_self_riichi=bool(raw.get("at_self_riichi", False)),
            at_opponent_kakan=bool(raw.get("at_opponent_kakan", False)),
        )

    @property
    def best_candidate(self) -> Candidate:
        return self.candidates[0]

    @property
    def actual_candidate(self) -> Candidate:
        return self.candidates[self.actual_index]

    @property
    def q_gap(self) -> float:
        return self.best_candidate.q_value - self.actual_candidate.q_value

    def as_dict(
        self,
        *,
        candidate_limit: int | None = None,
        include_context: bool = True,
    ) -> dict[str, Any]:
        candidates = self.candidates
        if candidate_limit is not None:
            candidates = candidates[: max(1, candidate_limit)]
            if self.actual_index >= len(candidates):
                candidates = (*candidates, self.actual_candidate)
        result = {
            "decision_id": self.decision_id,
            "round": self.round_label,
            "honba": self.honba,
            "turn": self.turn,
            "tiles_left": self.tiles_left,
            "hand_state": self.hand_state,
            "expected": self.expected,
            "actual": self.actual,
            "matches_mortal": self.matches_mortal,
            "shanten": self.shanten,
            "furiten": self.furiten,
            "actual_rank": self.actual_index + 1,
            "q_gap": self.q_gap,
            "candidates": [candidate.as_dict() for candidate in candidates],
        }
        if include_context:
            result["public_context"] = self.public_context or {
                "available": False,
                "information_scope": "target_player_public_view_before_decision",
                "reason": "Public table context was not reconstructed.",
            }
        return result


@dataclass(frozen=True)
class ReviewDocument:
    model_tag: str
    rating: float | None
    total_reviewed: int
    total_matches: int
    decisions: tuple[Decision, ...]
    raw: dict[str, Any]

    @classmethod
    def from_json(cls, raw: Any, *, player_id: int | None = None) -> ReviewDocument:
        if not isinstance(raw, dict):
            raise ReviewerError("mjai-reviewer output must be a JSON object")
        review = raw.get("review", raw)
        if not isinstance(review, dict):
            raise ReviewerError("mjai-reviewer output is missing the review object")
        kyokus = review.get("kyokus")
        if not isinstance(kyokus, list):
            raise ReviewerError("Mortal review is missing kyokus")

        decisions: list[Decision] = []
        for fallback_kyoku, kyoku_raw in enumerate(kyokus):
            if not isinstance(kyoku_raw, dict):
                raise ReviewerError("Mortal kyoku entry must be a JSON object")
            kyoku = int(kyoku_raw.get("kyoku", fallback_kyoku))
            honba = int(kyoku_raw.get("honba", 0))
            entries = kyoku_raw.get("entries", [])
            if not isinstance(entries, list):
                raise ReviewerError("Mortal kyoku entries must be a list")
            decisions.extend(
                Decision.from_json(entry, kyoku=kyoku, honba=honba, index=index)
                for index, entry in enumerate(entries)
            )

        raw_player_id = raw.get("player_id") if isinstance(raw, dict) else None
        resolved_player_id = player_id if player_id is not None else raw_player_id
        decision_tuple = tuple(decisions)
        contexts = reconstruct_decision_contexts(
            raw.get("mjai_log") if isinstance(raw, dict) else None,
            decision_tuple,
            player_id=resolved_player_id,
        )
        decision_tuple = tuple(
            replace(decision, public_context=contexts.get(decision.decision_id))
            for decision in decision_tuple
        )

        return cls(
            model_tag=str(review.get("model_tag", "unknown")),
            rating=float(review["rating"])
            if review.get("rating") is not None
            else None,
            total_reviewed=int(review.get("total_reviewed", len(decisions))),
            total_matches=int(
                review.get(
                    "total_matches", sum(item.matches_mortal for item in decisions)
                )
            ),
            decisions=decision_tuple,
            raw=raw,
        )

    def get_decision(self, decision_id: str) -> Decision:
        for decision in self.decisions:
            if decision.decision_id == decision_id:
                return decision
        raise ReviewerError(f"Decision not found in review: {decision_id}")

    def summary(self, *, weak_limit: int = 10) -> dict[str, Any]:
        weak = sorted(
            (item for item in self.decisions if not item.matches_mortal),
            key=lambda item: (item.q_gap, item.actual_index),
            reverse=True,
        )[: max(0, weak_limit)]
        return {
            "model_tag": self.model_tag,
            "rating": self.rating,
            "total_reviewed": self.total_reviewed,
            "total_matches": self.total_matches,
            "match_rate": (
                self.total_matches / self.total_reviewed
                if self.total_reviewed
                else None
            ),
            "weak_decisions": [
                item.as_dict(candidate_limit=3, include_context=False) for item in weak
            ],
        }


def round_label(kyoku: int) -> str:
    winds = ("E", "S", "W", "N")
    wind_index, number_index = divmod(kyoku, 4)
    wind = winds[wind_index] if wind_index < len(winds) else f"R{wind_index + 1}"
    return f"{wind}{number_index + 1}"


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
