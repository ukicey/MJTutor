from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .errors import CoachError

_ACCOUNT_ID_XOR = 86_216_345
_ACCOUNT_ID_ADDEND = 1_117_113
_PAIPU_ID_OFFSET = 1_358_437
_PAIPU_ACCOUNT_PATTERN = re.compile(r"_a(\d+)$")
_PAIPU_UUID_PATTERN = re.compile(r"^([^_]+)")


def encode_paipu_account_id(koromo_account_id: int) -> int:
    """Encode Koromo's internal account ID for a paipu viewer suffix."""
    if koromo_account_id <= 0:
        raise CoachError("koromo_account_id must be a positive integer")
    return _PAIPU_ID_OFFSET + (
        (7 * koromo_account_id + _ACCOUNT_ID_ADDEND) ^ _ACCOUNT_ID_XOR
    )


def decode_paipu_account_id(encoded_id: int) -> int | None:
    if encoded_id <= _PAIPU_ID_OFFSET:
        return None
    decoded = ((encoded_id - _PAIPU_ID_OFFSET) ^ _ACCOUNT_ID_XOR) - _ACCOUNT_ID_ADDEND
    if decoded <= 0 or decoded % 7:
        return None
    koromo_account_id = decoded // 7
    if encode_paipu_account_id(koromo_account_id) != encoded_id:
        return None
    return koromo_account_id


def extract_koromo_account_id(paipu_url: str) -> int | None:
    """Return Koromo's internal account ID selected by a paipu URL."""
    parsed = urlparse(paipu_url.strip())
    paipu_values = parse_qs(parsed.query).get("paipu")
    if not paipu_values:
        return None
    match = _PAIPU_ACCOUNT_PATTERN.search(paipu_values[0])
    if match is None:
        return None
    return decode_paipu_account_id(int(match.group(1)))


def extract_paipu_uuid(paipu_url: str) -> str | None:
    parsed = urlparse(paipu_url.strip())
    paipu_values = parse_qs(parsed.query).get("paipu")
    if not paipu_values:
        return None
    match = _PAIPU_UUID_PATTERN.match(paipu_values[0])
    return match.group(1) if match else None
