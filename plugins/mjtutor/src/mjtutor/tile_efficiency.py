from __future__ import annotations

from collections.abc import Iterable
from importlib.metadata import version
from typing import Any

from mahjong.shanten import Shanten

from .context import TILE_TYPES, normalize_tile
from .errors import CoachError
from .models import Decision

TILE_INDEX = {tile: index for index, tile in enumerate(TILE_TYPES)}


class TileEfficiencyError(CoachError):
    """Raised when a review decision cannot be analyzed as a discard shape."""


def analyze_tile_efficiency(
    decision: Decision,
    *,
    discards: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Enumerate deterministic shanten and effective draws for discard choices."""
    hand = _concealed_hand(decision)
    legal_discards = _legal_discards(decision)
    selected_discards = _select_discards(legal_discards, discards)
    visible_counts = _visible_counts(decision.public_context)

    analyses = []
    for discard in selected_discards:
        analysis = _analyze_discard(
            hand,
            discard,
            visible_counts=visible_counts,
        )
        candidate_rank, candidate = next(
            (rank, candidate)
            for rank, candidate in enumerate(decision.candidates, start=1)
            if candidate.action.get("type") == "dahai"
            and candidate.action.get("pai") == discard
        )
        analysis["mortal"] = {
            "rank": candidate_rank,
            "q_value": candidate.q_value,
            "probability": candidate.probability,
            "is_expected": decision.expected == candidate.action,
            "is_actual": decision.actual == candidate.action,
        }
        analyses.append(analysis)
    return {
        "calculator": {
            "library": "mahjong",
            "version": version("mahjong"),
        },
        "decision_id": decision.decision_id,
        "round": decision.round_label,
        "turn": decision.turn,
        "hand": {
            "concealed_tiles": hand,
            "meld_count": len(decision.hand_state.get("fuuros", [])),
        },
        "mortal_reported_shanten": decision.shanten,
        "availability": {
            "available": visible_counts is not None,
            "count_type": "unseen_copies" if visible_counts is not None else None,
            "note": (
                "Counts subtract tiles visible to the player; they do not identify "
                "which unseen tiles remain in the live wall."
                if visible_counts is not None
                else "Public visible-tile counts are unavailable or invalid."
            ),
        },
        "interpretation": {
            "scope": "deterministic_hand_shape",
            "waits_are": "shape-completing tiles before yaku and furiten checks",
            "not_included": [
                "tile value",
                "yaku availability",
                "furiten",
                "defense",
                "placement",
                "Mortal policy value",
            ],
        },
        "discards": analyses,
    }


def _analyze_discard(
    hand: list[str],
    discard: str,
    *,
    visible_counts: dict[str, int] | None,
) -> dict[str, Any]:
    remaining = hand.copy()
    _remove_tile(remaining, discard)
    counts = _to_34_counts(remaining)
    shanten = _calculate_shanten(counts)

    effective_draws = []
    for tile in TILE_TYPES:
        tile_index = TILE_INDEX[tile]
        if counts[tile_index] >= 4:
            continue
        drawn = counts.copy()
        drawn[tile_index] += 1
        shanten_after_draw = _calculate_shanten(drawn)
        if shanten_after_draw >= shanten:
            continue
        unseen_copies = _unseen_copies(visible_counts, tile)
        effective_draws.append(
            {
                "tile": tile,
                "unseen_copies": unseen_copies,
                "shanten_after_draw": shanten_after_draw,
                "completes_shape": shanten_after_draw == Shanten.AGARI_STATE,
                "continuations": _continuations(
                    drawn,
                    target_shanten=shanten_after_draw,
                    visible_counts=visible_counts,
                    drawn_tile=tile,
                ),
            }
        )

    unseen_values = [
        item["unseen_copies"]
        for item in effective_draws
        if item["unseen_copies"] is not None
    ]
    return {
        "discard": discard,
        "shanten_after_discard": shanten,
        "effective_tile_types": [item["tile"] for item in effective_draws],
        "effective_type_count": len(effective_draws),
        "total_unseen_copies": (
            sum(unseen_values) if len(unseen_values) == len(effective_draws) else None
        ),
        "effective_draws": effective_draws,
    }


def _continuations(
    drawn: list[int],
    *,
    target_shanten: int,
    visible_counts: dict[str, int] | None,
    drawn_tile: str,
) -> list[dict[str, Any]]:
    if target_shanten == Shanten.AGARI_STATE:
        return []

    hypothetical_visible = (
        {**visible_counts, drawn_tile: visible_counts[drawn_tile] + 1}
        if visible_counts is not None
        else None
    )
    continuations = []
    for discard_index, count in enumerate(drawn):
        if count == 0:
            continue
        after_discard = drawn.copy()
        after_discard[discard_index] -= 1
        resulting_shanten = _calculate_shanten(after_discard)
        if resulting_shanten != target_shanten:
            continue
        waits = (
            _shape_completing_tiles(after_discard)
            if resulting_shanten == Shanten.TENPAI_STATE
            else []
        )
        wait_counts = [_unseen_copies(hypothetical_visible, tile) for tile in waits]
        continuations.append(
            {
                "discard": TILE_TYPES[discard_index],
                "resulting_shanten": resulting_shanten,
                "shape_waits": waits,
                "total_unseen_wait_copies": (
                    sum(count for count in wait_counts if count is not None)
                    if waits and all(count is not None for count in wait_counts)
                    else None
                ),
            }
        )
    return continuations


def _shape_completing_tiles(counts: list[int]) -> list[str]:
    waits = []
    for tile, tile_index in TILE_INDEX.items():
        if counts[tile_index] >= 4:
            continue
        completed = counts.copy()
        completed[tile_index] += 1
        if _calculate_shanten(completed) == Shanten.AGARI_STATE:
            waits.append(tile)
    return waits


def _concealed_hand(decision: Decision) -> list[str]:
    raw_hand = decision.hand_state.get("tehai")
    if not isinstance(raw_hand, list) or not raw_hand:
        raise TileEfficiencyError("Decision does not include a concealed hand")
    hand = []
    for raw_tile in raw_hand:
        if not isinstance(raw_tile, str) or normalize_tile(raw_tile) not in TILE_INDEX:
            raise TileEfficiencyError(
                f"Unsupported tile in decision hand: {raw_tile!r}"
            )
        hand.append(raw_tile)
    return hand


def _legal_discards(decision: Decision) -> list[str]:
    discards = []
    for candidate in decision.candidates:
        action = candidate.action
        tile = action.get("pai")
        if action.get("type") != "dahai" or not isinstance(tile, str):
            continue
        if tile not in discards:
            discards.append(tile)
    if not discards:
        raise TileEfficiencyError("Decision has no Mortal discard candidates")
    return discards


def _select_discards(
    legal_discards: list[str], requested: Iterable[str] | None
) -> list[str]:
    if requested is None:
        return legal_discards
    requested_list = list(dict.fromkeys(requested))
    if not requested_list:
        raise TileEfficiencyError("discards must not be empty when provided")
    unknown = [tile for tile in requested_list if tile not in legal_discards]
    if unknown:
        raise TileEfficiencyError(
            "Requested discards are not Mortal candidates: " + ", ".join(unknown)
        )
    return requested_list


def _visible_counts(context: dict[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(context, dict) or context.get("available") is not True:
        return None
    integrity = context.get("integrity")
    raw_counts = context.get("visible_tile_counts")
    if (
        not isinstance(integrity, dict)
        or integrity.get("valid") is not True
        or not isinstance(raw_counts, dict)
    ):
        return None
    if any(
        not isinstance(raw_counts.get(tile), int) or not 0 <= raw_counts[tile] <= 4
        for tile in TILE_TYPES
    ):
        return None
    return {tile: raw_counts[tile] for tile in TILE_TYPES}


def _unseen_copies(visible_counts: dict[str, int] | None, tile: str) -> int | None:
    if visible_counts is None:
        return None
    return max(0, 4 - visible_counts[tile])


def _remove_tile(hand: list[str], discard: str) -> None:
    if discard in hand:
        hand.remove(discard)
        return
    normalized_discard = normalize_tile(discard)
    for index, tile in enumerate(hand):
        if normalize_tile(tile) == normalized_discard:
            hand.pop(index)
            return
    raise TileEfficiencyError(f"Discard tile is not present in hand: {discard}")


def _to_34_counts(tiles: Iterable[str]) -> list[int]:
    counts = [0] * len(TILE_TYPES)
    for tile in tiles:
        counts[TILE_INDEX[normalize_tile(tile)]] += 1
    if any(count > 4 for count in counts):
        raise TileEfficiencyError(
            "Decision hand contains more than four copies of a tile"
        )
    return counts


def _calculate_shanten(counts: list[int]) -> int:
    try:
        return Shanten.calculate_shanten(counts)
    except ValueError as error:
        raise TileEfficiencyError(f"Cannot calculate shanten: {error}") from error
