import unittest
from unittest.mock import MagicMock, patch
import requests
from gspread.exceptions import APIError
import Main1


class TestMain1(unittest.TestCase):
    def test_luhn_checksum(self):
        # 86662708197706 should have check digit 1 -> 866627081977061
        self.assertEqual(Main1.luhn_checksum("86662708197706"), "1")
        # 86248408246685 should have check digit 8 -> 862484082466858
        self.assertEqual(Main1.luhn_checksum("86248408246685"), "8")

    def test_clean_imei(self):
        # Standard 15 digits
        self.assertEqual(Main1.clean_imei("866627081977061"), "866627081977061")
        # Unformatted integer from Google Sheets
        self.assertEqual(Main1.clean_imei(866627081977061), "866627081977061")
        # Float
        self.assertEqual(Main1.clean_imei(866627081977061.0), "866627081977061")
        # Float string with .0
        self.assertEqual(Main1.clean_imei("866627081977061.0"), "866627081977061")
        # Scientific notation string with precision
        self.assertEqual(Main1.clean_imei("8.66627081977061E+14"), "866627081977061")
        # 14 digits (TAC + SNR) auto-completing Luhn check digit
        self.assertEqual(Main1.clean_imei("86662708197706"), "866627081977061")
        # 16 digits IMEISV
        self.assertEqual(Main1.clean_imei("8666270819770610"), "866627081977061")
        # Punctuation and whitespace
        self.assertEqual(Main1.clean_imei("  86-662708-197706-1 \n"), "866627081977061")
        # Invalid inputs
        self.assertIsNone(Main1.clean_imei("invalid"))
        self.assertIsNone(Main1.clean_imei("123"))
        self.assertIsNone(Main1.clean_imei(""))
        self.assertIsNone(Main1.clean_imei(None))

    def test_is_retry_value(self):
        # Error strings
        self.assertTrue(Main1.is_retry_value("Error: activation: HTTP 404"))
        self.assertTrue(Main1.is_retry_value("Error: info: HTTP 500"))
        self.assertTrue(Main1.is_retry_value("Error"))
        # Model Not found
        self.assertTrue(Main1.is_retry_value("Not activated", "Not found"))
        self.assertTrue(Main1.is_retry_value("Not found", ""))
        # Normal finished rows
        self.assertFalse(Main1.is_retry_value("2026-08-26", "A36"))
        self.assertFalse(Main1.is_retry_value("Not activated", "A36"))
        self.assertFalse(Main1.is_retry_value("", "A36"))

    @patch("Main1.time.sleep")
    def test_sheet_call_retry(self, mock_sleep):
        fn = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": {"code": 429, "message": "rate limit"}}
        mock_resp.status_code = 429
        mock_resp.text = "rate limit"
        api_error = APIError(mock_resp)

        # Fail twice with 429, then succeed
        fn.side_effect = [api_error, requests.RequestException("connection drop"), "success"]
        res = Main1.sheet_call(fn, "arg1")
        self.assertEqual(res, "success")
        self.assertEqual(fn.call_count, 3)

    @patch("Main1.time.sleep")
    def test_sheet_call_exhaustion(self, mock_sleep):
        fn = MagicMock(side_effect=requests.RequestException("persistent down"))
        with self.assertRaises(RuntimeError):
            Main1.sheet_call(fn)

    @patch("Main1.http.request")
    @patch("Main1.time.sleep")
    def test_request_json(self, mock_sleep, mock_http):
        # Success 200 JSON
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True}
        mock_http.return_value = mock_resp
        body, err = Main1.request_json("GET", "http://test")
        self.assertEqual(body, {"success": True})
        self.assertIsNone(err)

        # 200 non-JSON retry then success
        bad_resp = MagicMock()
        bad_resp.status_code = 200
        bad_resp.json.side_effect = ValueError("Not JSON")
        mock_http.side_effect = [bad_resp, mock_resp]
        body, err = Main1.request_json("GET", "http://test")
        self.assertEqual(body, {"success": True})

        # 404 returns HTTP 404 immediately
        r404 = MagicMock()
        r404.status_code = 404
        mock_http.side_effect = None
        mock_http.return_value = r404
        body, err = Main1.request_json("GET", "http://test")
        self.assertEqual(err, "HTTP 404")

        # 500 retries
        r500 = MagicMock()
        r500.status_code = 500
        mock_http.return_value = r500
        body, err = Main1.request_json("GET", "http://test")
        self.assertEqual(err, "HTTP 500")

    @patch("Main1.request_json")
    def test_get_device_info(self, mock_request):
        # Successful response
        mock_request.return_value = ({
            "errorCode": 0,
            "errorMessage": "",
            "success": True,
            "results": {
                "imei": "866627081977061",
                "meid": "866627082977060",
                "model": "A36"
            }
        }, None)
        status, info = Main1.get_device_info("866627081977061")
        self.assertEqual(status, "ok")
        self.assertEqual(info["model"], "A36")
        self.assertEqual(info["imei1"], "866627081977061")
        self.assertEqual(info["imei2"], "866627082977060")

        # Not found (404)
        mock_request.return_value = ({
            "errorCode": 404,
            "errorMessage": "Product Auth Not Found",
            "success": False,
            "results": ""
        }, None)
        status, info = Main1.get_device_info("000000000000000")
        self.assertEqual(status, "notfound")
        self.assertIsNone(info)

        # Server error (500) - must NOT be marked as notfound
        mock_request.return_value = ({
            "errorCode": 500,
            "errorMessage": "Server busy",
            "success": False,
            "results": ""
        }, None)
        status, reason = Main1.get_device_info("866627081977061")
        self.assertEqual(status, "error")
        self.assertIn("500", reason)

        # Request error
        mock_request.return_value = (None, "network down")
        status, reason = Main1.get_device_info("866627081977061")
        self.assertEqual(status, "error")

    @patch("Main1.request_json")
    def test_get_activation_date(self, mock_request):
        # Successful activation date
        mock_request.return_value = ({
            "code": 800,
            "message": "success",
            "data": {"begin": "2026-08-26 12:00:00"}
        }, None)
        status, date = Main1.get_activation_date("866627081977061")
        self.assertEqual(status, "ok")
        self.assertEqual(date, "2026-08-26")

        # Not activated (code 801)
        mock_request.return_value = ({
            "code": 801,
            "message": "fotatime null or before outstoretime",
            "data": None
        }, None)
        status, date = Main1.get_activation_date("866627081976519")
        self.assertEqual(status, "none")
        self.assertIsNone(date)

        # HTTP 404 (e.g. Model Z2577 where no certificate exists in CRM)
        mock_request.return_value = (None, "HTTP 404")
        status, date = Main1.get_activation_date("862484082466858")
        self.assertEqual(status, "none")
        self.assertIsNone(date)

        # Transient server error
        mock_request.return_value = (None, "HTTP 502")
        status, reason = Main1.get_activation_date("866627081977061")
        self.assertEqual(status, "error")
        self.assertIn("502", reason)

        # Unexpected code error
        mock_request.return_value = ({"code": 999, "message": "Unknown error"}, None)
        status, reason = Main1.get_activation_date("866627081977061")
        self.assertEqual(status, "error")
        self.assertIn("999", reason)

    def test_find_pending(self):
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = [
            ["imei", "IMEI1", "IMEI2", "model", "Activation Date"],
            ["866627081977061", "866627081977061", "866627082977060", "A36", "2026-08-26"], # Row 2: done
            ["866627081976519", "866627081976519", "866627082976518", "A36", "Not activated"], # Row 3: done
            ["862484082466858", "", "", "", "Error: activation: HTTP 404"], # Row 4: retry error
            ["866627081850367", "", "", "", ""], # Row 5: pending blank
            ["866627081850680", "", "", "", "Invalid IMEI"], # Row 6: corrected to valid IMEI
            ["bad_imei", "", "", "", "Invalid IMEI"], # Row 7: still invalid IMEI
        ]

        rechecked = set()
        pending = Main1.find_pending(mock_ws, rechecked)

        self.assertEqual(len(pending), 3)
        self.assertEqual(pending[0], (4, "862484082466858"))
        self.assertEqual(pending[1], (5, "866627081850367"))
        self.assertEqual(pending[2], (6, "866627081850680"))

        rechecked.add((4, "862484082466858"))
        pending2 = Main1.find_pending(mock_ws, rechecked)
        self.assertEqual(len(pending2), 2)
        self.assertEqual(pending2[0], (5, "866627081850367"))
        self.assertEqual(pending2[1], (6, "866627081850680"))

    @patch("Main1.get_device_info")
    @patch("Main1.get_activation_date")
    def test_process_row_success(self, mock_act, mock_info):
        mock_ws = MagicMock()
        mock_info.return_value = ("ok", {"imei1": "866627081977061", "imei2": "866627082977060", "model": "A36"})
        mock_act.return_value = ("ok", "2026-08-26")

        fails = {}
        rechecked = set()
        cache = {}

        Main1.process_row(mock_ws, 2, "866627081977061", fails, rechecked, cache)

        self.assertIn((2, "866627081977061"), rechecked)
        self.assertEqual(fails, {})
        mock_ws.update.assert_called_with(
            values=[["866627081977061", "866627082977060", "A36", "2026-08-26"]],
            range_name="B2:E2"
        )
        # Check cache
        self.assertEqual(cache["info:866627081977061"]["model"], "A36")
        self.assertEqual(cache["act:866627081977061"], "2026-08-26")

    @patch("Main1.get_device_info")
    @patch("Main1.get_activation_date")
    def test_process_row_max_attempts(self, mock_act, mock_info):
        mock_ws = MagicMock()
        mock_info.return_value = ("error", "HTTP 500")
        mock_act.return_value = ("error", "skipped")

        fails = {(2, "866627081977061"): 2} # Attempt 3
        rechecked = set()
        cache = {}

        Main1.process_row(mock_ws, 2, "866627081977061", fails, rechecked, cache)

        self.assertIn((2, "866627081977061"), rechecked)
        self.assertNotIn((2, "866627081977061"), fails)
        mock_ws.update.assert_called_with(
            values=[["", "", "", "Error: HTTP 500"]],
            range_name="B2:E2"
        )

    def test_process_row_invalid_imei(self):
        mock_ws = MagicMock()

        fails = {}
        rechecked = set()
        cache = {}

        Main1.process_row(mock_ws, 5, "not_an_imei", fails, rechecked, cache)

        self.assertIn((5, "not_an_imei"), rechecked)
        mock_ws.update.assert_called_with(
            values=[["", "", "", "Invalid IMEI"]],
            range_name="B5:E5"
        )

    @patch("Main1.gspread.service_account")
    @patch("Main1.time.sleep")
    @patch("Main1.process_row")
    @patch("Main1.find_pending")
    def test_main_one_iteration(self, mock_pending, mock_process, mock_sleep, mock_sa):
        mock_gc = MagicMock()
        mock_sh = MagicMock()
        mock_ws = MagicMock()
        mock_sa.return_value = mock_gc
        mock_gc.open_by_url.return_value = mock_sh
        mock_sh.sheet1 = mock_ws
        mock_ws.row_values.return_value = ["imei", "IMEI1", "IMEI2", "model", "Activation Date"]

        # 1 pending item, then break loop via KeyboardInterrupt
        mock_pending.side_effect = [[(2, "866627081977061")], KeyboardInterrupt]

        Main1.main()

        mock_process.assert_called_once()


if __name__ == "__main__":
    unittest.main()
