from typing import Any

from mjtutor.models import ReviewDocument


def test_discard_context_excludes_opponent_hands_and_future_events() -> None:
    hand = [
        "1m",
        "2m",
        "3m",
        "5mr",
        "6m",
        "7m",
        "1p",
        "2p",
        "3p",
        "4s",
        "5s",
        "6s",
        "E",
        "9s",
    ]
    entry = _entry(
        state={"tehai": hand, "fuuros": []},
        actual={"type": "dahai", "actor": 0, "pai": "9s", "tsumogiri": True},
        last_actor=0,
        tile="9s",
    )
    events = [
        _start_event(
            dora_marker="7p",
            tehais=[hand[:-1], ["C"] * 13, ["N"] * 13, ["P"] * 13],
        ),
        {"type": "tsumo", "actor": 0, "pai": "9s"},
        {"type": "dahai", "actor": 0, "pai": "9s", "tsumogiri": True},
        {"type": "tsumo", "actor": 1, "pai": "N"},
        {"type": "dahai", "actor": 1, "pai": "N", "tsumogiri": True},
    ]

    context = _review([entry], events).get_decision("k0.0:d0").public_context

    assert context is not None and context["available"] is True
    assert context["alignment"]["boundary"] == "before_actual_action"
    assert context["visible_tile_counts"]["5m"] == 1
    assert context["visible_tile_counts"]["C"] == 0
    assert context["visible_tile_counts"]["N"] == 0
    assert sum(context["visible_tile_counts"].values()) == 15
    assert context["rivers"] == [[], [], [], []]
    assert context["integrity"]["opponent_concealed_tiles_included"] is False
    assert context["integrity"]["future_events_included"] is False


def test_skipped_call_context_is_after_trigger_discard() -> None:
    hand = [
        "1m",
        "3m",
        "4m",
        "5m",
        "6m",
        "2p",
        "3p",
        "4p",
        "5s",
        "6s",
        "7s",
        "E",
        "E",
    ]
    entry = _entry(
        state={"tehai": hand, "fuuros": []},
        actual={"type": "none"},
        expected={"type": "none"},
        candidates=[
            {"type": "none"},
            {
                "type": "chi",
                "actor": 0,
                "target": 3,
                "pai": "2m",
                "consumed": ["1m", "3m"],
            },
        ],
        last_actor=3,
        tile="2m",
    )
    events = [
        _start_event(),
        {"type": "tsumo", "actor": 3, "pai": "2m"},
        {"type": "dahai", "actor": 3, "pai": "2m", "tsumogiri": False},
        {"type": "tsumo", "actor": 0, "pai": "C"},
    ]

    context = _review([entry], events).get_decision("k0.0:d0").public_context

    assert context is not None and context["available"] is True
    assert context["alignment"]["boundary"] == "after_trigger_event"
    assert context["alignment"]["trigger_event"]["pai"] == "2m"
    assert context["rivers"][3] == [
        {
            "pai": "2m",
            "tsumogiri": False,
            "riichi_declaration": False,
            "called": False,
        }
    ]
    assert context["visible_tile_counts"]["2m"] == 1
    assert context["visible_tile_counts"]["C"] == 0


def test_called_discard_is_counted_once_and_meld_is_replayed() -> None:
    before_call = [
        "1m",
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "1p",
        "2p",
        "3p",
        "7s",
        "8s",
        "E",
        "E",
    ]
    after_call = [
        "1m",
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "1p",
        "2p",
        "3p",
        "7s",
        "8s",
    ]
    pon = {
        "type": "pon",
        "actor": 0,
        "target": 1,
        "pai": "E",
        "consumed": ["E", "E"],
    }
    entries = [
        _entry(
            state={"tehai": before_call, "fuuros": []},
            actual=pon,
            last_actor=1,
            tile="E",
        ),
        _entry(
            state={"tehai": after_call, "fuuros": [pon]},
            actual={"type": "dahai", "actor": 0, "pai": "8s", "tsumogiri": False},
            last_actor=0,
            tile="8s",
        ),
    ]
    events = [
        _start_event(),
        {"type": "tsumo", "actor": 1, "pai": "E"},
        {"type": "dahai", "actor": 1, "pai": "E", "tsumogiri": False},
        pon,
        {"type": "dahai", "actor": 0, "pai": "8s", "tsumogiri": False},
    ]

    review = _review(entries, events)
    call_context = review.get_decision("k0.0:d0").public_context
    discard_context = review.get_decision("k0.0:d1").public_context

    assert call_context is not None and call_context["melds"][0] == []
    assert call_context["visible_tile_counts"]["E"] == 3
    assert discard_context is not None and discard_context["available"] is True
    assert discard_context["rivers"][1][0]["called"] is True
    assert discard_context["melds"][0][0]["type"] == "pon"
    assert discard_context["visible_tile_counts"]["E"] == 3


