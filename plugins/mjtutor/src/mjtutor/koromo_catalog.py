from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .errors import CoachError
from .koromo import encode_paipu_account_id

KOROMO_WEB_URL = "https://amae-koromo.sapk.ch"
KOROMO_DATA_MIRRORS = (
    "https://5-data.amae-koromo.com",
    "https://1.data.amae-koromo.com",
    "https://2.data.amae-koromo.com",
    "https://4.data.amae-koromo.com",
)
HANCHAN_MODES = (9, 12, 16)
MODE_LABELS = {9: "金南", 12: "玉南", 16: "王座南"}
DEFAULT_INITIAL_LOOKBACK_DAYS = 365
DEFAULT_SYNC_INTERVAL_MINUTES = 30


class KoromoAccessError(CoachError):
    """Raised when the public Koromo catalog cannot be reached."""


class KoromoVerificationRequired(KoromoAccessError):
    """Raised when Koromo requires its browser challenge or an access key."""


@dataclass(frozen=True)
class KoromoGame:
    uuid: str
    mode_id: int
    start_time: int
    end_time: int
    players: tuple[dict[str, Any], ...]
    player_rank: int
    player_score: int

    def as_dict(self, *, account_id: int) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "account_id": account_id,
            "mode_id": self.mode_id,
            "mode_label": MODE_LABELS.get(self.mode_id, f"Mode {self.mode_id}"),
            "start_time": self.start_time,
            "end_time": self.end_time,
            "players": [dict(player) for player in self.players],
            "player_rank": self.player_rank,
            "player_score": self.player_score,
            "paipu_url": make_paipu_url(self.uuid, account_id),
        }


class KoromoCatalogClient:
    def __init__(
        self,
        *,
        mirrors: tuple[str, ...] = KOROMO_DATA_MIRRORS,
        timeout: float = 10.0,
        access_token: str | None = None,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.mirrors = mirrors
        self.timeout = timeout
        self.access_token = access_token or os.environ.get("MJTUTOR_KOROMO_TOKEN")
        self._opener = opener

    def status(self) -> dict[str, Any]:
        return {
            "source": "Koromo (Mahjong Soul ranked-game catalog)",
            "web_url": KOROMO_WEB_URL,
            "coverage": "four-player Gold, Jade, and Throne ranked rooms",
            "hanchan_modes": list(HANCHAN_MODES),
            "access_token_configured": bool(self.access_token),
            "access_note": (
                "Koromo may require its browser challenge or an access key. "
                "MJTutor does not solve or bypass that challenge."
            ),
        }

    def fetch_games(
        self,
        *,
        account_id: int,
        start_ms: int,
        end_ms: int,
        limit: int = 100,
    ) -> list[KoromoGame]:
        if account_id <= 0:
            raise KoromoAccessError("account_id must be positive")
        if start_ms < 0 or end_ms <= start_ms:
            raise KoromoAccessError("Koromo sync time range is invalid")
        limit = max(1, min(int(limit), 100))
        query = urlencode(
            {
                "limit": limit,
                "mode": ",".join(str(mode) for mode in HANCHAN_MODES),
                "descending": "true",
            }
        )
        path = (
            f"/api/v2/pl4/player_records/{account_id}/{end_ms}/{start_ms}?{query}"
        )
        payload = self._get_json(path)
        if not isinstance(payload, list):
            raise KoromoAccessError("Koromo returned an unexpected game-list response")
        return [parse_koromo_game(item, account_id=account_id) for item in payload]

    def _get_json(self, path: str) -> Any:
        last_error: Exception | None = None
        for mirror in self.mirrors:
            request = Request(
                f"{mirror.rstrip('/')}{path}",
                headers=self._headers(),
                method="GET",
            )
            try:
                with self._opener(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                if error.code == 429 and "x-cap-token-required" in body:
                    raise KoromoVerificationRequired(
                        "Koromo requires its browser challenge or an authorized access key. "
                        "Open Koromo normally in a browser, or configure an access key supplied "
                        "by the site owner as MJTUTOR_KOROMO_TOKEN."
                    ) from error
                last_error = KoromoAccessError(
                    f"Koromo request failed with HTTP {error.code}"
                )
                if error.code < 500:
                    break
            except (TimeoutError, socket.timeout, URLError, json.JSONDecodeError) as error:
                last_error = error
        raise KoromoAccessError(
            "Koromo could not be reached from any configured data mirror"
        ) from last_error

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "MJTutor/0.3 (+https://github.com/ukicey/MJTutor)",
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers


def parse_koromo_game(raw: Any, *, account_id: int) -> KoromoGame:
    if not isinstance(raw, dict):
        raise KoromoAccessError("Koromo game record must be an object")
    players_raw = raw.get("players")
    if not isinstance(players_raw, list) or len(players_raw) != 4:
        raise KoromoAccessError("Koromo game record is not a four-player game")
    players = tuple(_parse_player(player) for player in players_raw)
    owner_index = next(
        (
            index
            for index, player in enumerate(players)
            if int(player["account_id"]) == account_id
        ),
        None,
    )
    if owner_index is None:
        raise KoromoAccessError("Koromo game record does not contain the requested account")
    mode_id = int(raw.get("modeId", raw.get("mode_id", 0)))
    if mode_id not in HANCHAN_MODES:
        raise KoromoAccessError(f"Unsupported Koromo game mode: {mode_id}")
    uuid = str(raw.get("uuid", "")).strip()
    if not uuid:
        raise KoromoAccessError("Koromo game record is missing its paipu UUID")
    rank_order = sorted(
        range(4),
        key=lambda index: (int(players[index]["score"]), -index),
        reverse=True,
    )
    return KoromoGame(
        uuid=uuid,
        mode_id=mode_id,
        start_time=int(raw.get("startTime", raw.get("start_time", 0))),
        end_time=int(raw.get("endTime", raw.get("end_time", 0))),
        players=players,
        player_rank=rank_order.index(owner_index) + 1,
        player_score=int(players[owner_index]["score"]),
    )


def make_paipu_url(uuid: str, account_id: int) -> str:
    encoded = encode_paipu_account_id(account_id)
    return f"https://game.maj-soul.com/1/?paipu={uuid}_a{encoded}"


def default_initial_start_ms(now: datetime | None = None) -> int:
    current = now or datetime.now(UTC)
    return int((current - timedelta(days=DEFAULT_INITIAL_LOOKBACK_DAYS)).timestamp() * 1000)


def _parse_player(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise KoromoAccessError("Koromo player record must be an object")
    return {
        "account_id": int(raw.get("accountId", raw.get("account_id", 0))),
        "nickname": str(raw.get("nickname", "")),
        "level": int(raw.get("level", 0)),
        "score": int(raw.get("score", 0)),
        "grading_score": (
            int(raw["gradingScore"])
            if raw.get("gradingScore") is not None
            else None
        ),
    }
