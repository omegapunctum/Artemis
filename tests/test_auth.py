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
from app.drafts.service import Draft, init_db as init_drafts_db  # noqa: E402


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
        init_drafts_db()
        self.db = SessionLocal()
        self.db.query(Draft).delete()
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

    def _login(self, email: str, password: str) -> str:
        login = self.session.post(
            f"{self.BASE_URL}/api/auth/login",
            json={"email": email, "password": password},
            timeout=5,
        )
        self.assertEqual(login.status_code, 200)
        access_token = login.json().get("access_token")
        self.assertTrue(access_token)
        return access_token

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

    def test_drafts_extended_payload_create_and_partial_update(self):
        email = f"drafts-{uuid4().hex}@example.com"
        password = "password123"
        self._create_user(email, password)
        token = self._login(email, password)
        headers = {"Authorization": f"Bearer {token}"}

        create_payload = {
            "name_ru": "Полное имя",
            "name_en": "Full name",
            "date_start": "2024-01-01",
            "source_url": "https://example.com/source",
            "layer_type": "biography",
            "latitude": 55.7558,
            "longitude": 37.6173,
            "coordinates_confidence": "exact",
            "coordinates_source": "survey",
            "title_short": "Коротко",
            "description": "Полное описание",
            "source_license": "CC BY-SA",
            "tags": ["tag1", "tag2"],
            "image_url": "https://example.com/image.png",
            "sequence_order": 7,
            "influence_radius_km": 12.5,
            "geometry": {"type": "Point", "coordinates": [37.6173, 55.7558]},
        }
        created = self.session.post(f"{self.BASE_URL}/api/drafts", json=create_payload, headers=headers, timeout=5)
        self.assertEqual(created.status_code, 201)
        created_data = created.json()
        self.assertIn("payload", created_data)
        self.assertEqual(created_data["payload"]["name_ru"], create_payload["name_ru"])
        self.assertEqual(created_data["payload"]["source_url"], create_payload["source_url"])
        self.assertEqual(created_data["payload"]["layer_type"], create_payload["layer_type"])
        self.assertEqual(created_data["payload"]["coordinates_confidence"], create_payload["coordinates_confidence"])
        self.assertEqual(created_data["payload"]["source_license"], create_payload["source_license"])

        draft_id = created_data["id"]
        stored = self.db.query(Draft).filter(Draft.id == draft_id).first()
        self.assertIsNotNone(stored)
        self.assertEqual(stored.payload["date_start"], create_payload["date_start"])
        self.assertEqual(stored.payload["source_url"], create_payload["source_url"])
        self.assertEqual(stored.payload["title_short"], create_payload["title_short"])
        self.assertEqual(stored.payload["sequence_order"], create_payload["sequence_order"])

        update_payload = {
            "description": "Обновлённое описание",
            "title_short": "Ещё короче",
            "influence_radius_km": 20.0,
            "image_url": "https://example.com/new-image.png",
        }
        updated = self.session.put(f"{self.BASE_URL}/api/drafts/{draft_id}", json=update_payload, headers=headers, timeout=5)
        self.assertEqual(updated.status_code, 200)
        updated_data = updated.json()
        self.assertEqual(updated_data["payload"]["description"], update_payload["description"])
        self.assertEqual(updated_data["payload"]["title_short"], update_payload["title_short"])
        self.assertEqual(updated_data["payload"]["influence_radius_km"], update_payload["influence_radius_km"])
        self.assertEqual(updated_data["payload"]["date_start"], create_payload["date_start"])
        self.assertEqual(updated_data["payload"]["source_url"], create_payload["source_url"])
        self.assertEqual(updated_data["payload"]["name_en"], create_payload["name_en"])

        stored = self.db.query(Draft).filter(Draft.id == draft_id).first()
        self.db.refresh(stored)
        self.assertEqual(stored.payload["name_ru"], create_payload["name_ru"])
        self.assertEqual(stored.payload["image_url"], update_payload["image_url"])
        self.assertEqual(stored.payload["tags"], create_payload["tags"])

        forbidden = self.session.post(
            f"{self.BASE_URL}/api/drafts",
            json={**create_payload, "status": "review"},
            headers=headers,
            timeout=5,
        )
        self.assertEqual(forbidden.status_code, 422)


if __name__ == "__main__":
    unittest.main()
