import os
import subprocess
import time
import unittest
from pathlib import Path
from uuid import uuid4

import requests

DB_PATH = Path("artemis_auth.db")
if DB_PATH.exists():
    DB_PATH.unlink()

os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-auth-api")
os.environ.setdefault("COOKIE_HTTPONLY", "true")
os.environ.setdefault("COOKIE_SAMESITE", "lax")
os.environ.setdefault("APP_ENV", "development")

from app.auth.service import SessionLocal, User, active_refresh_tokens, init_db  # noqa: E402
from app.auth.utils import hash_password  # noqa: E402


class AuthApiTests(unittest.TestCase):
    SERVER_PORT = 8012
    BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"

    @classmethod
    def setUpClass(cls):
        env = os.environ.copy()
        cls.server = subprocess.Popen(
            [
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(cls.SERVER_PORT),
                "--log-level",
                "warning",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            try:
                response = requests.get(f"{cls.BASE_URL}/api/health", timeout=0.5)
                if response.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("Failed to start test server")

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=5)

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.db.query(User).delete()
        self.db.commit()
        active_refresh_tokens.clear()
        self.session = requests.Session()

    def tearDown(self):
        self.db.close()
        active_refresh_tokens.clear()
        self.session.close()

    def _create_user(self, email: str, password: str) -> None:
        user = User(email=email, password_hash=hash_password(password), is_admin=False)
        self.db.add(user)
        self.db.commit()

    def test_auth_flow_and_routes(self):
        email = f"auth-{uuid4().hex}@example.com"
        password = "password123"
        self._create_user(email, password)

        health = self.session.get(f"{self.BASE_URL}/api/health", timeout=5)
        self.assertEqual(health.status_code, 200)

        me_unauthorized = self.session.get(f"{self.BASE_URL}/api/me", timeout=5)
        self.assertEqual(me_unauthorized.status_code, 401)

        me_route_exists = self.session.options(f"{self.BASE_URL}/api/me", timeout=5)
        self.assertNotEqual(me_route_exists.status_code, 404)

        login_route_exists = self.session.post(f"{self.BASE_URL}/api/auth/login", json={}, timeout=5)
        self.assertNotEqual(login_route_exists.status_code, 404)

        login = self.session.post(
            f"{self.BASE_URL}/api/auth/login",
            json={"email": email, "password": password},
            timeout=5,
        )
        self.assertEqual(login.status_code, 200)
        access_token = login.json().get("access_token")
        self.assertTrue(access_token)

        self.assertIn("refresh_token", self.session.cookies)

        refresh = self.session.post(f"{self.BASE_URL}/api/auth/refresh", timeout=5)
        self.assertEqual(refresh.status_code, 200)
        refreshed_token = refresh.json().get("access_token")
        self.assertTrue(refreshed_token)
        self.assertNotEqual(refreshed_token, access_token)

        me_authorized = self.session.get(
            f"{self.BASE_URL}/api/me",
            headers={"Authorization": f"Bearer {refreshed_token}"},
            timeout=5,
        )
        self.assertEqual(me_authorized.status_code, 200)

        logout = self.session.post(f"{self.BASE_URL}/api/auth/logout", timeout=5)
        self.assertEqual(logout.status_code, 200)
        set_cookie = logout.headers.get("set-cookie", "").lower()
        self.assertIn("refresh_token=", set_cookie)
        self.assertIn("max-age=0", set_cookie)


if __name__ == "__main__":
    unittest.main()
