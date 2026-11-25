"""Application configuration (section 6 and 6A).

Every setting lives in this file. No other module may contain these numbers.
Values here are starting values; if a run falls outside the target bands in
section 7.2, change a value here first and record the reason in
docs/design-notes.md.

Settings marked "env" may be overridden by an environment variable. load_settings()
is called at import time so that the API reads settings as soon as it is created
(section 13.2).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Project layout
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STANDS_CSV = DATA_DIR / "stands.csv"
FLIGHTS_CSV = DATA_DIR / "flights.csv"
DB_PATH = PROJECT_ROOT / "data" / "allocation.db"

# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
WINDOW_START = datetime(2027, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2027, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
WINDOW_LENGTH_SECONDS = int((WINDOW_END - WINDOW_START).total_seconds())  # 21,600
SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
MS_PER_SECOND = 1000

# ---------------------------------------------------------------------------
# Buffer
# ---------------------------------------------------------------------------
BUFFER_MINUTES = 15
MAX_BUFFER_MINUTES = 60
BUFFER_SECONDS = BUFFER_MINUTES * SECONDS_PER_MINUTE

# ---------------------------------------------------------------------------
# Aircraft sizes and stand types
# ---------------------------------------------------------------------------
SIZE_RANK = {"S": 0, "M": 1, "L": 2}
VALID_SIZES = frozenset(SIZE_RANK)
STAND_TYPE_RANK = {"PLB": 0, "REMOTE": 1}  # lower number is preferred
VALID_STAND_TYPES = frozenset(STAND_TYPE_RANK)

# ---------------------------------------------------------------------------
# Data generation (section 7.2)
# ---------------------------------------------------------------------------
RANDOM_SEED = 2027
CLEAN_FLIGHT_COUNT = 40
BAD_ROW_COUNT = 9
# SIZE_MIX running totals: draw < 0.30 -> S, < 0.80 -> M, otherwise L.
SIZE_MIX = (0.30, 0.80)
ARRIVAL_PEAK_SHARE = 0.40
# Slots are 5-minute steps from 06:00 UTC. Peak 07:30-09:30 (slots 18-42),
# off-peak ends at 11:30 (slot 66).
PEAK_FIRST_SLOT = 18
PEAK_END_SLOT = 42
OFF_PEAK_END_SLOT = 66
TIME_STEP_MINUTES = 5
# (lo, hi) ground minutes per size; every bound is a multiple of 5.
GROUND_MINUTES_RANGE = {"S": (25, 55), "M": (45, 95), "L": (75, 150)}
AIRLINE_CODES = ("AX", "BQ", "CZ", "DX", "EZ")
FLIGHT_NUMBER_MIN = 100
FLIGHT_NUMBER_MAX = 999
# IDs used by the injected bad rows; generated IDs must avoid them.
RESERVED_FLIGHT_IDS = frozenset(
    {"FR207", "KT610", "CZ411", "DL902", "EV318", "GO550", "BQ880", "KT999"}
)
MIN_GROUND_MINUTES = 20
MAX_GROUND_HOURS = 8
TIGHT_TURN_MINUTES = 30

# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------
MAX_BLOCKED_BY_SHOWN = 6

# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------
SOLVER_TIME_LIMIT_SECONDS: float = 10
SOLVER_NUM_WORKERS = 1
ALLOCATOR = "cpsat"  # "cpsat" or "greedy"

# ---------------------------------------------------------------------------
# Files and limits
# ---------------------------------------------------------------------------
MAX_CSV_BYTES = 5_000_000
MAX_CSV_ROWS = 10_000
SQLITE_BUSY_TIMEOUT_MS = 5000
RUN_RETENTION = 10
SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 8000
MIN_API_KEY_LENGTH = 32
MAX_PAGE_LIMIT = 500
DEFAULT_PAGE_LIMIT = 100
LATENCY_WINDOW = 1000
LATENCY_PERCENTILE = 95
PERCENT_SCALE = 100
PERCENT_DECIMALS = 1
FINGERPRINT_HEX_LENGTH = 8
ETAG_HEX_LENGTH = 32
REQUEST_ID_PATTERN = r"^[A-Za-z0-9._-]{8,64}$"
RATE_LIMIT_CAPACITY = 60
RATE_LIMIT_REFILL_PER_SECOND = 1.0
RATE_LIMIT_MAX_KEYS = 10000
RATE_EPSILON = 1e-9
# Auth-failure bucket: small capacity, slow refill, so a flood of wrong keys
# is slowed down and a full bucket retries after about 12 seconds.
AUTH_FAILURE_CAPACITY = 5
AUTH_FAILURE_REFILL_PER_SECOND = 1 / 12.0
LOG_LEVEL = "INFO"

PLACEHOLDER_KEYS = frozenset(
    {
        "changeme",
        "your-api-key",
        "your-api-key-here",
        "replace-me",
        "default",
        "secret",
        "test",
        "test-key",
        "sk-test",
        "your-secret-key",
    }
)

# Set at startup from the API_KEYS environment variable by load_settings().
API_KEYS: list[str] = []
ALLOWED_ORIGINS: list[str] = []
TRUST_PROXY_HEADERS = False

AUTH_FREE_PATHS = frozenset(
    {"/health", "/ready", "/docs", "/openapi.json", "/docs/oauth2-redirect"}
)

CSV_ENCODING = "utf-8-sig"


class SettingsError(Exception):
    """Raised when a setting is invalid; the program stops with exit code 1."""


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _parse_bool(text: str) -> bool:
    lower = text.strip().lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    raise SettingsError(f"value '{text}' is not 'true' or 'false'")


def load_settings() -> None:
    """Read environment overrides and validate every setting (section 23.1)."""
    global API_KEYS, BUFFER_MINUTES, SOLVER_TIME_LIMIT_SECONDS, ALLOCATOR, LOG_LEVEL, DB_PATH

    # --- API_KEYS (required) ---
    raw_keys = _env("API_KEYS", "")
    parts = [part.strip() for part in raw_keys.split(",") if part.strip()]
    if not parts:
        raise SettingsError("setting API_KEYS: at least one key is required")
    seen: set[str] = set()
    for key in parts:
        if len(key) < MIN_API_KEY_LENGTH:
            raise SettingsError(
                f"setting API_KEYS: key is shorter than {MIN_API_KEY_LENGTH} characters"
            )
        if key.lower() in PLACEHOLDER_KEYS:
            raise SettingsError(
                "setting API_KEYS: key is a placeholder such as 'changeme'"
            )
        if key in seen:
            raise SettingsError(f"setting API_KEYS: duplicate key {key!r}")
        seen.add(key)
    API_KEYS = parts

    # --- BUFFER_MINUTES ---
    try:
        buffer_minutes = int(_env("BUFFER_MINUTES", str(BUFFER_MINUTES)))
    except ValueError:
        raise SettingsError(
            f"setting BUFFER_MINUTES: value '{_env('BUFFER_MINUTES', str(BUFFER_MINUTES))}' "
            f"is not a whole number"
        ) from None
    if not (0 <= buffer_minutes <= MAX_BUFFER_MINUTES):
        raise SettingsError(
            f"setting BUFFER_MINUTES: value {buffer_minutes} is not in 0..{MAX_BUFFER_MINUTES}"
        )
    BUFFER_MINUTES = buffer_minutes

    # --- SOLVER_TIME_LIMIT_SECONDS ---
    try:
        time_limit = float(_env("SOLVER_TIME_LIMIT_SECONDS", str(SOLVER_TIME_LIMIT_SECONDS)))
    except ValueError:
        raise SettingsError(
            "setting SOLVER_TIME_LIMIT_SECONDS: value is not a number"
        ) from None
    import math

    if not math.isfinite(time_limit) or not (0 < time_limit <= 60):
        raise SettingsError(
            "setting SOLVER_TIME_LIMIT_SECONDS: value must be above 0 and at most 60"
        )
    SOLVER_TIME_LIMIT_SECONDS = time_limit

    # --- ALLOCATOR ---
    allocator = _env("ALLOCATOR", ALLOCATOR)
    if allocator not in ("cpsat", "greedy"):
        raise SettingsError(f"setting ALLOCATOR: value '{allocator}' is not cpsat or greedy")
    ALLOCATOR = allocator

    # --- LOG_LEVEL ---
    log_level = _env("LOG_LEVEL", LOG_LEVEL).upper()
    if log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise SettingsError(
            f"setting LOG_LEVEL: value '{log_level}' is not DEBUG, INFO, WARNING or ERROR"
        )
    LOG_LEVEL = log_level

    # --- DB_PATH ---
    db_path = _env("DB_PATH", str(DB_PATH))
    DB_PATH = Path(db_path)
    if not DB_PATH.is_absolute():
        DB_PATH = PROJECT_ROOT / db_path

    # --- ALLOWED_ORIGINS ---
    global ALLOWED_ORIGINS
    origins = _env("ALLOWED_ORIGINS", "")
    ALLOWED_ORIGINS = [o.strip() for o in origins.split(",") if o.strip()]


def _fail(message: str) -> None:
    """Print one line naming the setting and exit with code 1."""
    print(message, file=sys.stderr)
    sys.exit(1)


# Load settings at import time. Any invalid value stops the program here.
try:
    load_settings()
except SettingsError as exc:
    _fail(str(exc))
