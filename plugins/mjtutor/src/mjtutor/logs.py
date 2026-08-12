from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import InvalidLogError


@dataclass(frozen=True)
class LogMetadata:
    path: str
    sha256: str
    format: str
    rule_display: str
    player_names: list[str]
    round_count: int
    is_four_player: bool
    is_hanchan: bool
    reference: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_tenhou_v6_log(
    path: str | Path, *, require_hanchan: bool = True
) -> LogMetadata:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise InvalidLogError(f"Log file does not exist: {source}")

    raw_bytes = source.read_bytes()
    try:
        document = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidLogError(f"Log is not valid UTF-8 JSON: {source}") from exc

    if not isinstance(document, dict):
        raise InvalidLogError("Expected a tenhou.net/6-compatible JSON object")

    names = document.get("name")
    rounds = document.get("log")
    rule = document.get("rule", {})
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise InvalidLogError("Log is missing the player name list")
    if not isinstance(rounds, list) or not rounds:
        raise InvalidLogError("Log does not contain any rounds")
    if not isinstance(rule, dict):
        rule = {}

    rule_display = str(rule.get("disp", ""))
    is_four_player = len(names) == 4
    is_hanchan = _is_hanchan(rule_display, document)

    if not is_four_player:
        raise InvalidLogError("Only four-player Mahjong Soul logs are supported")
    if require_hanchan and not is_hanchan:
        raise InvalidLogError(
            "Only hanchan (South-round) logs are supported; the rule metadata "
            "does not identify this log as hanchan"
        )

    reference = document.get("ref")
    return LogMetadata(
        path=str(source),
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
        format="tenhou.net/6-compatible-json",
        rule_display=rule_display,
        player_names=names,
        round_count=len(rounds),
        is_four_player=is_four_player,
        is_hanchan=is_hanchan,
        reference=str(reference) if reference is not None else None,
    )


def _is_hanchan(rule_display: str, document: dict[str, Any]) -> bool:
    normalized = rule_display.casefold()
    if "\u5357" in rule_display or "hanchan" in normalized or "south" in normalized:
        return True

    game_length = document.get("game_length")
    return isinstance(game_length, str) and game_length.casefold() in {
        "hanchan",
        "south",
        "south_round",
    }
