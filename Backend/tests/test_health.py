"""The /health probe: what the uptime monitor pings."""

from app.database import get_db
from app.main import app


def test_health_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_health_reports_db_failure(client):
    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("db down")

        def close(self):
            pass

    def broken_db():
        yield BrokenSession()

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = broken_db
    try:
        res = client.get("/health")
        assert res.status_code == 503
    finally:
        app.dependency_overrides[get_db] = previous
