from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_leaderboard_requires_authentication():
    response = client.get("/users/leaderboard")

    assert response.status_code == 401
