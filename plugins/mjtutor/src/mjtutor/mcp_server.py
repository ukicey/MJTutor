from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp import types
from mcp.server import MCPServer
from mcp.server.apps import Apps

from . import __version__
from .service import CoachService

service = CoachService()
apps = Apps()
CATALOG_URI = "ui://mjtutor/game-catalog.html"


@apps.tool(
    resource_uri=CATALOG_URI,
    visibility=["model", "app"],
    title="Open MJTutor game catalog",
    description=(
        "Open the interactive local game catalog. Use this when the user wants to "
        "browse imported reviews, sync Koromo, or choose a game without listing "
        "every record in chat."
    ),
)
def open_game_catalog(
    auto_sync: bool = True,
    limit: int = 20,
) -> types.CallToolResult:
    result = service.list_koromo_games(limit=limit, auto_sync=auto_sync)
    result["sync_status"] = service.koromo_sync_status()
    return _catalog_tool_result(result)


apps.add_html_resource(
    CATALOG_URI,
    (Path(__file__).resolve().parents[2] / "assets" / "game-catalog.html").read_text(
        encoding="utf-8"
    ),
    name="MJTutor game catalog",
    title="MJTutor 牌局目录",
    description="Browse imported reviews and cached Koromo games.",
    prefers_border=False,
)

mcp = MCPServer("MJTutor", version=__version__, extensions=[apps])


