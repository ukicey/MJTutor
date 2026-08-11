from pathlib import Path

import pytest

from mjtutor.errors import InvalidLogError
from mjtutor.logs import inspect_tenhou_v6_log

FIXTURES = Path(__file__).parent / "fixtures"


def test_inspect_hanchan_log() -> None:
    metadata = inspect_tenhou_v6_log(FIXTURES / "sample_hanchan.json")

    assert metadata.is_four_player is True
    assert metadata.is_hanchan is True
    assert metadata.player_names[0] == "Player"
    assert len(metadata.sha256) == 64


def test_rejects_east_only_log(tmp_path: Path) -> None:
    path = tmp_path / "east.json"
    path.write_text(
        '{"name":["A","B","C","D"],"rule":{"disp":"四人东"},"log":[[]]}',
        encoding="utf-8",
    )

    with pytest.raises(InvalidLogError, match="hanchan"):
        inspect_tenhou_v6_log(path)
