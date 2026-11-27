"""Tests for the API (section 12.4)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from stand_allocation.api import app

API_KEY = "testkey01234567890123456789012345678901"
HEADERS = {"X-API-Key": API_KEY}

client = TestClient(app)


def test_unknown_query_parameter_422() -> None:
    response = client.get("/allocations?foo=bar", headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_bad_content_length_400() -> None:
    response = client.get(
        "/allocations", headers={**HEADERS, "Content-Length": "abc"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_unknown_path_404() -> None:
    response = client.get("/no-such-path", headers=HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_health_no_key() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_allocations_requires_key() -> None:
    response = client.get("/allocations")
    assert response.status_code == 401


def test_allocations_shape() -> None:
    response = client.get("/allocations", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) >= {
        "planning_window",
        "run_id",
        "allocator",
        "primary_method",
        "solver_status",
        "total",
        "limit",
        "offset",
        "allocations",
    }
    assert body["total"] == len(body["allocations"]) or body["total"] >= 0
    assert response.headers["x-request-id"]


def test_served_from_memory_without_db_read(monkeypatch) -> None:
    from stand_allocation import service

    def _fail() -> None:
        raise AssertionError("get_latest_run should not be called per request")

    monkeypatch.setattr(service, "get_latest_run", _fail)
    assert client.get("/ready").status_code == 200
    assert client.get("/allocations", headers=HEADERS).status_code == 200
    assert client.get("/stands", headers=HEADERS).status_code == 200
    assert client.get("/metrics", headers=HEADERS).status_code == 200
    assert client.get("/data-issues", headers=HEADERS).status_code == 200
    assert client.get("/ops/stats", headers=HEADERS).status_code == 200


def test_openapi_has_literal_enums() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schemas_json = response.json()["components"]["schemas"]
    assert schemas_json["AllocationOut"]["properties"]["aircraft_size"]["enum"] == [
        "S",
        "M",
        "L",
    ]
    assert schemas_json["StandOut"]["properties"]["stand_type"]["enum"] == [
        "PLB",
        "REMOTE",
    ]


def test_frontend_served_without_key() -> None:
    index = client.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    assert "Aleph Stand Allocation" in index.text

    css = client.get("/static/styles.css")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]

    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]


def test_etag_304_and_security_rate_headers() -> None:
    first = client.get("/allocations", headers=HEADERS)
    assert first.status_code == 200
    etag = first.headers.get("etag")
    assert etag
    assert first.headers.get("x-frame-options") == "DENY"
    assert first.headers.get("x-content-type-options") == "nosniff"
    assert first.headers.get("referrer-policy") == "no-referrer"
    assert int(first.headers["x-ratelimit-limit"]) > 0
    assert int(first.headers["x-ratelimit-remaining"]) >= 0

    second = client.get(
        "/allocations", headers={**HEADERS, "If-None-Match": etag}
    )
    assert second.status_code == 304
    assert second.headers.get("etag") == etag


def test_ready_and_allocations_expose_buffer_and_solve_time() -> None:
    ready = client.get("/ready")
    assert ready.status_code == 200
    ready_json = ready.json()
    assert isinstance(ready_json["buffer_minutes"], int)
    assert isinstance(ready_json["solve_seconds"], (int, float))

    alloc = client.get("/allocations", headers=HEADERS)
    assert alloc.status_code == 200
    assert alloc.json()["buffer_minutes"] == ready_json["buffer_minutes"]


def test_structured_access_log_emits_fields_without_secret(caplog) -> None:
    import json
    import logging

    from stand_allocation.logging_setup import _JsonFormatter

    with caplog.at_level(logging.INFO, logger="stand_allocation.access"):
        res = client.get("/stands/C01", headers=HEADERS)
    assert res.status_code == 200

    access_records = [r for r in caplog.records if r.name == "stand_allocation.access"]
    assert access_records
    line = _JsonFormatter().format(access_records[-1])
    payload = json.loads(line)
    assert payload["method"] == "GET"
    assert payload["path"] == "/stands/C01"
    assert payload["route"] == "/stands/{stand_id}"
    assert payload["status"] == 200
    assert payload["status_class"] == "2xx"
    assert "duration_ms" in payload
    assert len(payload["key_fingerprint"]) == 8
    assert API_KEY not in line
