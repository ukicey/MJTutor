from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.error import HTTPError

from mjtutor.logs import LogMetadata
from mjtutor.models import ReviewDocument
from mjtutor.koromo_catalog import (
    KoromoCatalogClient,
    KoromoGame,
    KoromoVerificationRequired,
    make_paipu_url,
    parse_koromo_game,
)
from mjtutor.service import CoachService
from mjtutor.storage import ReviewRepository


def _raw_game(uuid: str = "260811-test") -> dict:
    return {
        "uuid": uuid,
        "modeId": 9,
        "startTime": 1_786_500_000,
        "endTime": 1_786_503_600,
        "players": [
            {"accountId": 20155424, "nickname": "Orangeese", "level": 10101, "score": 31200},
            {"accountId": 2, "nickname": "B", "level": 10101, "score": 18400},
            {"accountId": 3, "nickname": "C", "level": 10101, "score": 34100},
            {"accountId": 4, "nickname": "D", "level": 10101, "score": 16300},
        ],
    }


def test_parses_four_player_hanchan_and_builds_paipu_url() -> None:
    game = parse_koromo_game(_raw_game(), account_id=20155424)

    assert game.mode_id == 9
    assert game.player_rank == 2
    assert game.player_score == 31200
    assert game.as_dict(account_id=20155424)["mode_label"] == "金南"
    assert make_paipu_url(game.uuid, 20155424).startswith(
        "https://game.maj-soul.com/1/?paipu=260811-test_a"
    )


def test_client_uses_hanchan_modes_and_optional_access_token() -> None:
    captured = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def opener(request, *, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return Response(json.dumps([_raw_game()]).encode())

    client = KoromoCatalogClient(
        mirrors=("https://data.example",),
        access_token="site-key",
        opener=opener,
    )
    games = client.fetch_games(
        account_id=20155424,
        start_ms=1_700_000_000_000,
        end_ms=1_800_000_000_000,
    )

    assert len(games) == 1
    assert "mode=9%2C12%2C16" in captured["url"]
    assert captured["authorization"] == "Bearer site-key"


def test_client_does_not_bypass_koromo_challenge() -> None:
    def opener(request, *, timeout):
        raise HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b"[x-cap-token-required] CAPTCHA required"),
        )

    client = KoromoCatalogClient(mirrors=("https://data.example",), opener=opener)

    try:
        client.fetch_games(account_id=20155424, start_ms=1, end_ms=2)
    except KoromoVerificationRequired as error:
        assert "does not solve or bypass" not in str(error)
        assert "browser challenge" in str(error)
    else:
        raise AssertionError("Koromo challenge should stop automatic sync")


class FakeKoromoClient:
    def __init__(self, games: list[KoromoGame] | None = None, error: Exception | None = None):
        self.games = games or []
        self.error = error
        self.calls = 0

    def status(self) -> dict:
        return {"source": "fake", "access_token_configured": False}

    def fetch_games(self, **_kwargs) -> list[KoromoGame]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.games


def test_sync_caches_filters_and_prepares_selected_game(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    repository.bind_koromo_account(nickname="Orangeese", koromo_player_id=20155424)
    parsed = parse_koromo_game(_raw_game(), account_id=20155424)
    fake = FakeKoromoClient([parsed])
    service = CoachService(repository=repository, koromo_client=fake)

    synced = service.sync_koromo_games(force=True, max_pages=1)
    listed = service.list_koromo_games(account_id=20155424, rank=2, reviewed=False)
    prepared = service.prepare_selected_game_review(parsed.uuid)

    assert synced["accounts"][0]["inserted"] == 1
    assert listed["total"] == 1
    assert listed["items"][0]["account_nickname"] == "Orangeese"
    assert prepared["external_analysis_started"] is False
    assert prepared["mortal_web"]["status"] == "awaiting_human_verification"

    repeated = service.sync_koromo_games(force=True, max_pages=1)
    assert repeated["accounts"][0]["inserted"] == 0
    assert repeated["accounts"][0]["updated"] == 1


def test_sync_records_verification_required_and_serves_cache(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    repository.bind_koromo_account(nickname="Orangeese", koromo_player_id=20155424)
    fake = FakeKoromoClient(error=KoromoVerificationRequired("challenge required"))
    service = CoachService(repository=repository, koromo_client=fake)

    synced = service.sync_koromo_games(force=True)
    listed = service.list_koromo_games()

    assert synced["accounts"][0]["status"] == "verification_required"
    assert synced["accounts"][0]["fetched"] == 0
    assert listed["items"] == []


def test_sync_marks_game_reviewed_when_review_was_imported_first(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    repository.bind_koromo_account(nickname="Orangeese", koromo_player_id=20155424)
    parsed = parse_koromo_game(_raw_game(), account_id=20155424)
    metadata = LogMetadata(
        path=parsed.as_dict(account_id=20155424)["paipu_url"],
        sha256="abc123",
        format="test",
        player_names=["Orangeese", "B", "C", "D"],
        rule_display="Gold South",
        round_count=8,
        is_hanchan=True,
        is_four_player=True,
        reference=None,
    )
    review = ReviewDocument.from_json(
        {
            "review": {
                "model_tag": "4.1b",
                "kyokus": [],
                "total_reviewed": 0,
                "total_matches": 0,
            }
        },
        player_id=0,
    )
    repository.save_review(
        review_id="review-before-sync",
        metadata=metadata,
        player_id=0,
        review=review,
    )
    service = CoachService(
        repository=repository,
        koromo_client=FakeKoromoClient([parsed]),
    )

    service.sync_koromo_games(force=True, max_pages=1)
    game = service.list_koromo_games()["items"][0]

    assert game["reviewed"] is True
    assert game["review_id"] == "review-before-sync"
    prepared = service.prepare_selected_game_review(parsed.uuid)
    assert prepared["status"] == "already_reviewed"
    assert prepared["mortal_web"] is None