@mcp.tool(meta={"ui": {"visibility": ["app"]}})
def query_game_catalog(
    majsoul_uid: int | None = None,
    rank: int | None = None,
    reviewed: bool | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> types.CallToolResult:
    """Return a private catalog page to the MJTutor App.

    Game rows are delivered in tool-result metadata so browsing does not add the page
    contents to the model transcript. Conversation clients should use list_koromo_games.
    """
    result = service.list_koromo_games(
        majsoul_uid=majsoul_uid,
        rank=rank,
        reviewed=reviewed,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
    result["sync_status"] = service.koromo_sync_status()
    return _catalog_tool_result(result)


@mcp.tool()
def check_setup() -> dict[str, Any]:
    """Check Mortal Web, ranked-game catalog, local data, and review preferences."""
    return service.check_setup()


@mcp.tool()
def prepare_mortal_web_review(
    majsoul_log_url: str,
    language: str = "zh-CN",
    model_tag: str | None = None,
    kyokus: str | None = None,
) -> dict[str, Any]:
    """Prepare a remote Mortal review from a Mahjong Soul paipu URL.

    This returns a prefilled Mortal Web URL. It never bypasses or solves
    Cloudflare Turnstile; the browser may continue when verification succeeds.
    """
    return service.prepare_web_review(
        majsoul_log_url,
        language=language,
        model_tag=model_tag,
        kyokus=kyokus,
    )


@mcp.tool()
def get_analysis_preferences() -> dict[str, Any]:
    """Return the default Mortal model and the currently available model catalog."""
    return service.analysis_preferences()


@mcp.tool()
def set_default_mortal_model(model_tag: str) -> dict[str, Any]:
    """Save the local user's default Mortal model for future web reviews."""
    return service.set_default_mortal_model(model_tag)


@mcp.tool()
def clear_default_mortal_model() -> dict[str, Any]:
    """Clear the saved Mortal model so the next review asks for a choice."""
    return service.clear_default_mortal_model()


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
def bind_majsoul_account(
    nickname: str,
    majsoul_uid: int,
    owned_paipu_url: str | None = None,
    koromo_account_id: int | None = None,
) -> dict[str, Any]:
    """Bind or refresh a confirmed Mahjong Soul account for the local user.

    majsoul_uid is the numeric UID shown in the user's Mahjong Soul profile.
    Pass a paipu URL confirmed to belong to that user so MJTutor can derive the
    separate Koromo catalog ID. koromo_account_id is an advanced fallback when a
    confirmed owned paipu is unavailable. Nicknames are display history only.
    """
    return service.bind_majsoul_account(
        nickname=nickname,
        majsoul_uid=majsoul_uid,
        owned_paipu_url=owned_paipu_url,
        koromo_account_id=koromo_account_id,
    )


@mcp.tool(meta={"ui": {"visibility": ["model", "app"]}})
def sync_koromo_games(
    majsoul_uid: int | None = None,
    force: bool = False,
    lookback_days: int = 365,
    max_pages: int = 10,
) -> dict[str, Any]:
    """Incrementally sync bound-account hanchan metadata from Koromo into SQLite.

    This does not analyze games with Mortal. Koromo may require its browser challenge or
    an access key; MJTutor records that state and continues serving cached games.
    """
    return service.sync_koromo_games(
        majsoul_uid=majsoul_uid,
        force=force,
        lookback_days=lookback_days,
        max_pages=max_pages,
    )


@mcp.tool(meta={"ui": {"visibility": ["model", "app"]}})
def list_koromo_games(
    majsoul_uid: int | None = None,
    rank: int | None = None,
    reviewed: bool | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    limit: int = 20,
    offset: int = 0,
    auto_sync: bool = False,
) -> dict[str, Any]:
    """Return one compact page of local reviews and cached Koromo hanchan games.

    Times are Unix seconds. Use open_game_catalog for interactive browsing instead of
    sending a large game list into the conversation.
    """
    return service.list_koromo_games(
        majsoul_uid=majsoul_uid,
        rank=rank,
        reviewed=reviewed,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
        auto_sync=auto_sync,
    )


@mcp.tool(meta={"ui": {"visibility": ["model", "app"]}})
def get_koromo_sync_status(
    majsoul_uid: int | None = None,
) -> dict[str, Any]:
    """Return compact local cache and Koromo sync status for bound accounts."""
    return service.koromo_sync_status(majsoul_uid=majsoul_uid)


@mcp.tool(meta={"ui": {"visibility": ["model", "app"]}})
def prepare_selected_game_review(
    uuid: str,
    model_tag: str | None = None,
) -> dict[str, Any]:
    """Prepare a game selected from the combined local game catalog.

    This only creates the prefilled URL. Opening and submitting remain browser actions;
    this tool itself does not start external analysis.
    """
    return service.prepare_selected_game_review(uuid, model_tag=model_tag)


@mcp.tool()
def list_reviews(limit: int = 20) -> list[dict[str, Any]]:
    """List locally stored reviews, newest first."""
    return service.list_reviews(limit=limit)


@mcp.tool()
def get_review_viewer(review_id: str) -> dict[str, Any]:
    """Return the best visual replay URL for a locally stored review.

    Prefer mortal_viewer_url when available. Older records may only have paipu_url;
    opening it still restores a tile-by-tile replay without rerunning Mortal.
    """
    return service.review_viewer(review_id)


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
    """Return a decision with Mortal evidence and reconstructed table context."""
    return service.decision(
        review_id,
        decision_id,
        candidate_limit=candidate_limit,
    )


@mcp.tool()
def analyze_tile_efficiency(
    review_id: str,
    decision_id: str,
    discards: list[str] | None = None,
) -> dict[str, Any]:
    """Calculate deterministic shanten, effective draws, and shape waits.

    Use after get_decision when explaining exact tile efficiency. Pass the discards
    relevant to the question to keep the result focused. Availability counts mean
    copies not visible to the player, not tiles known to remain in the live wall.
    Mortal Q values are included separately and do not explain its policy choice.
    """
    return service.tile_efficiency(
        review_id,
        decision_id,
        discards=discards,
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

    Do not call this for silent inference or ordinary Mortal disagreement.
    Suitable kinds include mistake, style_preference, goal, strength,
    teaching_preference, question, understood, and pattern.
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


def _catalog_tool_result(result: dict[str, Any]) -> types.CallToolResult:
    summary = {
        "total": int(result["total"]),
        "limit": int(result["limit"]),
        "offset": int(result["offset"]),
        "has_more": bool(result["has_more"]),
        "sync_status": result.get("sync_status"),
        "catalog_notice": result.get("catalog_notice"),
    }
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=(
                    f"Opened the local MJTutor catalog with {summary['total']} cached "
                    "games. Game rows stay in component-only metadata."
                ),
            )
        ],
        structuredContent=summary,
        _meta={"mjtutor/catalog": result},
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
