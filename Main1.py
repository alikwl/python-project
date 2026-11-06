"""
ZTE checker with watch mode -> Google Sheets.

Leave it running: every POLL_SECONDS it re-reads the sheet and processes any row
that has an IMEI in column A but nothing in column E (or needs retry). Press Ctrl+C to stop.

Sheet layout:
    A: your input IMEI   B: IMEI1   C: IMEI2   D: model   E: Activation Date

Values in column E:
    YYYY-MM-DD              activation date found
    Not activated           device has no activation record / not activated yet
    Invalid IMEI            cell cannot be resolved to a valid 15-digit IMEI
    Error: ...              failed MAX_ATTEMPTS times; reason is recorded in cell
Delete a cell in column E (or add its text to RETRY_VALUES) to have that row re-checked.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor
import requests
from requests.adapters import HTTPAdapter
import gspread
from gspread.exceptions import APIError, GSpreadException
from google.auth.exceptions import GoogleAuthError, TransportError

# ---------- CONFIG ----------
import os
SHEET_URL = os.environ.get("GOOGLE_SHEET_URL", "https://docs.google.com/spreadsheets/d/16_cF2eD2oht8ckH7GKkQSkj8yT_GFJ3V7UK-8CtHKIo/edit?pli=1&gid=0#gid=0")
WORKSHEET = os.environ.get("GOOGLE_WORKSHEET", None)   # tab name, or None for the first tab
KEY_FILE = os.environ.get("GOOGLE_KEY_FILE", "service_account.json")
POLL_SECONDS = 30                     # how often to look for new entries
DELAY = 1.0                           # seconds between IMEIs
RETRIES = 3                           # HTTP retries per request
MAX_ATTEMPTS = 3                      # row-level attempts before writing "Error: ..."
# Existing cell values that should be re-checked once each time the script starts
RETRY_VALUES = {"Not found", "Error"}
# ----------------------------

INFO_API = "https://www.ztedevices.com/bin/product/auth/query"
ACTIVATION_API = "https://shouhou-en.ztems.com/crm/app/certificateInfo"
HEADERS = ["IMEI1", "IMEI2", "model", "Activation Date"]   # columns B to E

# Configure requests session with pooled connections
http = requests.Session()
adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=1)
http.mount("https://", adapter)
http.mount("http://", adapter)
http.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
})


# ---------- Google Sheets helpers ----------
def sheet_call(fn, *args, **kwargs):
    """Run a gspread call, retrying on quota/server/network errors."""
    for attempt in range(1, 6):
        try:
            return fn(*args, **kwargs)
        except APIError as e:
            status = getattr(e, "code", None) or getattr(getattr(e, "response", None), "status_code", None)
            if status in (408, 429, 500, 502, 503, 504):
                wait = 15 * attempt
                print(f"  Google Sheets busy (HTTP {status}), waiting {wait}s...")
                time.sleep(wait)
                continue
            raise
        except (requests.RequestException, GoogleAuthError, TransportError, GSpreadException) as e:
            wait = 5 * attempt
            print(f"  Network/Auth problem talking to Google ({type(e).__name__}: {e}), retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError("Google Sheets kept failing after 5 attempts")


# ---------- IMEI & Retry helpers ----------
def luhn_checksum(digits14):
    """Calculate the 15th Luhn check digit for a 14-digit IMEI."""
    total = 0
    for i, d in enumerate(digits14):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return str((10 - (total % 10)) % 10)


def clean_imei(raw):
    """
    Returns a valid 15-digit IMEI string, or None if raw cannot be resolved to a 15-digit IMEI.
    Handles:
      - integers and floats from unformatted sheet values
      - scientific notation strings (e.g. '8.66627081977061E+14')
      - float strings with decimals (e.g. '866627081977061.0')
      - strings with spaces, hyphens, prefixes
      - 14-digit IMEIs (auto-calculates Luhn check digit)
      - 16-digit IMEISVs (extracts 14 digits + Luhn check digit)
    """
    if raw is None:
        return None

    if isinstance(raw, (int, float)):
        try:
            val = round(raw)
            raw = str(val)
        except (ValueError, OverflowError):
            raw = str(raw)
    else:
        raw = str(raw).strip()

    if not raw:
        return None

    # Handle scientific notation in string (e.g. "8.66627081977061E+14")
    if "e" in raw.lower():
        try:
            f_val = float(raw)
            if 1e14 <= f_val < 1e15:
                raw = f"{int(round(f_val)):015d}"
        except (ValueError, OverflowError):
            pass

    # Handle float string like "866627081977061.0"
    if "." in raw:
        parts = raw.split(".")
        if len(parts) == 2 and re.sub(r"\D", "", parts[1]) == "0" * len(re.sub(r"\D", "", parts[1])):
            raw = parts[0]

    # Extract all digits
    digits = re.sub(r"\D", "", raw)

    if len(digits) == 15:
        return digits
    elif len(digits) == 14:
        # Calculate Luhn check digit
        return digits + luhn_checksum(digits)
    elif len(digits) == 16:
        # IMEISV: First 14 digits are TAC+SNR, 15th is Luhn check digit
        return digits[:14] + luhn_checksum(digits[:14])

    return None


def is_retry_value(current_e, current_d=""):
    """
    Check if a row's current values indicate it should be retried.
    Matches exact strings in RETRY_VALUES, any error message if 'Error' is in RETRY_VALUES,
    or if model is 'Not found' and 'Not found' is in RETRY_VALUES.
    """
    c_e = str(current_e or "").strip()
    c_d = str(current_d or "").strip()

    for rv in RETRY_VALUES:
        rv_lower = rv.lower()
        if rv_lower == "error":
            if c_e.lower().startswith("error") or "error" in c_e.lower():
                return True
        elif rv_lower == "not found":
            if c_e.lower() == "not found" or c_d.lower() == "not found":
                return True
        else:
            if c_e.lower() == rv_lower or c_d.lower() == rv_lower:
                return True
    return False


# ---------- ZTE helpers ----------
def request_json(method, url, **kwargs):
    """Returns (json, None) on success or (None, reason) on failure."""
    reason = "unknown error"
    for attempt in range(1, RETRIES + 1):
        try:
            r = http.request(method, url, timeout=(10, 25), **kwargs)
            if r.status_code == 200:
                try:
                    return r.json(), None
                except ValueError:
                    reason = "response was not JSON"
                    time.sleep(2 * attempt)
                    continue
            if r.status_code == 404:
                return None, "HTTP 404"
            reason = f"HTTP {r.status_code}"
            if r.status_code in (408, 429, 500, 502, 503, 504):
                time.sleep(5 * attempt)
                continue
            return None, reason
        except requests.RequestException as e:
            reason = f"network error: {type(e).__name__}"
            time.sleep(2 * attempt)
    return None, reason


def get_device_info(imei):
    """Returns ('ok', dict) | ('notfound', None) | ('error', reason)."""
    body, err = request_json(
        "GET", INFO_API, params={"query": imei},
        headers={"Referer": "https://www.ztedevices.com/en/support/check.html"})
    if err:
        return "error", f"info: {err}"
    if not isinstance(body, dict):
        return "error", "info: response was not a dictionary"

    error_code = body.get("errorCode")
    error_msg = str(body.get("errorMessage") or "")

    # Not found in ZTE product auth database
    if error_code == 404 or "not found" in error_msg.lower():
        return "notfound", None

    # Server returned an error code
    if error_code not in (0, None) and not body.get("success", False):
        return "error", f"info: code {error_code} {error_msg}".strip()

    results = body.get("results")
    if not isinstance(results, dict):
        return "notfound", None

    found_imei = results.get("imei") or imei
    found_meid = results.get("meid") or ""
    found_model = (results.get("model") or "").strip()

    return "ok", {
        "imei1": found_imei,
        "imei2": found_meid,
        "model": found_model or "Unknown",
    }


def get_activation_date(imei):
    """Returns ('ok', date) | ('none', None) | ('error', reason)."""
    body, err = request_json(
        "POST", ACTIVATION_API, json={"imei": imei},
        headers={"Content-Type": "application/json"})

    # HTTP 404 on the activation API means no certificate was found for this device in CRM
    if err == "HTTP 404":
        return "none", None
    if err:
        return "error", f"activation: {err}"
    if not isinstance(body, dict):
        return "error", "activation: unexpected response"

    code = body.get("code")
    if code in (801, 404):
        # 801: "fotatime null or before outstoretime" or "device info null":
        # device is not activated or has no activation record. Real answer, not an error.
        return "none", None

    if code != 800:
        # Any other code is treated as a temporary problem and retried.
        msg = str(body.get("message", ""))[:40]
        return "error", f"activation: code {code} {msg}".strip()

    data = body.get("data")
    begin = None
    if isinstance(data, dict):
        begin = data.get("begin")
    elif isinstance(data, str):
        begin = data

    if begin:
        begin_str = str(begin).strip()
        # Keep YYYY-MM-DD if ISO timestamp
        if len(begin_str) >= 10 and begin_str[4] == "-" and begin_str[7] == "-":
            begin_str = begin_str[:10]
        return "ok", begin_str

    return "none", None


# ---------- main logic ----------
def find_pending(ws, rechecked_this_session):
    """
    Finds rows that need processing.
    - Reads with UNFORMATTED_VALUE so 15-digit numbers are not scientific strings.
    - Processes empty Column E rows immediately.
    - If Column E is 'Invalid IMEI' but Column A was updated to a valid IMEI, re-processes.
    - If Column E or D matches RETRY_VALUES, re-processes once per session.
    """
    rows = sheet_call(ws.get_all_values, value_render_option="UNFORMATTED_VALUE")
    if not rows or len(rows) <= 1:
        return []

    pending = []
    for i, row in enumerate(rows[1:], start=2):
        raw_a = row[0] if row else ""
        raw = str(raw_a).strip()
        if not raw:
            continue

        current_e = str(row[4]).strip() if len(row) > 4 else ""
        current_d = str(row[3]).strip() if len(row) > 3 else ""

        key = (i, raw)

        # 1. Blank column E: user entered new IMEI or cleared cell to re-check
        if not current_e:
            rechecked_this_session.discard(key)
            pending.append((i, raw))
            continue

        # 2. Previously marked "Invalid IMEI", but user corrected Column A to a valid IMEI
        if current_e.lower() == "invalid imei" and clean_imei(raw):
            rechecked_this_session.discard(key)
            pending.append((i, raw))
            continue

        # 3. Matches retry values (e.g. Error: ... or Not found)
        if is_retry_value(current_e, current_d):
            if key not in rechecked_this_session:
                pending.append((i, raw))
            continue

    return pending


def process_row(ws, row_num, raw, fails, rechecked_this_session):
    key = (row_num, raw)
    imei = clean_imei(raw)

    if imei is None:
        sheet_call(ws.update, values=[["", "", "", "Invalid IMEI"]],
                   range_name=f"B{row_num}:E{row_num}")
        rechecked_this_session.add(key)
        fails.pop(key, None)
        print(f"  row {row_num}: {raw!r} -> Invalid IMEI")
        return

    # Always perform 100% fresh live requests to ZTE APIs in parallel (no cache)
    with ThreadPoolExecutor(max_workers=2) as executor:
        fut_info = executor.submit(get_device_info, imei)
        fut_act = executor.submit(get_activation_date, imei)

        info_status, info = fut_info.result()
        act_status, act = fut_act.result()

    if info_status == "error" or act_status == "error":
        reason = info if info_status == "error" else act
        fails[key] = fails.get(key, 0) + 1
        print(f"  row {row_num}: {imei} -> {reason} "
              f"(attempt {fails[key]}/{MAX_ATTEMPTS})")
        if fails[key] >= MAX_ATTEMPTS:
            # Retain model and IMEI if info was successfully retrieved
            imei1_val = (info.get("imei1") or imei) if isinstance(info, dict) else ""
            imei2_val = (info.get("imei2") or "") if isinstance(info, dict) else ""
            model_val = (info.get("model") or "") if isinstance(info, dict) else ""
            sheet_call(ws.update, values=[[imei1_val, imei2_val, model_val, f"Error: {reason}"[:80]]],
                       range_name=f"B{row_num}:E{row_num}")
            rechecked_this_session.add(key)
            fails.pop(key, None)
        return

    if info_status == "notfound":
        info = {"imei1": imei, "imei2": "", "model": "Not found"}
    else:
        if not info.get("imei1"):
            info["imei1"] = imei

    activation = act if act_status == "ok" else "Not activated"

    sheet_call(ws.update,
               values=[[info["imei1"], info["imei2"], info["model"], activation]],
               range_name=f"B{row_num}:E{row_num}")
    rechecked_this_session.add(key)
    fails.pop(key, None)
    print(f"  row {row_num}: {imei} -> {info['model']} | {activation}")


def main():
    def connect_sheet():
        gc = gspread.service_account(filename=KEY_FILE)
        sh = gc.open_by_url(SHEET_URL)
        return gc, sh, (sh.worksheet(WORKSHEET) if WORKSHEET else sh.sheet1)

    gc, sh, ws = connect_sheet()

    try:
        header_row = sheet_call(ws.row_values, 1)
        if not header_row or not header_row[0]:
            sheet_call(ws.update, values=[["Input IMEI"]], range_name="A1")
        if len(header_row) < 5 or header_row[1:5] != HEADERS:
            sheet_call(ws.update, values=[HEADERS], range_name="B1:E1")
    except Exception as e:
        print(f"Header check note: {e}")

    rechecked_this_session = set()
    fails = {}
    print(f"Watching the sheet every {POLL_SECONDS}s. Press Ctrl+C to stop.")

    while True:
        try:
            pending = find_pending(ws, rechecked_this_session)
            if pending:
                print(f"{time.strftime('%H:%M:%S')}  {len(pending)} row(s) to check")
            for row_num, raw in pending:
                try:
                    process_row(ws, row_num, raw, fails, rechecked_this_session)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    key = (row_num, raw)
                    fails[key] = fails.get(key, 0) + 1
                    print(f"  row {row_num}: unexpected error {type(e).__name__}: {e}")
                    if fails[key] >= MAX_ATTEMPTS:
                        try:
                            sheet_call(ws.update, values=[["", "", "", f"Error: {type(e).__name__}"]],
                                       range_name=f"B{row_num}:E{row_num}")
                        except Exception:
                            pass
                        rechecked_this_session.add(key)
                        fails.pop(key, None)
                time.sleep(DELAY)
        except KeyboardInterrupt:
            print("\nStopped.")
            return
        except Exception as e:
            print(f"{time.strftime('%H:%M:%S')}  problem reading sheet: "
                  f"{type(e).__name__}: {e}")
            try:
                gc, sh, ws = connect_sheet()
            except Exception as rc_err:
                print(f"  reconnect attempt failed: {rc_err}")
        try:
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("\nStopped.")
            return


if __name__ == "__main__":
    main()
