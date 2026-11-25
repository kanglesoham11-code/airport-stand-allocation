"""Authentication, fingerprints and ETags (sections 10A.3, 10A.5).

No secrets are logged; only key fingerprints appear in logs.
"""

from __future__ import annotations

import hashlib
import hmac

from stand_allocation import config


def key_matches(presented: str | None, configured: list[str]) -> bool:
    """True when the presented key matches at least one configured key.

    Every configured key is compared even after a match, so timing does not
    reveal which key matched (hmac.compare_digest).
    """
    if not presented:
        return False
    presented_bytes = presented.encode("utf-8")
    matched = False
    for key in configured:
        matched = hmac.compare_digest(presented_bytes, key.encode("utf-8")) or matched
    return matched


def key_fingerprint(key: str) -> str:
    """First 8 hex characters of the SHA-256 of the key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[: config.FINGERPRINT_HEX_LENGTH]


def etag_for(run_id: str, path_and_query: str) -> str:
    """ETag: double quote + 32 hex chars of SHA-256(run_id|path+query) + double quote."""
    digest = hashlib.sha256((run_id + "|" + path_and_query).encode("utf-8")).hexdigest()
    return f'"{digest[: config.ETAG_HEX_LENGTH]}"'


def etag_matches(header: str | None, etag: str) -> bool:
    """True when the If-None-Match header equals the ETag or '*'."""
    if header is None:
        return False
    for part in header.split(","):
        part = part.strip()
        if part == etag or part == "*":
            return True
        if part.startswith("W/"):
            continue  # weak tags never match
    return False
