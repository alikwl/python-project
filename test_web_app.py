import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import web_app

client = TestClient(web_app.app)


class TestWebApp(unittest.TestCase):
    def setUp(self):
        client.cookies.clear()

    def test_redirect_unauthenticated_to_login(self):
        # Visiting / without cookie must redirect to /login
        response = client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/login")

    def test_login_page_renders(self):
        response = client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Device Portal", response.text)
        self.assertIn("Sign In", response.text)

    def test_login_invalid_credentials(self):
        response = client.post("/login", data={"username": "admin", "password": "wrongpassword"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid username or password", response.text)

    def test_login_success_admin(self):
        response = client.post(
            "/login",
            data={"username": "admin", "password": web_app.USERS["admin"]},
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/")
        self.assertIn(web_app.COOKIE_NAME, response.cookies)

    def test_login_success_shazain(self):
        response = client.post(
            "/login",
            data={"username": "shazain", "password": web_app.USERS["shazain"]},
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(web_app.COOKIE_NAME, response.cookies)

    def test_login_success_demo(self):
        response = client.post(
            "/login",
            data={"username": "demo", "password": web_app.USERS["demo"]},
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(web_app.COOKIE_NAME, response.cookies)

    def test_authenticated_dashboard(self):
        token = web_app.create_session_token("admin")
        client.cookies.set(web_app.COOKIE_NAME, token)
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Device IMEI Checker", response.text)
        self.assertIn("admin", response.text)
        self.assertIn("Logout", response.text)

    def test_logout(self):
        token = web_app.create_session_token("admin")
        client.cookies.set(web_app.COOKIE_NAME, token)
        response = client.get("/logout", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/login")

    def test_check_single_imei_invalid(self):
        res = web_app.check_single_imei(1, "invalid_imei")
        self.assertEqual(res["status"], "invalid")
        self.assertEqual(res["activation"], "Invalid IMEI")

    @patch("web_app.Main1.get_device_info")
    @patch("web_app.Main1.get_activation_date")
    def test_check_single_imei_valid(self, mock_act, mock_info):
        mock_info.return_value = ("ok", {"imei1": "866627081977061", "imei2": "866627082977060", "model": "A36"})
        mock_act.return_value = ("ok", "2026-08-26")

        res = web_app.check_single_imei(1, "866627081977061")
        self.assertEqual(res["status"], "activated")
        self.assertEqual(res["model"], "A36")
        self.assertEqual(res["activation"], "2026-08-26")

    def test_check_stream_unauthorized(self):
        client.cookies.clear()
        response = client.post("/api/check-stream", json={"imeis": ["866627081977061"]})
        self.assertEqual(response.status_code, 401)

    @patch("web_app.check_single_imei")
    def test_check_stream_authorized(self, mock_check):
        token = web_app.create_session_token("shazain")
        client.cookies.set(web_app.COOKIE_NAME, token)
        mock_check.return_value = {
            "index": 1,
            "raw": "866627081977061",
            "imei1": "866627081977061",
            "imei2": "866627082977060",
            "model": "A36",
            "activation": "2026-08-26",
            "status": "activated"
        }
        response = client.post("/api/check-stream", json={"imeis": ["866627081977061"]})
        self.assertEqual(response.status_code, 200)
        content = response.text
        self.assertIn("data: ", content)
        self.assertIn("866627081977061", content)
        self.assertIn("[DONE]", content)


if __name__ == "__main__":
    unittest.main()
