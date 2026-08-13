from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from .errors import ReviewerError
from .logs import LogMetadata
from .models import ReviewDocument

MAJSOUL_HOSTS = {
    "game.maj-soul.com",
    "game.mahjongsoul.com",
    "mahjongsoul.game.yo-star.com",
}
REPORT_HOSTS = {"mjai.ekyu.moe", "gh.ekyu.moe"}
LANGUAGE_PATHS = {
    "zh-CN": "/zh-cn.html",
    "en": "/",
    "ja": "/ja.html",
    "ko": "/ko.html",
}
MORTAL_MODEL_CATALOG = (
    {
        "tag": "4.1c",
        "label": "First-place-oriented",
        "site_label_zh": "争一型",
        "guidance": (
            "Prefer when the review should emphasize converting chances into "
            "first place."
        ),
    },
    {
        "tag": "4.1b",
        "label": "Balanced",
        "site_label_zh": "平衡型",
        "guidance": "A practical general-purpose starting point for routine review.",
    },
    {
        "tag": "4.1a",
        "label": "Fourth-place-avoidant",
        "site_label_zh": "避四型",
        "guidance": (
            "Prefer when avoiding fourth place is the main placement objective."
        ),
    },
    {
        "tag": "4.0",
        "label": "Legacy",
        "site_label_zh": "旧版",
        "guidance": (
            "Keep mainly for comparison with reports made using the older network."
        ),
    },
    {
        "tag": "3.0",
        "label": "More human-like, but weakest",
        "site_label_zh": "更像人类，但是最弱",
        "guidance": "Can provide gentler, more human-like alternatives, but is weaker.",
    },
)
MODEL_TAGS = frozenset(item["tag"] for item in MORTAL_MODEL_CATALOG)
MAX_REPORT_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class RemoteReviewResult:
    metadata: LogMetadata
    review: ReviewDocument
    player_id: int
    report_json_url: str


