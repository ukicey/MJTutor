import json
from pathlib import Path

import pytest

from mjtutor.models import ReviewDocument

FIXTURES = Path(__file__).parent / "fixtures"


def load_review() -> ReviewDocument:
    raw = json.loads((FIXTURES / "sample_review.json").read_text(encoding="utf-8"))
    return ReviewDocument.from_json(raw)


def test_parses_decisions_and_actual_candidate() -> None:
    review = load_review()
    decision = review.get_decision("k0.0:d0")

    assert decision.round_label == "E1"
    assert decision.actual_candidate.action["pai"] == "E"
    assert decision.best_candidate.action["pai"] == "8m"
    assert decision.q_gap == pytest.approx(0.21)


def test_summary_prioritizes_disagreement() -> None:
    summary = load_review().summary(weak_limit=3)

    assert summary["total_reviewed"] == 2
    assert summary["total_matches"] == 1
    assert summary["weak_decisions"][0]["decision_id"] == "k0.0:d0"
    assert summary["weak_decisions"][0]["actual_rank"] == 2
    assert "public_context" not in summary["weak_decisions"][0]


def test_decision_reports_unavailable_context_without_mjai_log() -> None:
    decision = load_review().get_decision("k0.0:d0").as_dict()

    assert decision["public_context"]["available"] is False
    assert "mjai_log" in decision["public_context"]["reason"]
