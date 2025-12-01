from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_create_admin():
    response = client.post("/admin/", json={"name": "Test Admin", "description": "A admin for testing"})
    assert response.status_code == 200
    assert response.json()["name"] == "Test Admin"

def test_read_admin():
    response = client.post("/admin/", json={"name": "Test Admin", "description": "A admin for testing"})
    item_id = response.json()["id"]
    response = client.get(f"/admin/{item_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Test Admin"

def test_update_admin():
    response = client.post("/admin/", json={"name": "Test Admin", "description": "A admin for testing"})
    item_id = response.json()["id"]
    response = client.put(f"/admin/{item_id}", json={"name": "Updated Admin", "description": "Updated description"})
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Admin"

def test_delete_admin():
    response = client.post("/admin/", json={"name": "Test Admin", "description": "A admin for testing"})
    item_id = response.json()["id"]
    response = client.delete(f"/admin/{item_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Test Admin"
