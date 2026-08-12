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

    commands.add_parser("setup", help="check local reviewer and Mortal paths")

    account_parser = commands.add_parser(
        "account-bind", help="bind a user-confirmed Koromo account to the local profile"
    )
    account_parser.add_argument("nickname")
    account_parser.add_argument("koromo_player_id", type=int)

    commands.add_parser(
        "profile", help="show local accounts and compact coaching memory"
    )

    inspect_parser = commands.add_parser(
        "inspect", help="validate a Mahjong Soul export"
    )
    inspect_parser.add_argument("log_path")

    review_parser = commands.add_parser("review", help="run and store a Mortal review")
    review_parser.add_argument("log_path")
    review_parser.add_argument("--seat", type=int, required=True, choices=range(4))
    review_parser.add_argument("--kyokus")

    web_parser = commands.add_parser(
        "web-prepare", help="prepare a human-verified remote Mortal review"
    )
    web_parser.add_argument("majsoul_log_url")
    web_parser.add_argument(
        "--language", default="zh-CN", choices=("zh-CN", "en", "ja", "ko")
    )
    web_parser.add_argument(
        "--model", default="4.1b", choices=("4.1c", "4.1b", "4.1a", "4.0", "3.0")
    )
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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    service = CoachService()
    actions: dict[str, Callable[[], Any]] = {
        "setup": service.check_setup,
        "account-bind": lambda: service.bind_koromo_account(
            nickname=args.nickname,
            koromo_player_id=args.koromo_player_id,
        ),
        "profile": service.local_profile,
        "inspect": lambda: service.inspect_log(args.log_path),
        "review": lambda: service.review_log(
            args.log_path, player_id=args.seat, kyokus=args.kyokus
        ),
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
    }
    try:
        result = actions[args.command]()
    except CoachError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