class MortalWebProvider:
    def status(self) -> dict[str, Any]:
        return {
            "available": True,
            "mode": "human_verification_required",
            "inference_location": "remote",
            "submission_site": "https://mjai.ekyu.moe",
            "public_api": False,
            "notice": (
                "Mortal Web uses Cloudflare Turnstile. MJTutor can prefill the log URL "
                "and import the completed report, but cannot submit headlessly or "
                "bypass verification."
            ),
        }

    def prepare(
        self,
        log_url: str,
        *,
        language: str = "zh-CN",
        model_tag: str = "4.1b",
        kyokus: str | None = None,
    ) -> dict[str, Any]:
        normalized_log_url = validate_majsoul_url(log_url)
        language = validate_mortal_web_language(language)
        model_tag = validate_mortal_model_tag(model_tag)

        query = urlencode({"url": normalized_log_url})
        submission_url = urlunparse(
            ("https", "mjai.ekyu.moe", LANGUAGE_PATHS[language], "", query, "")
        )
        return {
            "provider": "mortal_web",
            "status": "awaiting_human_verification",
            "majsoul_log_url": normalized_log_url,
            "submission_url": submission_url,
            "requested_settings": {
                "engine": "mortal",
                "model_tag": model_tag,
                "ui": "killerducky",
                "language": language,
                "kyokus": kyokus,
            },
            "next_step": (
                "Open submission_url and set the requested model. If the user asked "
                "to start this review, inspect only the first review form's submit "
                "button. Treat its initial disabled state as transient and poll the "
                "current URL plus its live disabled property every 500-1000 ms for up "
                "to 10 seconds. Recheck both immediately before acting. Submit once "
                "if enabled; otherwise hand off the visible page without claiming why "
                "it remains disabled. Then pass the generated /report/ JSON or HTML "
                "URL to "
                "import_mortal_web_report."
            ),
            "automatic_submission": False,
        }

    def fetch_report(
        self, report_url: str, *, source_log_url: str
    ) -> RemoteReviewResult:
        normalized_source = validate_majsoul_url(source_log_url)
        report_json_url = normalize_report_json_url(report_url)
        request = Request(
            report_json_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "MJTutor/0.1 (+local personal review tool)",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                content_type = response.headers.get_content_type()
                payload = response.read(MAX_REPORT_BYTES + 1)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ReviewerError(f"Could not download Mortal Web report: {exc}") from exc
        if len(payload) > MAX_REPORT_BYTES:
            raise ReviewerError("Mortal Web report is larger than 50 MiB")
        if content_type not in {"application/json", "text/json", "text/plain"}:
            raise ReviewerError(
                f"Mortal Web report did not return JSON (content type: {content_type})"
            )
        try:
            raw = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReviewerError("Mortal Web report is not valid JSON") from exc

        review = ReviewDocument.from_json(raw)
        player_id = raw.get("player_id") if isinstance(raw, dict) else None
        if not isinstance(player_id, int) or player_id not in range(4):
            raise ReviewerError("Mortal Web report is missing a valid player_id")
        names = _extract_player_names(raw)
        metadata = LogMetadata(
            path=normalized_source,
            sha256=hashlib.sha256(payload).hexdigest(),
            format="mortal-web-report-json",
            rule_display="Mortal Web four-player hanchan",
            player_names=names,
            round_count=len(review.raw.get("review", {}).get("kyokus", [])),
            is_four_player=True,
            is_hanchan=True,
            reference=report_json_url,
        )
        return RemoteReviewResult(
            metadata=metadata,
            review=review,
            player_id=player_id,
            report_json_url=report_json_url,
        )


def mortal_model_catalog() -> list[dict[str, str]]:
    return [dict(item) for item in MORTAL_MODEL_CATALOG]


def validate_mortal_model_tag(value: str) -> str:
    model_tag = value.strip()
    if model_tag not in MODEL_TAGS:
        available = ", ".join(item["tag"] for item in MORTAL_MODEL_CATALOG)
        raise ReviewerError(f"model_tag must be one of: {available}")
    return model_tag


def validate_mortal_web_language(value: str) -> str:
    if value not in LANGUAGE_PATHS:
        raise ReviewerError(f"language must be one of: {', '.join(LANGUAGE_PATHS)}")
    return value


def validate_majsoul_url(value: str) -> str:
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or host not in MAJSOUL_HOSTS:
        raise ReviewerError(
            "Expected an HTTPS Mahjong Soul paipu URL from game.maj-soul.com, "
            "game.mahjongsoul.com, or mahjongsoul.game.yo-star.com"
        )
    if not parse_qs(parsed.query).get("paipu"):
        raise ReviewerError("Mahjong Soul URL is missing the paipu query parameter")
    return urlunparse(("https", host, parsed.path or "/", "", parsed.query, ""))


def normalize_report_json_url(value: str) -> str:
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or host not in REPORT_HOSTS:
        raise ReviewerError("Report URL must use HTTPS on mjai.ekyu.moe or gh.ekyu.moe")
    if host == "mjai.ekyu.moe" and parsed.path.rstrip("/") == "/killerducky":
        data_values = parse_qs(parsed.query).get("data")
        if not data_values:
            raise ReviewerError("Mortal viewer URL is missing its report data path")
        data = data_values[0]
        if data.startswith("/report/"):
            parsed = urlparse(f"https://mjai.ekyu.moe{data}")
        else:
            parsed = urlparse(data)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or host not in REPORT_HOSTS:
            raise ReviewerError("Mortal viewer data must reference a supported report")
    if "/report/" not in parsed.path:
        raise ReviewerError("Expected a Mortal Web /report/ URL")
    path = parsed.path
    if path.endswith(".html"):
        path = f"{path[:-5]}.json"
    elif not path.endswith(".json"):
        raise ReviewerError("Report URL must end in .html or .json")
    return urlunparse(("https", host, path, "", "", ""))


def make_report_viewer_url(report_url: str) -> str:
    """Return the KillerDucky viewer URL for a stored Mortal report."""
    report_json_url = normalize_report_json_url(report_url)
    parsed = urlparse(report_json_url)
    data = parsed.path if parsed.hostname == "mjai.ekyu.moe" else report_json_url
    query = urlencode({"data": data})
    return f"https://mjai.ekyu.moe/killerducky/?{query}"


def _extract_player_names(raw: dict[str, Any]) -> list[str]:
    split_logs = raw.get("split_logs")
    if isinstance(split_logs, list):
        for log in split_logs:
            if isinstance(log, dict):
                names = log.get("name")
                if isinstance(names, list) and len(names) == 4:
                    return [str(name) for name in names]
    return ["Player 0", "Player 1", "Player 2", "Player 3"]
