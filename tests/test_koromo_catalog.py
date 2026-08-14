from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.error import HTTPError

from mjtutor.koromo_catalog import (
    KoromoCatalogClient,
    KoromoGame,
    KoromoVerificationRequired,
    make_paipu_url,
    parse_koromo_game,
)
from mjtutor.logs import LogMetadata
from mjtutor.models import ReviewDocument
from mjtutor.service import CoachService
from mjtutor.storage import ReviewRepository

MAJSOUL_UID = 12_345_678
KOROMO_ACCOUNT_ID = 8_765_432


def _raw_game(uuid: str = "260811-test") -> dict:
    return {
        "uuid": uuid,
        "modeId": 9,
        "startTime": 1_786_500_000,
        "endTime": 1_786_503_600,
        "players": [
            {
                "accountId": KOROMO_ACCOUNT_ID,
                "nickname": "LocalPlayer",
                "level": 10101,
                "score": 31200,
            },
            {"accountId": 2, "nickname": "B", "level": 10101, "score": 18400},
            {"accountId": 3, "nickname": "C", "level": 10101, "score": 34100},
            {"accountId": 4, "nickname": "D", "level": 10101, "score": 16300},
        ],
    }


def test_parses_four_player_hanchan_and_builds_paipu_url() -> None:
    game = parse_koromo_game(
        _raw_game(), koromo_account_id=KOROMO_ACCOUNT_ID
    )

    assert game.mode_id == 9
    assert game.player_rank == 2
    assert game.player_score == 31200
    assert game.as_dict(koromo_account_id=KOROMO_ACCOUNT_ID)["mode_label"] == "金南"
    assert make_paipu_url(game.uuid, KOROMO_ACCOUNT_ID).startswith(
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
        koromo_account_id=KOROMO_ACCOUNT_ID,
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
        client.fetch_games(
            koromo_account_id=KOROMO_ACCOUNT_ID, start_ms=1, end_ms=2
        )
    except KoromoVerificationRequired as error:
        assert "does not solve or bypass" not in str(error)
        assert "browser challenge" in str(error)
    else:
        raise AssertionError("Koromo challenge should stop automatic sync")


class FakeKoromoClient:
    def __init__(
        self, games: list[KoromoGame] | None = None, error: Exception | None = None
    ):
        self.games = games or []
        self.error = error
        self.calls = 0
        self.last_kwargs = None

    def status(self) -> dict:
        return {"source": "fake", "access_token_configured": False}

    def fetch_games(self, **kwargs) -> list[KoromoGame]:
        self.calls += 1
        self.last_kwargs = kwargs
        if self.error:
            raise self.error
        return self.games


def test_sync_caches_filters_and_prepares_selected_game(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    repository.bind_majsoul_account(
        nickname="LocalPlayer",
        majsoul_uid=MAJSOUL_UID,
        koromo_account_id=KOROMO_ACCOUNT_ID,
    )
    parsed = parse_koromo_game(
        _raw_game(), koromo_account_id=KOROMO_ACCOUNT_ID
    )
    fake = FakeKoromoClient([parsed])
    service = CoachService(repository=repository, koromo_client=fake)

    synced = service.sync_koromo_games(force=True, max_pages=1)
    listed = service.list_koromo_games(
        majsoul_uid=MAJSOUL_UID, rank=2, reviewed=False
    )
    prepared = service.prepare_selected_game_review(parsed.uuid)

    assert synced["accounts"][0]["inserted"] == 1
    assert fake.last_kwargs["koromo_account_id"] == KOROMO_ACCOUNT_ID
    assert fake.last_kwargs["koromo_account_id"] != MAJSOUL_UID
    assert listed["total"] == 1
    assert listed["items"][0]["account_nickname"] == "LocalPlayer"
    assert prepared["status"] == "model_preference_required"
    assert prepared["external_analysis_started"] is False
    assert prepared["mortal_web"]["status"] == "model_preference_required"

    service.set_default_mortal_model("4.1c")
    prepared = service.prepare_selected_game_review(parsed.uuid)
    assert prepared["status"] == "awaiting_human_verification"
    assert prepared["mortal_web"]["requested_settings"]["model_tag"] == "4.1c"

    repeated = service.sync_koromo_games(force=True, max_pages=1)
    assert repeated["accounts"][0]["inserted"] == 0
    assert repeated["accounts"][0]["updated"] == 1


def test_sync_records_verification_required_and_serves_cache(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    repository.bind_majsoul_account(
        nickname="LocalPlayer",
        majsoul_uid=MAJSOUL_UID,
        koromo_account_id=KOROMO_ACCOUNT_ID,
    )
    fake = FakeKoromoClient(error=KoromoVerificationRequired("challenge required"))
    service = CoachService(repository=repository, koromo_client=fake)

    synced = service.sync_koromo_games(force=True)
    listed = service.list_koromo_games()

    assert synced["accounts"][0]["status"] == "verification_required"
    assert synced["accounts"][0]["fetched"] == 0
    assert listed["items"] == []


def test_sync_marks_game_reviewed_when_review_was_imported_first(
    tmp_path: Path,
) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    repository.bind_majsoul_account(
        nickname="LocalPlayer",
        majsoul_uid=MAJSOUL_UID,
        koromo_account_id=KOROMO_ACCOUNT_ID,
    )
    parsed = parse_koromo_game(
        _raw_game(), koromo_account_id=KOROMO_ACCOUNT_ID
    )
    metadata = LogMetadata(
        path=parsed.as_dict(koromo_account_id=KOROMO_ACCOUNT_ID)["paipu_url"],
        sha256="abc123",
        format="test",
        player_names=["LocalPlayer", "B", "C", "D"],
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
    assert prepared["viewer"]["viewer_kind"] == "majsoul"
    assert prepared["viewer"]["viewer_url"] == metadata.path


def test_saved_report_prefers_mortal_visual_viewer(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    parsed = parse_koromo_game(
        _raw_game(), koromo_account_id=KOROMO_ACCOUNT_ID
    )
    metadata = LogMetadata(
        path=parsed.as_dict(koromo_account_id=KOROMO_ACCOUNT_ID)["paipu_url"],
        sha256="mortal-report",
        format="mortal-web-report-json",
        player_names=["LocalPlayer", "B", "C", "D"],
        rule_display="Gold South",
        round_count=8,
        is_hanchan=True,
        is_four_player=True,
        reference="https://mjai.ekyu.moe/report/synthetic.json",
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
        review_id="saved-mortal-review",
        metadata=metadata,
        player_id=0,
        review=review,
        report_json_url=metadata.reference,
    )

    viewer = CoachService(repository=repository).review_viewer("saved-mortal-review")
    listed = CoachService(repository=repository).list_reviews()

    assert viewer["viewer_kind"] == "mortal_web"
    assert viewer["viewer_url"] == (
        "https://mjai.ekyu.moe/killerducky/?data=%2Freport%2Fsynthetic.json"
    )
    assert viewer["paipu_url"] == metadata.path
    assert listed[0]["viewer_available"] is True
    assert listed[0]["viewer_kind"] == "mortal_web"


def test_catalog_merges_local_reviews_and_uses_bound_nickname(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    paipu_urls = (
        make_paipu_url("260811-first", KOROMO_ACCOUNT_ID),
        make_paipu_url("260812-second", KOROMO_ACCOUNT_ID),
    )
    models = ((paipu_urls[0], "4.1b"), (paipu_urls[1], "4.1b"), (paipu_urls[1], "3.0"))
    for index, (paipu_url, model_tag) in enumerate(models):
        metadata = LogMetadata(
            path=paipu_url,
            sha256=f"report-{index}",
            format="mortal-web-report-json",
            player_names=["Aさん", "Bさん", "Cさん", "Dさん"],
            rule_display="Mortal Web four-player hanchan",
            round_count=0,
            is_hanchan=True,
            is_four_player=True,
            reference=f"https://mjai.ekyu.moe/report/{index}.json",
        )
        review = ReviewDocument.from_json(
            {
                "review": {
                    "model_tag": model_tag,
                    "kyokus": [],
                    "total_reviewed": 0,
                    "total_matches": 0,
                }
            },
            player_id=2,
        )
        repository.save_review(
            review_id=f"review-{index}",
            metadata=metadata,
            player_id=2,
            review=review,
            report_json_url=metadata.reference,
        )

    service = CoachService(repository=repository)
    service.bind_majsoul_account(
        nickname="LocalPlayer",
        majsoul_uid=MAJSOUL_UID,
        owned_paipu_url=paipu_urls[0],
    )
    catalog = service.list_koromo_games()
    reviews = service.list_reviews()

    assert catalog["catalog_game_count"] == 2
    assert catalog["catalog_review_count"] == 3
    assert catalog["total"] == 2
    assert sorted(item["review_count"] for item in catalog["items"]) == [1, 2]
    double_review = next(
        item for item in catalog["items"] if item["review_count"] == 2
    )
    assert set(double_review["model_tags"]) == {"3.0", "4.1b"}
    assert double_review["account_nickname"] == "LocalPlayer"
    assert double_review["majsoul_uid"] == MAJSOUL_UID
    assert {item["player_name"] for item in reviews} == {"LocalPlayer"}


def test_web_review_requires_preference_then_uses_default(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "coach.sqlite3")
    service = CoachService(repository=repository)
    paipu_url = "https://game.maj-soul.com/1/?paipu=synthetic-test-hanchan"

    first = service.prepare_web_review(paipu_url)
    assert first["status"] == "model_preference_required"
    assert first["majsoul_log_url"] == paipu_url
    assert "submission_url" not in first

    saved = service.set_default_mortal_model("4.1a")
    assert saved["default_mortal_model"] == "4.1a"
    prepared = service.prepare_web_review(paipu_url)
    assert prepared["requested_settings"]["model_tag"] == "4.1a"

    overridden = service.prepare_web_review(paipu_url, model_tag="3.0")
    assert overridden["requested_settings"]["model_tag"] == "3.0"
    assert service.analysis_preferences()["default_mortal_model"] == "4.1a"

    cleared = service.clear_default_mortal_model()
    assert cleared["default_mortal_model"] is None
