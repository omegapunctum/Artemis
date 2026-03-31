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

os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-for-integration")
os.environ.setdefault("COOKIE_HTTPONLY", "true")
os.environ.setdefault("COOKIE_SAMESITE", "lax")
os.environ.setdefault("APP_ENV", "development")

from app.auth.service import SessionLocal, User, active_refresh_tokens, init_db  # noqa: E402


class AuthIntegrationTests(unittest.TestCase):
    SERVER_PORT = 8011
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

    def _create_user_and_login(self) -> tuple[str, dict]:
        email = f"user-{uuid4().hex}@example.com"
        password = "password123"
        register = self.session.post(f"{self.BASE_URL}/api/auth/register", json={"email": email, "password": password}, timeout=5)
        self.assertEqual(register.status_code, 201)
        login = self.session.post(f"{self.BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=5)
        self.assertEqual(login.status_code, 200)
        self.assertIn("refresh_token", self.session.cookies)
        return login.json()["access_token"], {"email": email, "password": password}

    def test_health_endpoint(self):
        response = self.session.get(f"{self.BASE_URL}/api/health", timeout=5)
        self.assertEqual(response.status_code, 200)
        self.assertIn("counts", response.json())

    def test_refresh_rotates_access_token(self):
        access_token, _ = self._create_user_and_login()
        refresh = self.session.post(f"{self.BASE_URL}/api/auth/refresh", timeout=5)
        self.assertEqual(refresh.status_code, 200)
        new_access_token = refresh.json().get("access_token")
        self.assertTrue(new_access_token)
        self.assertNotEqual(access_token, new_access_token)

    def test_logout_clears_cookie(self):
        self._create_user_and_login()
        response = self.session.post(f"{self.BASE_URL}/api/auth/logout", timeout=5)
        self.assertEqual(response.status_code, 200)
        set_cookie = response.headers.get("set-cookie", "").lower()
        self.assertIn("refresh_token=", set_cookie)
        self.assertIn("max-age=0", set_cookie)
        self.assertIn("httponly", set_cookie)
        self.assertIn("samesite=lax", set_cookie)

    def test_me_requires_valid_access_token(self):
        access_token, _ = self._create_user_and_login()
        unauthorized = self.session.get(f"{self.BASE_URL}/api/me", timeout=5)
        self.assertEqual(unauthorized.status_code, 401)

        valid = self.session.get(f"{self.BASE_URL}/api/me", headers={"Authorization": f"Bearer {access_token}"}, timeout=5)
        self.assertEqual(valid.status_code, 200)
        payload = valid.json()
        self.assertIn("id", payload)
        self.assertIn("email", payload)
        self.assertIn("is_admin", payload)

    def test_draft_endpoints_reject_system_fields_and_allow_valid_payloads(self):
        access_token, _ = self._create_user_and_login()
        headers = {"Authorization": f"Bearer {access_token}"}

        valid_create_payload = {
            "name_ru": "Черновик",
            "date_start": "2026-01-01",
            "source_url": "https://example.com/source",
            "description": "Описание",
        }

        for forbidden_field in ("etl_status", "status", "published_from_draft_id"):
            payload = {**valid_create_payload, forbidden_field: "forbidden"}
            response = self.session.post(f"{self.BASE_URL}/api/drafts", headers=headers, json=payload, timeout=5)
            self.assertEqual(response.status_code, 422)

        create_response = self.session.post(
            f"{self.BASE_URL}/api/drafts",
            headers=headers,
            json=valid_create_payload,
            timeout=5,
        )
        self.assertEqual(create_response.status_code, 201)
        draft_id = create_response.json()["id"]

        for forbidden_field in ("status", "created_at", "updated_at"):
            payload = {"description": "Новое описание", forbidden_field: "forbidden"}
            response = self.session.put(
                f"{self.BASE_URL}/api/drafts/{draft_id}",
                headers=headers,
                json=payload,
                timeout=5,
            )
            self.assertEqual(response.status_code, 422)

        valid_update_response = self.session.put(
            f"{self.BASE_URL}/api/drafts/{draft_id}",
            headers=headers,
            json={"description": "Обновленное описание"},
            timeout=5,
        )
        self.assertEqual(valid_update_response.status_code, 200)
        self.assertEqual(valid_update_response.json()["description"], "Обновленное описание")

    def test_draft_endpoints_ugc_validation_edge_cases(self):
        access_token, _ = self._create_user_and_login()
        headers = {"Authorization": f"Bearer {access_token}"}

        valid_create_payload = {
            "name_ru": "Черновик",
            "date_start": "2026-01-01",
            "source_url": "https://example.com/source",
            "description": "Описание",
            "layer_type": "biography",
            "coordinates_confidence": "exact",
            "source_license": "CC BY-SA",
        }

        invalid_create = self.session.post(
            f"{self.BASE_URL}/api/drafts",
            headers=headers,
            json={**valid_create_payload, "source_license": "INVALID"},
            timeout=5,
        )
        self.assertEqual(invalid_create.status_code, 422)

        # Forbidden system fields on create
        forbidden_create = self.session.post(
            f"{self.BASE_URL}/api/drafts",
            headers=headers,
            json={**valid_create_payload, "status": "forbidden"},
            timeout=5,
        )
        self.assertEqual(forbidden_create.status_code, 422)

        create_response = self.session.post(
            f"{self.BASE_URL}/api/drafts",
            headers=headers,
            json=valid_create_payload,
            timeout=5,
        )
        self.assertEqual(create_response.status_code, 201)
        draft_id = create_response.json()["id"]

        invalid_update = self.session.put(
            f"{self.BASE_URL}/api/drafts/{draft_id}",
            headers=headers,
            json={"latitude": 55.7},
            timeout=5,
        )
        self.assertEqual(invalid_update.status_code, 422)

        valid_update = self.session.put(
            f"{self.BASE_URL}/api/drafts/{draft_id}",
            headers=headers,
            json={
                "description": "Валидное обновление",
                "latitude": 55.7,
                "longitude": 37.6,
            },
            timeout=5,
        )
        self.assertEqual(valid_update.status_code, 200)
        self.assertEqual(valid_update.json()["description"], "Валидное обновление")

    def test_draft_create_update_endpoint_validation_matrix(self):
        access_token, _ = self._create_user_and_login()
        headers = {"Authorization": f"Bearer {access_token}"}

        valid_create_payload = {
            "name_ru": "Черновик API",
            "date_start": "2026-01-01",
            "source_url": "https://example.com/source",
            "description": "Описание",
            "layer_type": "biography",
            "coordinates_confidence": "exact",
            "source_license": "CC BY-SA",
        }

        # Create: valid payload -> success
        create_ok = self.session.post(
            f"{self.BASE_URL}/api/drafts",
            headers=headers,
            json=valid_create_payload,
            timeout=5,
        )
        self.assertEqual(create_ok.status_code, 201)
        draft_id = create_ok.json()["id"]

        # Create: required, date/url/enum/forbidden validations
        create_missing_name_ru = self.session.post(
            f"{self.BASE_URL}/api/drafts",
            headers=headers,
            json={k: v for k, v in valid_create_payload.items() if k != "name_ru"},
            timeout=5,
        )
        self.assertEqual(create_missing_name_ru.status_code, 422)

        create_invalid_date = self.session.post(
            f"{self.BASE_URL}/api/drafts",
            headers=headers,
            json={**valid_create_payload, "date_start": "2026/01/01"},
            timeout=5,
        )
        self.assertEqual(create_invalid_date.status_code, 422)

        create_invalid_source_url = self.session.post(
            f"{self.BASE_URL}/api/drafts",
            headers=headers,
            json={**valid_create_payload, "source_url": "not-url"},
            timeout=5,
        )
        self.assertEqual(create_invalid_source_url.status_code, 422)

        create_invalid_enum = self.session.post(
            f"{self.BASE_URL}/api/drafts",
            headers=headers,
            json={**valid_create_payload, "layer_type": "invalid-enum"},
            timeout=5,
        )
        self.assertEqual(create_invalid_enum.status_code, 422)

        for forbidden_field in ("etl_status", "status"):
            create_forbidden = self.session.post(
                f"{self.BASE_URL}/api/drafts",
                headers=headers,
                json={**valid_create_payload, forbidden_field: "forbidden"},
                timeout=5,
            )
            self.assertEqual(create_forbidden.status_code, 422)

        # Update: valid payload -> success
        update_ok = self.session.put(
            f"{self.BASE_URL}/api/drafts/{draft_id}",
            headers=headers,
            json={"description": "Обновлено через API"},
            timeout=5,
        )
        self.assertEqual(update_ok.status_code, 200)
        self.assertEqual(update_ok.json()["description"], "Обновлено через API")

        # Update: forbidden/enum/coordinates validations
        update_forbidden_status = self.session.put(
            f"{self.BASE_URL}/api/drafts/{draft_id}",
            headers=headers,
            json={"status": "review"},
            timeout=5,
        )
        self.assertEqual(update_forbidden_status.status_code, 422)

        update_invalid_enum = self.session.put(
            f"{self.BASE_URL}/api/drafts/{draft_id}",
            headers=headers,
            json={"source_license": "INVALID"},
            timeout=5,
        )
        self.assertEqual(update_invalid_enum.status_code, 422)

        update_invalid_coordinates = self.session.put(
            f"{self.BASE_URL}/api/drafts/{draft_id}",
            headers=headers,
            json={"latitude": 55.7},
            timeout=5,
        )
        self.assertEqual(update_invalid_coordinates.status_code, 422)


if __name__ == "__main__":
    unittest.main()
