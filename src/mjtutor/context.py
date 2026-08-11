from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import Decision


TILE_TYPES = tuple(
    [f"{number}{suit}" for suit in ("m", "p", "s") for number in range(1, 10)]
    + ["E", "S", "W", "N", "P", "F", "C"]
)
WIND_OFFSETS = {"E": 0, "S": 4, "W": 8, "N": 12}
CALL_TYPES = {"chi", "pon", "daiminkan"}


def reconstruct_decision_contexts(
    mjai_log: Any,
    decisions: tuple[Decision, ...],
    *,
    player_id: int | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(player_id, int) or player_id not in range(4):
        return _unavailable_for_all(decisions, "Review is missing a valid player_id.")
    if not isinstance(mjai_log, list) or not mjai_log:
        return _unavailable_for_all(decisions, "Review does not include mjai_log events.")

    round_events = _partition_round_events(mjai_log)
    grouped: dict[tuple[int, int], list[Decision]] = {}
    for decision in decisions:
        grouped.setdefault((_round_index(decision.round_label), decision.honba), []).append(
            decision
        )

    contexts: dict[str, dict[str, Any]] = {}
    for key, round_decisions in grouped.items():
        events = round_events.get(key)
        if not events:
            for decision in round_decisions:
                contexts[decision.decision_id] = _unavailable(
                    f"Could not find mjai events for {decision.round_label}.{decision.honba}."
                )
            continue

        state = _RoundState.from_start_event(events[0][1])
        cursor = 1
        for decision in sorted(round_decisions, key=lambda item: item.index):
            context, cursor = _find_decision_boundary(
                events,
                cursor,
                state,
                decision,
                player_id=player_id,
            )
            contexts[decision.decision_id] = context
    return contexts


def normalize_tile(tile: str) -> str:
    if tile in {"5mr", "5pr", "5sr"}:
        return tile[:2]
    return tile


@dataclass
class _RoundState:
    bakaze: str
    kyoku: int
    honba: int
    kyotaku: int
    oya: int
    scores: list[int]
    dora_markers: list[str]
    tiles_left: int = 70
    rivers: list[list[dict[str, Any]]] = field(
        default_factory=lambda: [[], [], [], []]
    )
    melds: list[list[dict[str, Any]]] = field(default_factory=lambda: [[], [], [], []])
    riichi_states: list[str] = field(default_factory=lambda: ["none"] * 4)
    public_tile_counts: Counter[str] = field(default_factory=Counter)
    pending_reach_actor: int | None = None

    @classmethod
    def from_start_event(cls, event: dict[str, Any]) -> _RoundState:
        marker = event.get("dora_marker")
        markers = [marker] if isinstance(marker, str) else []
        counts: Counter[str] = Counter(normalize_tile(tile) for tile in markers)
        scores = event.get("scores")
        return cls(
            bakaze=str(event.get("bakaze", "?")),
            kyoku=int(event.get("kyoku", 0)),
            honba=int(event.get("honba", 0)),
            kyotaku=int(event.get("kyotaku", 0)),
            oya=int(event.get("oya", -1)),
            scores=[int(score) for score in scores] if _is_four_item_list(scores) else [],
            dora_markers=markers,
            public_tile_counts=counts,
        )

    def apply(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        actor = event.get("actor")

        if event_type == "tsumo":
            self.tiles_left = max(0, self.tiles_left - 1)
            return

        if event_type == "dahai" and _is_player_id(actor):
            tile = event.get("pai")
            if not isinstance(tile, str):
                return
            self.rivers[actor].append(
                {
                    "pai": tile,
                    "tsumogiri": bool(event.get("tsumogiri", False)),
                    "riichi_declaration": self.pending_reach_actor == actor,
                    "called": False,
                }
            )
            self.public_tile_counts[normalize_tile(tile)] += 1
            return

        if event_type in CALL_TYPES and _is_player_id(actor):
            target = event.get("target")
            tile = event.get("pai")
            if _is_player_id(target) and isinstance(tile, str):
                self._mark_called_discard(target, tile)
            consumed = _tile_list(event.get("consumed"))
            self.public_tile_counts.update(normalize_tile(tile) for tile in consumed)
            self.melds[actor].append(_public_meld(event))
            return

        if event_type == "ankan" and _is_player_id(actor):
            consumed = _tile_list(event.get("consumed"))
            self.public_tile_counts.update(normalize_tile(tile) for tile in consumed)
            self.melds[actor].append(_public_meld(event))
            return

        if event_type == "kakan" and _is_player_id(actor):
            tile = event.get("pai")
            if isinstance(tile, str):
                self.public_tile_counts[normalize_tile(tile)] += 1
            upgraded = _public_meld(event)
            for index in range(len(self.melds[actor]) - 1, -1, -1):
                meld = self.melds[actor][index]
                meld_tile = meld.get("pai")
                if meld.get("type") == "pon" and isinstance(meld_tile, str) and isinstance(
                    tile, str
                ) and normalize_tile(meld_tile) == normalize_tile(tile):
                    if "target" not in upgraded and "target" in meld:
                        upgraded["target"] = meld["target"]
                    self.melds[actor][index] = upgraded
                    break
            else:
                self.melds[actor].append(upgraded)
            return

        if event_type == "dora":
            marker = event.get("dora_marker")
            if isinstance(marker, str):
                self.dora_markers.append(marker)
                self.public_tile_counts[normalize_tile(marker)] += 1
            return

        if event_type == "reach" and _is_player_id(actor):
            self.riichi_states[actor] = "declared"
            self.pending_reach_actor = actor
            return

        if event_type == "reach_accepted" and _is_player_id(actor):
            self.riichi_states[actor] = "accepted"
            self.pending_reach_actor = None
            if len(self.scores) == 4:
                self.scores[actor] -= 1000
            self.kyotaku += 1

    def snapshot(
        self,
        decision: Decision,
        *,
        player_id: int,
        boundary: str,
        decision_event_index: int | None,
        context_after_event_index: int,
        trigger_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        hand = _tile_list(decision.hand_state.get("tehai"))
        visible_counts = self.public_tile_counts.copy()
        visible_counts.update(normalize_tile(tile) for tile in hand)
        unknown_tiles = sorted(tile for tile in visible_counts if tile not in TILE_TYPES)
        overfull_tiles = {
            tile: visible_counts[tile] for tile in TILE_TYPES if visible_counts[tile] > 4
        }
        warnings: list[str] = []
        if not hand:
            warnings.append("Decision state does not include the player's concealed hand.")
        if unknown_tiles:
            warnings.append(f"Unknown tile encodings: {', '.join(unknown_tiles)}")
        if overfull_tiles:
            warnings.append("Visible tile counts exceed four for at least one tile type.")
        state_fuuros = decision.hand_state.get("fuuros")
        if isinstance(state_fuuros, list) and len(state_fuuros) != len(self.melds[player_id]):
            warnings.append("Replayed meld count does not match the decision state.")

        visible = {tile: int(visible_counts[tile]) for tile in TILE_TYPES}
        unseen = {tile: max(0, 4 - visible[tile]) for tile in TILE_TYPES}
        return {
            "available": not warnings,
            "information_scope": "target_player_public_view_before_decision",
            "player_id": player_id,
            "alignment": {
                "boundary": boundary,
                "decision_event_index": decision_event_index,
                "context_after_event_index": context_after_event_index,
                "trigger_event": _public_event(trigger_event) if trigger_event else None,
            },
            "round": {
                "label": decision.round_label,
                "bakaze": self.bakaze,
                "kyoku": self.kyoku,
                "honba": self.honba,
                "kyotaku": self.kyotaku,
                "oya": self.oya,
                "tiles_left": self.tiles_left,
            },
            "scores": list(self.scores),
            "dora_markers": list(self.dora_markers),
            "rivers": deepcopy(self.rivers),
            "melds": deepcopy(self.melds),
            "riichi_states": list(self.riichi_states),
            "visible_tile_counts": visible,
            "unseen_tile_counts": unseen,
            "integrity": {
                "valid": not warnings,
                "opponent_concealed_tiles_included": False,
                "future_events_included": False,
                "red_fives_normalized": True,
                "warnings": warnings,
            },
        }

    def _mark_called_discard(self, target: int, tile: str) -> None:
        normalized = normalize_tile(tile)
        for discard in reversed(self.rivers[target]):
            discard_tile = discard.get("pai")
            if (
                not discard.get("called")
                and isinstance(discard_tile, str)
                and normalize_tile(discard_tile) == normalized
            ):
                discard["called"] = True
                return


def _find_decision_boundary(
    events: list[tuple[int, dict[str, Any]]],
    cursor: int,
    state: _RoundState,
    decision: Decision,
    *,
    player_id: int,
) -> tuple[dict[str, Any], int]:
    actual_type = decision.actual.get("type")
    while cursor < len(events):
        event_index, event = events[cursor]
        if (
            actual_type != "none"
            and _action_matches_event(decision.actual, event)
            and state.tiles_left == decision.tiles_left
        ):
            previous_event_index = events[cursor - 1][0] if cursor else event_index - 1
            context = state.snapshot(
                decision,
                player_id=player_id,
                boundary="before_actual_action",
                decision_event_index=event_index,
                context_after_event_index=previous_event_index,
            )
            state.apply(event)
            return context, cursor + 1

        state.apply(event)
        cursor += 1
        if (
            actual_type == "none"
            and _trigger_matches_decision(event, decision, player_id)
            and state.tiles_left == decision.tiles_left
        ):
            return (
                state.snapshot(
                    decision,
                    player_id=player_id,
                    boundary="after_trigger_event",
                    decision_event_index=None,
                    context_after_event_index=event_index,
                    trigger_event=event,
                ),
                cursor,
            )

    return (
        _unavailable(
            f"Could not align {decision.decision_id} with the round's mjai events."
        ),
        cursor,
    )


def _partition_round_events(
    mjai_log: list[Any],
) -> dict[tuple[int, int], list[tuple[int, dict[str, Any]]]]:
    rounds: dict[tuple[int, int], list[tuple[int, dict[str, Any]]]] = {}
    current: list[tuple[int, dict[str, Any]]] | None = None
    for index, raw_event in enumerate(mjai_log):
        if not isinstance(raw_event, dict):
            continue
        if raw_event.get("type") == "start_kyoku":
            key = _start_event_key(raw_event)
            current = rounds.setdefault(key, []) if key is not None else None
        if current is not None:
            current.append((index, raw_event))
        if raw_event.get("type") == "end_kyoku":
            current = None
    return rounds


def _start_event_key(event: dict[str, Any]) -> tuple[int, int] | None:
    bakaze = event.get("bakaze")
    kyoku = event.get("kyoku")
    honba = event.get("honba", 0)
    if bakaze not in WIND_OFFSETS or not isinstance(kyoku, int) or not isinstance(honba, int):
        return None
    return WIND_OFFSETS[bakaze] + kyoku - 1, honba


def _round_index(label: str) -> int:
    wind = label[:1]
    try:
        number = int(label[1:])
    except ValueError:
        return -1
    return WIND_OFFSETS.get(wind, -4) + number - 1


def _action_matches_event(action: dict[str, Any], event: dict[str, Any]) -> bool:
    if action.get("type") != event.get("type"):
        return False
    for key in ("actor", "target", "pai", "tsumogiri"):
        if key in action and action[key] != event.get(key):
            return False
    if "consumed" in action:
        action_tiles = sorted(normalize_tile(tile) for tile in _tile_list(action["consumed"]))
        event_tiles = sorted(normalize_tile(tile) for tile in _tile_list(event.get("consumed")))
        if action_tiles != event_tiles:
            return False
    return True


def _trigger_matches_decision(
    event: dict[str, Any], decision: Decision, player_id: int
) -> bool:
    event_type = event.get("type")
    expected_type = "kakan" if decision.at_opponent_kakan else "dahai"
    if event_type != expected_type:
        if not (decision.last_actor == player_id and event_type == "tsumo"):
            return False
    if decision.last_actor is not None and event.get("actor") != decision.last_actor:
        return False
    event_tile = event.get("pai")
    return (
        decision.tile is None
        or isinstance(event_tile, str)
        and normalize_tile(event_tile) == normalize_tile(decision.tile)
    )


def _public_event(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        key: deepcopy(event[key])
        for key in ("type", "actor", "target", "pai", "tsumogiri", "consumed")
        if key in event
    }


def _public_meld(event: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(event[key])
        for key in ("type", "actor", "target", "pai", "consumed")
        if key in event
    }


def _tile_list(value: Any) -> list[str]:
    return [tile for tile in value if isinstance(tile, str)] if isinstance(value, list) else []


def _is_player_id(value: Any) -> bool:
    return isinstance(value, int) and value in range(4)


def _is_four_item_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 4


def _unavailable_for_all(
    decisions: tuple[Decision, ...], reason: str
) -> dict[str, dict[str, Any]]:
    return {decision.decision_id: _unavailable(reason) for decision in decisions}


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "information_scope": "target_player_public_view_before_decision",
        "reason": reason,
    }
