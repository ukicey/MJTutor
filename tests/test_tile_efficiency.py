from __future__ import annotations

from dataclasses import replace

import pytest

from mjtutor.context import TILE_TYPES
from mjtutor.models import Candidate, Decision
from mjtutor.tile_efficiency import TileEfficiencyError, analyze_tile_efficiency


def test_complex_open_hand_enumerates_triplet_pair_routes() -> None:
    result = analyze_tile_efficiency(
        _complex_open_hand_decision(),
        discards=["2s", "6s"],
    )

    by_discard = {item["discard"]: item for item in result["discards"]}
    discard_2s = by_discard["2s"]
    discard_6s = by_discard["6s"]

    assert result["calculator"]["library"] == "mahjong"
    assert result["calculator"]["version"].startswith("2.")
    assert discard_2s["shanten_after_discard"] == 1
    assert discard_2s["effective_tile_types"] == [
        "3m",
        "4m",
        "5m",
        "6m",
        "4s",
        "5s",
        "6s",
        "7s",
    ]
    assert discard_2s["total_unseen_copies"] == 26
    assert discard_2s["mortal"]["rank"] == 2

    draw_3m = _draw(discard_2s, "3m")
    after_3s = _continuation(draw_3m, "3s")
    assert after_3s["resulting_shanten"] == 0
    assert after_3s["shape_waits"] == ["4s", "7s"]

    draw_4s = _draw(discard_2s, "4s")
    assert _continuation(draw_4s, "3s")["shape_waits"] == ["3m", "6m"]

    assert discard_6s["effective_tile_types"] == [
        "3m",
        "6m",
        "1s",
        "2s",
        "4s",
        "5s",
    ]
    assert discard_6s["total_unseen_copies"] == 20
    assert discard_6s["mortal"]["rank"] == 1
    assert _continuation(_draw(discard_6s, "1s"), "5s")["shape_waits"] == [
        "3m",
        "6m",
    ]


def test_missing_public_context_keeps_shape_but_omits_availability() -> None:
    decision = replace(_complex_open_hand_decision(), public_context=None)

    result = analyze_tile_efficiency(decision, discards=["2s"])

    discard = result["discards"][0]
    assert result["availability"]["available"] is False
    assert discard["effective_type_count"] == 8
    assert discard["total_unseen_copies"] is None
    assert all(draw["unseen_copies"] is None for draw in discard["effective_draws"])


def test_rejects_non_candidate_discard() -> None:
    with pytest.raises(TileEfficiencyError, match="not Mortal candidates"):
        analyze_tile_efficiency(_complex_open_hand_decision(), discards=["9m"])


def _complex_open_hand_decision() -> Decision:
    hand = ["4m", "6p", "7p", "8p", "2s", "3s", "3s", "3s", "5s", "6s", "5m"]
    discard_6s = {"type": "dahai", "actor": 3, "pai": "6s", "tsumogiri": False}
    discard_2s = {"type": "dahai", "actor": 3, "pai": "2s", "tsumogiri": False}
    actual = {"type": "dahai", "actor": 3, "pai": "5m", "tsumogiri": True}
    visible_counts = {tile: 0 for tile in TILE_TYPES}
    visible_counts.update(
        {
            "1m": 3,
            "2m": 3,
            "3m": 0,
            "4m": 1,
            "5m": 2,
            "6m": 1,
            "8m": 1,
            "9m": 1,
            "4p": 2,
            "6p": 1,
            "7p": 1,
            "8p": 1,
            "9p": 2,
            "1s": 1,
            "2s": 1,
            "3s": 3,
            "4s": 0,
            "5s": 1,
            "6s": 1,
            "7s": 0,
            "8s": 1,
            "E": 1,
            "S": 1,
            "W": 3,
            "N": 4,
            "P": 1,
            "F": 2,
            "C": 1,
        }
    )
    candidates = (
        Candidate(discard_6s, q_value=0.08788198, probability=0.9391101),
        Candidate(discard_2s, q_value=-0.32083756, probability=0.015764138),
        Candidate(actual, q_value=-1.0158235, probability=0.000015114178),
    )
    return Decision(
        decision_id="k0.0:d7",
        round_label="E1",
        honba=0,
        index=7,
        turn=7,
        tiles_left=44,
        hand_state={
            "tehai": hand,
            "fuuros": [
                {
                    "type": "pon",
                    "target": 1,
                    "pai": "N",
                    "consumed": ["N", "N"],
                }
            ],
        },
        expected=discard_6s,
        actual=actual,
        matches_mortal=False,
        shanten=1,
        furiten=False,
        actual_index=2,
        candidates=candidates,
        last_actor=3,
        tile="5m",
        at_self_chi_pon=False,
        at_self_riichi=False,
        at_opponent_kakan=False,
        public_context={
            "available": True,
            "visible_tile_counts": visible_counts,
            "integrity": {"valid": True},
        },
    )


def _draw(discard: dict[str, object], tile: str) -> dict[str, object]:
    return next(item for item in discard["effective_draws"] if item["tile"] == tile)


def _continuation(draw: dict[str, object], discard: str) -> dict[str, object]:
    return next(item for item in draw["continuations"] if item["discard"] == discard)
