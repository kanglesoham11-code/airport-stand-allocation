"""Repository: SQLite persistence for runs (sections 23.44-23.47).

All SQL text lives in this file. db.py only opens connections. Every query uses
? placeholders. One run is saved in a single transaction.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from stand_allocation import config
from stand_allocation.models import Allocation, DataIssue, Metric, SavedRun, Stand

SCHEMA_VERSION = config.SCHEMA_VERSION

# Migration 1 creates the full schema (section 23.47).
MIGRATIONS: dict[int, list[str]] = {
    1: [
        "CREATE TABLE runs (",
        "  seq INTEGER PRIMARY KEY AUTOINCREMENT,",
        "  run_id TEXT NOT NULL UNIQUE,",
        "  status TEXT NOT NULL CHECK (status IN ('INCOMPLETE', 'COMPLETE')),",
        "  created_at TEXT NOT NULL,",
        "  buffer_minutes INTEGER NOT NULL,",
        "  allocator TEXT NOT NULL,",
        "  primary_method TEXT NOT NULL,",
        "  solver_status TEXT NOT NULL,",
        "  solve_seconds REAL NOT NULL,",
        "  input_hashes TEXT NOT NULL",
        ");",
        "CREATE TABLE stands (",
        "  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,",
        "  stand_id TEXT NOT NULL,",
        "  stand_type TEXT NOT NULL,",
        "  max_size TEXT NOT NULL,",
        "  PRIMARY KEY (run_id, stand_id)",
        ");",
        "CREATE TABLE allocations (",
        "  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,",
        "  method TEXT NOT NULL CHECK (method IN ('PRIMARY', 'BASELINE')),",
        "  flight_id TEXT NOT NULL,",
        "  aircraft_size TEXT NOT NULL,",
        "  arrival TEXT NOT NULL,",
        "  departure TEXT NOT NULL,",
        "  status TEXT NOT NULL CHECK (status IN ('ASSIGNED', 'UNASSIGNED')),",
        "  stand_id TEXT,",
        "  stand_type TEXT,",
        "  note TEXT,",
        "  reason_code TEXT,",
        "  reason TEXT,",
        "  blocked_by TEXT NOT NULL,",
        "  PRIMARY KEY (run_id, method, flight_id)",
        ");",
        "CREATE INDEX idx_alloc_stand ON allocations "
        "(run_id, method, stand_id, arrival, flight_id);",
        "CREATE TABLE data_issues (",
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,",
        "  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,",
        "  line_number INTEGER NOT NULL,",
        "  flight_id TEXT NOT NULL,",
        "  field TEXT NOT NULL,",
        "  issue_code TEXT NOT NULL,",
        "  action TEXT NOT NULL CHECK (action IN ('DROPPED', 'FIXED')),",
        "  original_value TEXT NOT NULL,",
        "  new_value TEXT,",
        "  explanation TEXT NOT NULL",
        ");",
        "CREATE INDEX idx_issues_run ON data_issues (run_id, line_number);",
        "CREATE TABLE metrics (",
        "  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,",
        "  metric_id TEXT NOT NULL,",
        "  name TEXT NOT NULL,",
        "  value REAL,",
        "  unit TEXT NOT NULL,",
        "  window_text TEXT NOT NULL,",
        "  flights_covered INTEGER NOT NULL,",
        "  definition TEXT NOT NULL,",
        "  why_it_matters TEXT NOT NULL,",
        "  PRIMARY KEY (run_id, metric_id)",
        ");",
    ]
}


def _statements(fragments: list[str]) -> list[str]:
    """Join SQL fragments into complete statements ending with ';'."""
    statements: list[str] = []
    buffer: list[str] = []
    for fragment in fragments:
        buffer.append(fragment)
        if fragment.rstrip().endswith(";"):
            statements.append("".join(buffer))
            buffer = []
    if buffer:
        statements.append("".join(buffer))
    return statements


def migrate(conn: sqlite3.Connection) -> None:
    """Create the schema if missing, apply migrations, refuse a newer version."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
    )
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        version = 0
    else:
        version = row[0]

    if version > SCHEMA_VERSION:
        raise FutureSchemaError(
            f"database schema version {version} is newer than this program's "
            f"version {SCHEMA_VERSION}"
        )

    for n in range(version + 1, SCHEMA_VERSION + 1):
        statements = _statements(MIGRATIONS[n])
        conn.execute("BEGIN")
        try:
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "UPDATE schema_version SET version = ?", (n,)
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


class FutureSchemaError(Exception):
    """Raised when the database schema is newer than the program expects."""


