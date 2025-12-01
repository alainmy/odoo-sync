from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_login():
    response = client.post("/token", data={"username": "testuser", "password": "testpassword"})
    assert response.status_code == 200
    assert "access_token" in response.json()

def test_get_current_user():
    response = client.post("/token", data={"username": "testuser", "password": "testpassword"})
    token = response.json()["access_token"]
    response = client.get("/users/me/", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["username"] == "testuser"