def test_reach_accepted_updates_score_kyotaku_and_river_marker() -> None:
    reach_hand = [
        "1m",
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "1p",
        "2p",
        "3p",
        "4s",
        "5s",
        "6s",
        "9m",
        "9m",
    ]
    waiting_hand = reach_hand[:-1]
    entries = [
        _entry(
            state={"tehai": reach_hand, "fuuros": []},
            actual={"type": "reach", "actor": 0},
            last_actor=0,
            tile="9m",
        ),
        _entry(
            state={"tehai": waiting_hand, "fuuros": []},
            actual={"type": "hora", "actor": 0, "target": 1},
            last_actor=1,
            tile="7p",
            tiles_left=68,
        ),
    ]
    events = [
        _start_event(),
        {"type": "tsumo", "actor": 0, "pai": "9m"},
        {"type": "reach", "actor": 0},
        {"type": "dahai", "actor": 0, "pai": "9m", "tsumogiri": True},
        {"type": "reach_accepted", "actor": 0},
        {"type": "tsumo", "actor": 1, "pai": "7p"},
        {"type": "dahai", "actor": 1, "pai": "7p", "tsumogiri": True},
        {"type": "hora", "actor": 0, "target": 1},
    ]

    review = _review(entries, events)
    reach_context = review.get_decision("k0.0:d0").public_context
    hora_context = review.get_decision("k0.0:d1").public_context

    assert reach_context is not None and reach_context["riichi_states"][0] == "none"
    assert reach_context["scores"][0] == 25000
    assert hora_context is not None and hora_context["available"] is True
    assert hora_context["riichi_states"][0] == "accepted"
    assert hora_context["scores"][0] == 24000
    assert hora_context["round"]["kyotaku"] == 1
    assert hora_context["rivers"][0][0]["riichi_declaration"] is True


def _review(
    entries: list[dict[str, Any]], events: list[dict[str, Any]]
) -> ReviewDocument:
    return ReviewDocument.from_json(
        {
            "player_id": 0,
            "mjai_log": [{"type": "start_game"}, *events],
            "review": {
                "model_tag": "test",
                "total_reviewed": len(entries),
                "total_matches": len(entries),
                "kyokus": [
                    {
                        "kyoku": 0,
                        "honba": 0,
                        "entries": entries,
                    }
                ],
            },
        }
    )


def _entry(
    *,
    state: dict[str, Any],
    actual: dict[str, Any],
    last_actor: int,
    tile: str,
    expected: dict[str, Any] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    tiles_left: int = 69,
) -> dict[str, Any]:
    actions = candidates or [actual]
    return {
        "junme": 1,
        "tiles_left": tiles_left,
        "last_actor": last_actor,
        "tile": tile,
        "state": state,
        "expected": expected or actual,
        "actual": actual,
        "is_equal": True,
        "details": [
            {"action": action, "q_value": 0.5 - index * 0.1, "prob": 1.0}
            for index, action in enumerate(actions)
        ],
        "shanten": 1,
        "at_furiten": False,
        "actual_index": 0,
    }


def _start_event(
    *,
    dora_marker: str = "1p",
    tehais: list[list[str]] | None = None,
) -> dict[str, Any]:
    return {
        "type": "start_kyoku",
        "bakaze": "E",
        "kyoku": 1,
        "honba": 0,
        "kyotaku": 0,
        "oya": 0,
        "scores": [25000, 25000, 25000, 25000],
        "dora_marker": dora_marker,
        "tehais": tehais or [[], [], [], []],
    }