def _now_text() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def save_run(
    conn: sqlite3.Connection,
    run_id: str | None,
    buffer_minutes: int,
    allocator: str,
    primary_method: str,
    solver_status: str,
    solve_seconds: float,
    input_hashes: dict[str, str],
    stands: list[Stand],
    primary_allocations: list[Allocation],
    baseline_allocations: list[Allocation],
    data_issues: list[DataIssue],
    metrics: list[Metric],
) -> str:
    """Save one complete run in a single transaction (section 23.44)."""
    created_at = _now_text()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM runs").fetchone()
        next_seq = int(row[0]) + 1
        if run_id is None:
            run_id = f"run-{next_seq:04d}"

        conn.execute(
            "INSERT INTO runs (run_id, status, created_at, buffer_minutes, "
            "allocator, primary_method, solver_status, solve_seconds, input_hashes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                "INCOMPLETE",
                created_at,
                buffer_minutes,
                allocator,
                primary_method,
                solver_status,
                solve_seconds,
                _canonical(input_hashes),
            ),
        )

        conn.executemany(
            "INSERT INTO stands (run_id, stand_id, stand_type, max_size) "
            "VALUES (?, ?, ?, ?)",
            [
                (run_id, stand.stand_id, stand.stand_type, stand.max_size)
                for stand in stands
            ],
        )

        conn.executemany(
            "INSERT INTO allocations "
            "(run_id, method, flight_id, aircraft_size, arrival, departure, "
            "status, stand_id, stand_type, note, reason_code, reason, blocked_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                _allocation_row(run_id, method, a)
                for method, allocations in (
                    ("PRIMARY", primary_allocations),
                    ("BASELINE", baseline_allocations),
                )
                for a in allocations
            ],
        )

        conn.executemany(
            "INSERT INTO data_issues "
            "(run_id, line_number, flight_id, field, issue_code, action, "
            "original_value, new_value, explanation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    run_id,
                    issue.row_number,
                    issue.flight_id,
                    issue.field,
                    issue.issue_code,
                    issue.action,
                    issue.original_value,
                    issue.new_value,
                    issue.explanation,
                )
                for issue in data_issues
            ],
        )

        conn.executemany(
            "INSERT INTO metrics "
            "(run_id, metric_id, name, value, unit, window_text, "
            "flights_covered, definition, why_it_matters) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    run_id,
                    m.id,
                    m.name,
                    m.value,
                    m.unit,
                    m.window,
                    m.flights_covered,
                    m.definition,
                    m.why_it_matters,
                )
                for m in metrics
            ],
        )

        conn.execute(
            "UPDATE runs SET status = 'COMPLETE' WHERE run_id = ?", (run_id,)
        )

        apply_retention(conn, next_seq)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return run_id


def _allocation_row(
    run_id: str, method: str, a: Allocation
) -> tuple:
    return (
        run_id,
        method,
        a.flight_id,
        a.aircraft_size,
        a.arrival.strftime("%Y-%m-%dT%H:%M:%SZ"),
        a.departure.strftime("%Y-%m-%dT%H:%M:%SZ"),
        a.status,
        a.stand_id,
        a.stand_type,
        a.note,
        a.reason_code,
        a.reason,
        _canonical(list(a.blocked_by)),
    )


def apply_retention(conn: sqlite3.Connection, keep_seq: int) -> None:
    """Delete incomplete runs and old complete runs (section 23.45)."""
    conn.execute("DELETE FROM runs WHERE status = 'INCOMPLETE'")
    conn.execute(
        "DELETE FROM runs WHERE status = 'COMPLETE' AND seq NOT IN "
        "(SELECT seq FROM runs WHERE status = 'COMPLETE' "
        "ORDER BY seq DESC LIMIT ?)",
        (config.RUN_RETENTION,),
    )


def latest_run(conn: sqlite3.Connection) -> SavedRun | None:
    """Return the newest complete run, or None (section 23.46)."""
    row = conn.execute(
        "SELECT * FROM runs WHERE status = 'COMPLETE' ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    run_id = row["run_id"]

    stands = [
        Stand(r["stand_id"], r["stand_type"], r["max_size"])
        for r in conn.execute(
            "SELECT stand_id, stand_type, max_size FROM stands WHERE run_id = ? "
            "ORDER BY stand_id",
            (run_id,),
        )
    ]

    def load_allocations(method: str) -> list[Allocation]:
        rows = conn.execute(
            "SELECT * FROM allocations WHERE run_id = ? AND method = ? "
            "ORDER BY arrival, flight_id",
            (run_id, method),
        )
        result = []
        for r in rows:
            result.append(
                Allocation(
                    flight_id=r["flight_id"],
                    aircraft_size=r["aircraft_size"],
                    arrival=_parse(r["arrival"]),
                    departure=_parse(r["departure"]),
                    status=r["status"],
                    stand_id=r["stand_id"],
                    stand_type=r["stand_type"],
                    note=r["note"],
                    reason_code=r["reason_code"],
                    reason=r["reason"],
                    blocked_by=tuple(
                        json.loads(r["blocked_by"]) if r["blocked_by"] else []
                    ),
                )
            )
        return result

    issues = [
        DataIssue(
            row_number=r["line_number"],
            flight_id=r["flight_id"],
            field=r["field"],
            issue_code=r["issue_code"],
            action=r["action"],
            original_value=r["original_value"],
            new_value=r["new_value"],
            explanation=r["explanation"],
        )
        for r in conn.execute(
            "SELECT * FROM data_issues WHERE run_id = ? ORDER BY line_number, field",
            (run_id,),
        )
    ]

    metrics = [
        Metric(
            id=r["metric_id"],
            name=r["name"],
            value=r["value"],
            unit=r["unit"],
            window=r["window_text"],
            flights_covered=r["flights_covered"],
            definition=r["definition"],
            why_it_matters=r["why_it_matters"],
        )
        for r in conn.execute(
            "SELECT * FROM metrics WHERE run_id = ? ORDER BY metric_id",
            (run_id,),
        )
    ]

    return SavedRun(
        run_id=run_id,
        status=row["status"],
        created_at=row["created_at"],
        buffer_minutes=row["buffer_minutes"],
        allocator=row["allocator"],
        primary_method=row["primary_method"],
        solver_status=row["solver_status"],
        solve_seconds=row["solve_seconds"],
        input_hashes=json.loads(row["input_hashes"]),
        stands=tuple(stands),
        allocations=tuple(load_allocations("PRIMARY")),
        baseline_allocations=tuple(load_allocations("BASELINE")),
        data_issues=tuple(issues),
        metrics=tuple(metrics),
    )


def _parse(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
