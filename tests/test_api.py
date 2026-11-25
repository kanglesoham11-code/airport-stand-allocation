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
