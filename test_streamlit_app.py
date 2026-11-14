import unittest
from unittest.mock import patch
import streamlit_app


class TestStreamlitApp(unittest.TestCase):
    def test_check_auth(self):
        self.assertEqual(streamlit_app.check_auth("admin", "admin@2026"), "admin")
        self.assertEqual(streamlit_app.check_auth("shazain", "shazain@2026"), "shazain")
        self.assertEqual(streamlit_app.check_auth("demo", "demo@2026"), "demo")
        self.assertIsNone(streamlit_app.check_auth("admin", "wrongpassword"))
        self.assertIsNone(streamlit_app.check_auth("unknown", "any"))

    def test_check_single_imei_live_invalid(self):
        res = streamlit_app.check_single_imei_live(1, "bad_imei")
        self.assertEqual(res["#"], 1)
        self.assertEqual(res["Status"], "Invalid")
        self.assertEqual(res["Activation Date"], "Invalid IMEI")

    @patch("streamlit_app.Main1.get_device_info")
    @patch("streamlit_app.Main1.get_activation_date")
    def test_check_single_imei_live_valid(self, mock_act, mock_info):
        mock_info.return_value = ("ok", {"imei1": "866627081977061", "imei2": "866627082977060", "model": "A36"})
        mock_act.return_value = ("ok", "2026-08-26")

        res = streamlit_app.check_single_imei_live(1, "866627081977061")
        self.assertEqual(res["#"], 1)
        self.assertEqual(res["Status"], "Activated")
        self.assertEqual(res["Model"], "A36")
        self.assertEqual(res["Activation Date"], "2026-08-26")

    @patch("streamlit_app.Main1.get_device_info")
    @patch("streamlit_app.Main1.get_activation_date")
    def test_check_single_imei_live_not_activated(self, mock_act, mock_info):
        mock_info.return_value = ("ok", {"imei1": "866627081977061", "imei2": "866627082977060", "model": "A36"})
        mock_act.return_value = ("none", None)

        res = streamlit_app.check_single_imei_live(1, "866627081977061")
        self.assertEqual(res["#"], 1)
        self.assertEqual(res["Status"], "Not Activated")
        self.assertEqual(res["Activation Date"], "Not activated")

    @patch("streamlit_app.Main1.get_device_info")
    @patch("streamlit_app.Main1.get_activation_date")
    def test_check_single_imei_live_not_found(self, mock_act, mock_info):
        mock_info.return_value = ("notfound", "Not found")
        mock_act.return_value = ("none", None)

        res = streamlit_app.check_single_imei_live(2, "866627081977061")
        self.assertEqual(res["#"], 2)
        self.assertEqual(res["Model"], "Not found")
        self.assertEqual(res["Status"], "Not Activated")

    @patch("streamlit_app.Main1.get_device_info")
    @patch("streamlit_app.Main1.get_activation_date")
    def test_check_single_imei_live_error(self, mock_act, mock_info):
        mock_info.return_value = ("error", "HTTP 500")
        mock_act.return_value = ("error", "HTTP 500")

        res = streamlit_app.check_single_imei_live(3, "866627081977061")
        self.assertEqual(res["#"], 3)
        self.assertEqual(res["Status"], "Error")
        self.assertIn("Error:", res["Activation Date"])


if __name__ == "__main__":
    unittest.main()
