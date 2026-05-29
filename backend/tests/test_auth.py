import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os

# Add parent directories to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from main import app
from auth.database import Base, get_db
from auth.models import User

# Use a local temporary SQLite file for reliable testing across sessions
TEST_DB_FILE = "./test_temp.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

class TestAuthRouter(unittest.TestCase):
    def setUp(self):
        # Create all tables in memory
        print("Base metadata tables:", Base.metadata.tables.keys())
        Base.metadata.create_all(bind=engine)
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        # Clean up dependency overrides
        app.dependency_overrides.pop(get_db, None)
        # Drop all tables after test
        Base.metadata.drop_all(bind=engine)
        # Remove the file if exists
        try:
            if os.path.exists(TEST_DB_FILE):
                os.remove(TEST_DB_FILE)
        except Exception:
            pass

    def test_register_and_login(self):
        # 1. Register a user
        reg_payload = {
            "email": "testuser@example.com",
            "password": "strongpassword123",
            "name": "Test User"
        }
        res = self.client.post("/api/auth/register", json=reg_payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["user"]["email"], reg_payload["email"])
        self.assertEqual(data["user"]["name"], reg_payload["name"])
        self.assertIn("id", data["user"])

        # 2. Login with registered user
        login_payload = {
            "email": "testuser@example.com",
            "password": "strongpassword123"
        }
        res = self.client.post("/api/auth/login", json=login_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["token_type"], "bearer")

    def test_login_invalid_credentials(self):
        login_payload = {
            "email": "nonexistent@example.com",
            "password": "wrongpassword"
        }
        res = self.client.post("/api/auth/login", json=login_payload)
        self.assertEqual(res.status_code, 401)
        self.assertIn("detail", res.json())

    def test_get_profile_authenticated(self):
        # Register and login first
        reg_payload = {
            "email": "profileuser@example.com",
            "password": "password123",
            "name": "Profile User"
        }
        self.client.post("/api/auth/register", json=reg_payload)
        
        login_res = self.client.post("/api/auth/login", json={
            "email": "profileuser@example.com",
            "password": "password123"
        })
        token = login_res.json()["access_token"]

        # Call profile route
        headers = {"Authorization": f"Bearer {token}"}
        profile_res = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(profile_res.status_code, 200)
        self.assertEqual(profile_res.json()["email"], reg_payload["email"])

if __name__ == "__main__":
    unittest.main()
