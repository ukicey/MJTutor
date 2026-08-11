import pytest

from mjtutor.errors import ReviewerError
from mjtutor.remote import (
    MortalWebProvider,
    normalize_report_json_url,
    validate_majsoul_url,
)

PAIPU_URL = "https://game.maj-soul.com/1/?paipu=synthetic-test-hanchan"


def test_prepares_prefilled_mortal_web_review() -> None:
    result = MortalWebProvider().prepare(PAIPU_URL, language="zh-CN", model_tag="4.1b")

    assert result["status"] == "awaiting_human_verification"
    assert result["automatic_submission"] is False
    assert result["submission_url"].startswith("https://mjai.ekyu.moe/zh-cn.html?url=")


def test_rejects_non_majsoul_url() -> None:
    with pytest.raises(ReviewerError, match="Mahjong Soul"):
        validate_majsoul_url("https://example.com/?paipu=abc")


def test_converts_report_html_url_to_json() -> None:
    assert normalize_report_json_url(
        "https://mjai.ekyu.moe/report/example.html"
    ) == "https://mjai.ekyu.moe/report/example.json"
