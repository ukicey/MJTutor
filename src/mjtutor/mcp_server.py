from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from .service import CoachService

mcp = MCPServer("MJTutor")
service = CoachService()


@mcp.tool()
def check_setup() -> dict[str, Any]:
    """Check local mjai-reviewer, Mortal, database, and supported-log readiness."""
    return service.check_setup()


@mcp.tool()
def inspect_majsoul_log(log_path: str) -> dict[str, Any]:
    """Validate a local Mahjong Soul four-player hanchan export without running Mortal."""
    return service.inspect_log(log_path)


@mcp.tool()
def prepare_mortal_web_review(
    majsoul_log_url: str,
    language: str = "zh-CN",
    model_tag: str = "4.1b",
    kyokus: str | None = None,
) -> dict[str, Any]:
    """Prepare a remote Mortal review from a Mahjong Soul paipu URL.

    This returns a prefilled Mortal Web URL. Cloudflare Turnstile requires a
    human verification step; this tool never bypasses or solves it.
    """
    return service.prepare_web_review(
        majsoul_log_url,
        language=language,
        model_tag=model_tag,
        kyokus=kyokus,
    )


@mcp.tool()
def import_mortal_web_report(
    report_url: str,
    majsoul_log_url: str,
) -> dict[str, Any]:
    """Import the public structured JSON produced by a completed Mortal Web review."""
    return service.import_web_report(
        report_url,
        source_log_url=majsoul_log_url,
    )


@mcp.tool()
def review_majsoul_hanchan(
    log_path: str,
    player_id: int,
    kyokus: str | None = None,
) -> dict[str, Any]:
    """Run Mortal through mjai-reviewer and save its structured review locally.

    player_id is the seat at East 1: 0=East, 1=South, 2=West, 3=North.
    kyokus optionally limits analysis, for example "E1,E4,S3.1".
    """
    return service.review_log(
        log_path,
        player_id=player_id,
        kyokus=kyokus,
    )


@mcp.tool()
def import_mjai_review(
    review_path: str,
    source_log_path: str,
    player_id: int,
) -> dict[str, Any]:
    """Import an existing mjai-reviewer JSON report into the local coach database."""
    return service.import_review(
        review_path,
        source_log_path=source_log_path,
        player_id=player_id,
    )


@mcp.tool()
def bind_koromo_account(
    nickname: str,
    koromo_player_id: int,
) -> dict[str, Any]:
    """Bind or refresh one of the local user's accounts after confirmation.

    nickname is display and search history. koromo_player_id is the stable account_id from
    the user's Koromo URL. Never select a same-named result without user confirmation.
    Matching existing paipu reviews receive this account as provenance automatically.
    """
    return service.bind_koromo_account(
        nickname=nickname,
        koromo_player_id=koromo_player_id,
    )


@mcp.tool()
def list_reviews(limit: int = 20) -> list[dict[str, Any]]:
    """List locally stored reviews, newest first."""
    return service.list_reviews(limit=limit)


@mcp.tool()
def get_review_summary(review_id: str, weak_limit: int = 10) -> dict[str, Any]:
    """Return review totals and the largest Mortal disagreements."""
    return service.review_summary(review_id, weak_limit=weak_limit)


@mcp.tool()
def get_decision(
    review_id: str,
    decision_id: str,
    candidate_limit: int = 8,
) -> dict[str, Any]:
    """Return one decision with Mortal evidence and reconstructed public table context."""
    return service.decision(
        review_id,
        decision_id,
        candidate_limit=candidate_limit,
    )


@mcp.tool()
def record_coaching_note(
    review_id: str,
    decision_id: str,
    kind: str,
    category: str,
    note: str,
) -> dict[str, Any]:
    """Save explicit feedback for personalization.

    kind must be mistake, style_preference, question, or understood.
    category should be a compact coaching category such as tile_efficiency or push_fold.
    """
    return service.record_note(
        review_id,
        decision_id,
        kind=kind,
        category=category,
        note=note,
    )


@mcp.tool()
def get_local_observations(
    disagreements_only: bool = True,
    actual_type: str | None = None,
    expected_type: str | None = None,
    limit: int = 12,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a compact, paginated decision ledger for cross-game reasoning.

    These rows are objective Mortal comparisons, not inferred traits. Use review_id and
    decision_id with get_decision when full public context is needed.
    """
    return service.local_observations(
        disagreements_only=disagreements_only,
        actual_type=actual_type,
        expected_type=expected_type,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def propose_profile_item(
    kind: str,
    category: str,
    statement: str,
    confidence: float,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store a confidence-labelled tentative player pattern.

    Use only after repeated reviewed behavior. The item remains tentative until the user
    explicitly confirms or corrects it. Add both supporting and contradicting decisions
    with add_profile_evidence.
    """
    return service.propose_profile_item(
        kind=kind,
        category=category,
        statement=statement,
        scope=scope,
        confidence=confidence,
    )


@mcp.tool()
def record_profile_memory(
    kind: str,
    category: str,
    statement: str,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a confirmed long-term memory from an explicit user statement.

    Do not call this for silent inference or ordinary Mortal disagreement. Suitable kinds
    include mistake, style_preference, goal, strength, teaching_preference, question,
    understood, and pattern.
    """
    return service.record_profile_memory(
        kind=kind,
        category=category,
        statement=statement,
        scope=scope,
    )


@mcp.tool()
def add_profile_evidence(
    item_id: int,
    review_id: str,
    decision_id: str,
    stance: str,
    note: str,
) -> dict[str, Any]:
    """Attach a supporting or contradicting reviewed decision to a profile item."""
    return service.add_profile_evidence(
        item_id=item_id,
        review_id=review_id,
        decision_id=decision_id,
        stance=stance,
        note=note,
    )


@mcp.tool()
def resolve_profile_item(
    item_id: int,
    action: str,
    statement: str | None = None,
    kind: str | None = None,
    category: str | None = None,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply explicit user feedback to a profile item.

    action must be confirm, correct, reject, or forget. correct requires a replacement
    statement. forget deletes the item and its evidence from local storage.
    """
    return service.resolve_profile_item(
        item_id=item_id,
        action=action,
        statement=statement,
        kind=kind,
        category=category,
        scope=scope,
    )


@mcp.tool()
def get_profile_item(item_id: int, evidence_limit: int = 20) -> dict[str, Any]:
    """Return one profile item with supporting and contradicting evidence references."""
    return service.profile_item(item_id, evidence_limit=evidence_limit)


@mcp.tool()
def get_local_profile(
    include_rejected: bool = False,
) -> dict[str, Any]:
    """Return the local user's accounts and compact evidence-backed coaching memory.

    Rejected items are hidden by default. Full decisions are always fetched separately.
    """
    return service.local_profile(
        include_rejected=include_rejected,
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
