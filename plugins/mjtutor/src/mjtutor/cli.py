from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from .errors import CoachError
from .service import CoachService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mjtutor")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("setup", help="show Mortal Web and local data readiness")

    account_parser = commands.add_parser(
        "account-bind",
        help="bind a user-confirmed Mahjong Soul account to the local profile",
    )
    account_parser.add_argument("nickname")
    account_parser.add_argument("account_id", type=int)

    commands.add_parser(
        "profile", help="show local accounts and compact coaching memory"
    )
    commands.add_parser(
        "preferences", help="show local analysis preferences and Mortal models"
    )
    model_parser = commands.add_parser(
        "model-default", help="set the default Mortal Web model"
    )
    model_parser.add_argument(
        "model_tag", choices=("4.1c", "4.1b", "4.1a", "4.0", "3.0")
    )
    commands.add_parser(
        "model-default-clear", help="clear the default Mortal Web model"
    )

    web_parser = commands.add_parser(
        "web-prepare", help="prepare a human-verified remote Mortal review"
    )
    web_parser.add_argument("majsoul_log_url")
    web_parser.add_argument(
        "--language", default="zh-CN", choices=("zh-CN", "en", "ja", "ko")
    )
    web_parser.add_argument("--model", choices=("4.1c", "4.1b", "4.1a", "4.0", "3.0"))
    web_parser.add_argument("--kyokus")

    web_import_parser = commands.add_parser(
        "web-import", help="import a completed Mortal Web report"
    )
    web_import_parser.add_argument("report_url")
    web_import_parser.add_argument("majsoul_log_url")

    list_parser = commands.add_parser("list", help="list stored reviews")
    list_parser.add_argument("--limit", type=int, default=20)

    summary_parser = commands.add_parser(
        "summary", help="show the largest disagreements"
    )
    summary_parser.add_argument("review_id")
    summary_parser.add_argument("--limit", type=int, default=10)

    decision_parser = commands.add_parser("decision", help="show one review decision")
    decision_parser.add_argument("review_id")
    decision_parser.add_argument("decision_id")
    decision_parser.add_argument("--candidates", type=int, default=8)

    efficiency_parser = commands.add_parser(
        "tile-efficiency", help="calculate exact discard shape and effective draws"
    )
    efficiency_parser.add_argument("review_id")
    efficiency_parser.add_argument("decision_id")
    efficiency_parser.add_argument("--discard", action="append", dest="discards")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    service = CoachService()
    actions: dict[str, Callable[[], Any]] = {
        "setup": service.check_setup,
        "account-bind": lambda: service.bind_majsoul_account(
            nickname=args.nickname,
            account_id=args.account_id,
        ),
        "profile": service.local_profile,
        "preferences": service.analysis_preferences,
        "model-default": lambda: service.set_default_mortal_model(args.model_tag),
        "model-default-clear": service.clear_default_mortal_model,
        "web-prepare": lambda: service.prepare_web_review(
            args.majsoul_log_url,
            language=args.language,
            model_tag=args.model,
            kyokus=args.kyokus,
        ),
        "web-import": lambda: service.import_web_report(
            args.report_url,
            source_log_url=args.majsoul_log_url,
        ),
        "list": lambda: service.list_reviews(limit=args.limit),
        "summary": lambda: service.review_summary(
            args.review_id, weak_limit=args.limit
        ),
        "decision": lambda: service.decision(
            args.review_id, args.decision_id, candidate_limit=args.candidates
        ),
        "tile-efficiency": lambda: service.tile_efficiency(
            args.review_id,
            args.decision_id,
            discards=args.discards,
        ),
    }
    try:
        result = actions[args.command]()
    except CoachError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
