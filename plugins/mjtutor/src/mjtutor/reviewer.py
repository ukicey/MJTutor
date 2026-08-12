from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import ReviewerError
from .logs import LogMetadata, inspect_tenhou_v6_log
from .models import ReviewDocument


@dataclass(frozen=True)
class ReviewerConfig:
    reviewer_bin: str
    mortal_exe: str | None
    mortal_config: str | None
    timeout_seconds: int = 1800

    @classmethod
    def from_env(cls) -> ReviewerConfig:
        return cls(
            reviewer_bin=os.environ.get("MJTUTOR_REVIEWER_BIN", "mjai-reviewer"),
            mortal_exe=os.environ.get("MJTUTOR_MORTAL_EXE"),
            mortal_config=os.environ.get("MJTUTOR_MORTAL_CONFIG"),
            timeout_seconds=int(os.environ.get("MJTUTOR_TIMEOUT_SECONDS", "1800")),
        )

    def status(self) -> dict[str, Any]:
        reviewer_path = _resolve_executable(self.reviewer_bin)
        mortal_exe_ok = bool(self.mortal_exe and Path(self.mortal_exe).expanduser().is_file())
        mortal_config_ok = bool(
            self.mortal_config and Path(self.mortal_config).expanduser().is_file()
        )
        return {
            **asdict(self),
            "reviewer_resolved": reviewer_path,
            "reviewer_ready": reviewer_path is not None,
            "mortal_exe_ready": mortal_exe_ok,
            "mortal_config_ready": mortal_config_ok,
            "ready": reviewer_path is not None and mortal_exe_ok and mortal_config_ok,
        }


@dataclass(frozen=True)
class ReviewResult:
    metadata: LogMetadata
    review: ReviewDocument


class MortalReviewer:
    def __init__(self, config: ReviewerConfig | None = None) -> None:
        self.config = config or ReviewerConfig.from_env()

    def review(
        self,
        log_path: str | Path,
        *,
        player_id: int,
        kyokus: str | None = None,
    ) -> ReviewResult:
        if player_id not in range(4):
            raise ReviewerError("player_id must be within 0-3")
        metadata = inspect_tenhou_v6_log(log_path)
        status = self.config.status()
        if not status["ready"]:
            raise ReviewerError(
                "Mortal is not configured. Call check_setup and set the missing "
                "MJTUTOR_* paths before reviewing."
            )

        command = [
            str(status["reviewer_resolved"]),
            "--engine",
            "mortal",
            "--in-file",
            metadata.path,
            "--player-id",
            str(player_id),
            "--json",
            "--out-file",
            "-",
            "--no-open",
            "--without-log-viewer",
            "--mortal-exe",
            str(Path(self.config.mortal_exe or "").expanduser()),
            "--mortal-cfg",
            str(Path(self.config.mortal_config or "").expanduser()),
        ]
        if kyokus:
            command.extend(("--kyokus", kyokus))

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReviewerError(
                f"Mortal review exceeded {self.config.timeout_seconds} seconds"
            ) from exc
        except OSError as exc:
            raise ReviewerError(f"Failed to start mjai-reviewer: {exc}") from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ReviewerError(
                f"mjai-reviewer exited with code {completed.returncode}: {detail[-2000:]}"
            )

        try:
            output = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ReviewerError("mjai-reviewer did not return valid JSON") from exc
        return ReviewResult(
            metadata=metadata,
            review=ReviewDocument.from_json(output, player_id=player_id),
        )


def load_review_file(path: str | Path, *, player_id: int | None = None) -> ReviewDocument:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ReviewerError(f"Review file does not exist: {source}")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewerError(f"Review is not valid UTF-8 JSON: {source}") from exc
    return ReviewDocument.from_json(raw, player_id=player_id)


def _resolve_executable(value: str) -> str | None:
    candidate = Path(value).expanduser()
    if candidate.parent != Path(".") or candidate.is_absolute():
        return str(candidate.resolve()) if candidate.is_file() else None
    return shutil.which(value)
