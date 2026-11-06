"""
ZTE IMEI Bulk Checker Pro - Web Application with Secure Authentication.

Features:
- Multi-user authentication (admin, shazain, demo) with signed session cookies.
- Safe 5-worker parallel processing (tested for 300-400+ IMEIs without IP block).
- Realtime Server-Sent Events (SSE) streaming directly into a spreadsheet-like live table.
- One-click export to Excel (.xlsx), CSV, and Copy-to-Clipboard (Google Sheets paste format).
- Embedded standalone frontend (Tailwind CSS, SheetJS, Lucide/FontAwesome via CDN).
- Ready for Render, Hugging Face Spaces, Koyeb, or local deployment.
"""
import os
import json
import time
import queue
import random
import hmac
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from fastapi import FastAPI, Request, Form, Response, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import Main1

app = FastAPI(title="Device Verification Portal", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- AUTH & CONFIG ----------
SESSION_SECRET = os.environ.get("SESSION_SECRET", "zte-imei-auth-secret-key-2026")
COOKIE_NAME = "session_token"

# Configured user accounts (passwords can be overridden via Render Environment Variables)
USERS = {
    "admin": os.environ.get("ADMIN_PASSWORD", "admin@2026"),
    "shazain": os.environ.get("SHAZAIN_PASSWORD", "shazain@2026"),
    "demo": os.environ.get("DEMO_PASSWORD", "demo@2026"),
}

MAX_PARALLEL_WORKERS = 5
SAFE_JITTER_SECONDS = (0.15, 0.35)
global_cache = {}


def create_session_token(username: str) -> str:
    """Generate a tamper-proof signed session token valid for 7 days."""
    expires = int(time.time()) + 7 * 86400
    payload = f"{username}:{expires}"
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def verify_session_token(token: Optional[str]) -> Optional[str]:
    """Validate token and return username, or None if invalid/expired."""
    if not token or ":" not in token:
        return None
    parts = token.split(":")
    if len(parts) != 3:
        return None
    username, expires_str, sig = parts
    try:
        expires = int(expires_str)
        if time.time() > expires:
            return None
    except ValueError:
        return None
    expected_sig = hmac.new(SESSION_SECRET.encode(), f"{username}:{expires}".encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected_sig) and username in USERS:
        return username
    return None


def get_current_user(request: Request) -> Optional[str]:
    """Extract authenticated username from request cookies."""
    token = request.cookies.get(COOKIE_NAME)
    return verify_session_token(token)


# ---------- CORE LOGIC ----------
def check_single_imei(idx: int, raw_input: str) -> dict:
    """Process a single IMEI using parallel sub-requests and caching."""
    raw_str = str(raw_input or "").strip()
    imei = Main1.clean_imei(raw_str)

    if not imei:
        return {
            "index": idx,
            "raw": raw_str,
            "imei1": "",
            "imei2": "",
            "model": "",
            "activation": "Invalid IMEI",
            "status": "invalid"
        }

    # Safe worker jitter to avoid burst synchronization
    time.sleep(random.uniform(*SAFE_JITTER_SECONDS))

    cached_info = global_cache.get(f"info:{imei}")
    cached_act = global_cache.get(f"act:{imei}")

    info_status, info = ("ok" if cached_info else "error"), cached_info
    act_status, act = ("ok" if cached_act else "error"), cached_act

    need_info = not cached_info
    need_act = not cached_act

    if need_info or need_act:
        with ThreadPoolExecutor(max_workers=2) as sub_exec:
            fut_info = sub_exec.submit(Main1.get_device_info, imei) if need_info else None
            fut_act = sub_exec.submit(Main1.get_activation_date, imei) if need_act else None

            if fut_info:
                info_status, info = fut_info.result()
                if info_status == "ok":
                    global_cache[f"info:{imei}"] = info

            if fut_act:
                act_status, act = fut_act.result()
                if act_status == "ok":
                    global_cache[f"act:{imei}"] = act

    if info_status == "error" or act_status == "error":
        reason = info if info_status == "error" else act
        imei1_val = (info.get("imei1") or imei) if isinstance(info, dict) else imei
        imei2_val = (info.get("imei2") or "") if isinstance(info, dict) else ""
        model_val = (info.get("model") or "") if isinstance(info, dict) else ""
        return {
            "index": idx,
            "raw": raw_str,
            "imei1": imei1_val,
            "imei2": imei2_val,
            "model": model_val,
            "activation": f"Error: {reason}"[:60],
            "status": "error"
        }

    if info_status == "notfound":
        model_name = "Not found"
        imei1 = imei
        imei2 = ""
    else:
        model_name = info.get("model") or "Unknown"
        imei1 = info.get("imei1") or imei
        imei2 = info.get("imei2") or ""

    if act_status == "ok":
        activation_val = act
        status_tag = "activated"
    else:
        activation_val = "Not activated"
        status_tag = "not_activated"

    return {
        "index": idx,
        "raw": raw_str,
        "imei1": imei1,
        "imei2": imei2,
        "model": model_name,
        "activation": activation_val,
        "status": status_tag
    }


# ---------- HTML TEMPLATES ----------
def get_login_html(error_msg: str = "") -> str:
    err_banner = f"""
    <div class="mb-4 p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs flex items-center gap-2">
      <i class="fa-solid fa-circle-exclamation"></i>
      <span>{error_msg}</span>
    </div>
    """ if error_msg else ""

    return f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Login - Device Verification Portal</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-[#0f111a] text-slate-100 min-h-screen flex items-center justify-center p-4 antialiased font-sans">
  <div class="w-full max-w-md">
    <div class="bg-[#161824] border border-slate-800 rounded-3xl p-8 shadow-2xl backdrop-blur">
      <div class="text-center mb-6">
        <div class="h-14 w-14 rounded-2xl bg-gradient-to-tr from-indigo-600 to-indigo-400 flex items-center justify-center shadow-lg shadow-indigo-600/30 mx-auto mb-4">
          <i class="fa-solid fa-mobile-screen-button text-white text-2xl"></i>
        </div>
        <h1 class="text-2xl font-bold text-white tracking-tight">Device Portal</h1>
        <p class="text-xs text-slate-400 mt-1">Sign in to access bulk verification tools</p>
      </div>

      {err_banner}

      <form action="/login" method="POST" class="space-y-4">
        <div>
          <label class="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">Username</label>
          <div class="relative">
            <i class="fa-solid fa-user absolute left-3.5 top-3 text-slate-500 text-sm"></i>
            <input type="text" name="username" required autocomplete="username" placeholder="Enter username"
              class="w-full bg-[#0c0d14] border border-slate-800 rounded-xl pl-10 pr-4 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500 transition">
          </div>
        </div>

        <div>
          <label class="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">Password</label>
          <div class="relative">
            <i class="fa-solid fa-lock absolute left-3.5 top-3 text-slate-500 text-sm"></i>
            <input type="password" name="password" required autocomplete="current-password" placeholder="••••••••"
              class="w-full bg-[#0c0d14] border border-slate-800 rounded-xl pl-10 pr-4 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500 transition">
          </div>
        </div>

        <button type="submit"
          class="w-full py-3 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-white font-semibold text-sm shadow-lg shadow-indigo-600/30 transition flex items-center justify-center gap-2 mt-6">
          <span>Sign In</span>
          <i class="fa-solid fa-arrow-right text-xs"></i>
        </button>
      </form>

      <div class="mt-6 pt-5 border-t border-slate-800/80 text-center text-xs text-slate-500">
        Authorized Access Only &bull; Secured Session
      </div>
    </div>
  </div>
</body>
</html>"""


def get_dashboard_html(username: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Device IMEI Bulk Checker Pro</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
    ::-webkit-scrollbar-track {{ background: #1e1e2d; }}
    ::-webkit-scrollbar-thumb {{ background: #3b3b54; border-radius: 4px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: #4f46e5; }}
    @keyframes pulse-subtle {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.6; }} }}
    .pulse-glow {{ animation: pulse-subtle 1.8s infinite ease-in-out; }}
  </style>
</head>
<body class="bg-[#0f111a] text-slate-100 min-h-screen font-sans flex flex-col antialiased">

  <!-- Header -->
  <header class="border-b border-slate-800 bg-[#161824]/90 backdrop-blur sticky top-0 z-50 px-6 py-4 flex flex-wrap items-center justify-between gap-4">
    <div class="flex items-center space-x-3">
      <div class="h-10 w-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-indigo-400 flex items-center justify-center shadow-lg shadow-indigo-500/20">
        <i class="fa-solid fa-mobile-screen-button text-white text-lg"></i>
      </div>
      <div>
        <h1 class="text-xl font-bold tracking-tight text-white flex items-center gap-2">
          Device IMEI Checker <span class="text-xs px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 font-medium">PRO</span>
        </h1>
        <p class="text-xs text-slate-400">High-Speed & Safe 5-Worker Parallel Verification</p>
      </div>
    </div>

    <div class="flex items-center gap-4 text-xs">
      <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
        <span class="h-2 w-2 rounded-full bg-emerald-400 pulse-glow"></span> 5 Workers Active
      </span>
      <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
        <i class="fa-solid fa-user-circle text-indigo-400"></i> {username}
      </span>
      <a href="/logout" class="px-3 py-1.5 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/20 text-rose-400 font-medium transition flex items-center gap-1.5">
        <i class="fa-solid fa-arrow-right-from-bracket"></i> Logout
      </a>
    </div>
  </header>

  <!-- Main Container -->
  <main class="flex-1 max-w-7xl w-full mx-auto p-4 md:p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">

    <!-- Left Column: Input and Controls (4 Cols) -->
    <section class="lg:col-span-4 flex flex-col gap-5">
      <div class="bg-[#161824] border border-slate-800 rounded-2xl p-5 shadow-xl flex flex-col h-full">
        <div class="flex items-center justify-between mb-3">
          <label class="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <i class="fa-solid fa-list-ol text-indigo-400"></i> Input IMEI List
          </label>
          <span id="imeiCountBadge" class="text-xs px-2.5 py-0.5 rounded-full bg-slate-800 text-slate-400 font-mono">
            0 IMEIs
          </span>
        </div>

        <textarea id="imeiInput" rows="14" placeholder="Paste IMEIs here (1 per line)&#10;e.g.&#10;866627081977061&#10;866627081975750&#10;862484082466858"
          class="w-full flex-1 bg-[#0c0d14] border border-slate-800 rounded-xl p-3 text-sm font-mono text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500 transition resize-none"></textarea>

        <div class="flex items-center justify-between text-xs text-slate-400 mt-2 mb-4 px-1">
          <button id="btnDedupe" class="hover:text-indigo-400 transition flex items-center gap-1">
            <i class="fa-solid fa-wand-magic-sparkles"></i> Clean & Dedupe
          </button>
          <button id="btnClear" class="hover:text-rose-400 transition flex items-center gap-1">
            <i class="fa-solid fa-trash-can"></i> Clear All
          </button>
        </div>

        <!-- Action Buttons -->
        <div class="flex gap-2">
          <button id="btnStart" class="flex-1 py-3 px-4 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-white font-semibold text-sm shadow-lg shadow-indigo-600/30 transition flex items-center justify-center gap-2">
            <i class="fa-solid fa-play"></i> Start Check
          </button>
          <button id="btnStop" disabled class="py-3 px-4 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white font-semibold text-sm transition disabled:opacity-40 disabled:cursor-not-allowed">
            <i class="fa-solid fa-stop"></i>
          </button>
        </div>
      </div>
    </section>

    <!-- Right Column: Live Table & Stats (8 Cols) -->
    <section class="lg:col-span-8 flex flex-col gap-5">

      <!-- Stats Bar -->
      <div class="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <div class="bg-[#161824] border border-slate-800 rounded-xl p-3">
          <p class="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Total</p>
          <p id="statTotal" class="text-xl font-bold font-mono text-white mt-0.5">0</p>
        </div>
        <div class="bg-[#161824] border border-slate-800 rounded-xl p-3">
          <p class="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Processed</p>
          <p id="statProcessed" class="text-xl font-bold font-mono text-indigo-400 mt-0.5">0</p>
        </div>
        <div class="bg-[#161824] border border-emerald-900/40 bg-emerald-950/10 rounded-xl p-3">
          <p class="text-[11px] font-medium text-emerald-400 uppercase tracking-wider">Activated</p>
          <p id="statActivated" class="text-xl font-bold font-mono text-emerald-400 mt-0.5">0</p>
        </div>
        <div class="bg-[#161824] border border-amber-900/40 bg-amber-950/10 rounded-xl p-3">
          <p class="text-[11px] font-medium text-amber-400 uppercase tracking-wider">Not Active</p>
          <p id="statNotActivated" class="text-xl font-bold font-mono text-amber-400 mt-0.5">0</p>
        </div>
        <div class="bg-[#161824] border border-rose-900/40 bg-rose-950/10 rounded-xl p-3 col-span-2 sm:col-span-1">
          <p class="text-[11px] font-medium text-rose-400 uppercase tracking-wider">Error/Invalid</p>
          <p id="statError" class="text-xl font-bold font-mono text-rose-400 mt-0.5">0</p>
        </div>
      </div>

      <!-- Progress Bar -->
      <div class="w-full bg-[#161824] rounded-full h-2.5 overflow-hidden border border-slate-800">
        <div id="progressBar" class="bg-gradient-to-r from-indigo-600 to-emerald-400 h-2.5 rounded-full transition-all duration-300 w-0"></div>
      </div>

      <!-- Live Table Card -->
      <div class="bg-[#161824] border border-slate-800 rounded-2xl flex-1 flex flex-col shadow-xl overflow-hidden min-h-[460px]">
        <!-- Table Toolbar -->
        <div class="p-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-2">
            <div class="relative">
              <i class="fa-solid fa-magnifying-glass absolute left-3 top-2.5 text-slate-500 text-xs"></i>
              <input id="searchInput" type="text" placeholder="Search table..."
                class="bg-[#0c0d14] border border-slate-800 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500 transition w-44">
            </div>
            <select id="filterStatus" class="bg-[#0c0d14] border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500">
              <option value="all">All Statuses</option>
              <option value="activated">Activated Only</option>
              <option value="not_activated">Not Activated Only</option>
              <option value="error">Errors / Invalid</option>
            </select>
          </div>

          <!-- Export Buttons -->
          <div class="flex items-center gap-2">
            <button id="btnCopy" class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 font-medium transition flex items-center gap-1.5">
              <i class="fa-solid fa-clipboard"></i> Copy Sheet
            </button>
            <button id="btnExportCSV" class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 font-medium transition flex items-center gap-1.5">
              <i class="fa-solid fa-file-csv text-emerald-400"></i> CSV
            </button>
            <button id="btnExportExcel" class="px-3 py-1.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 text-xs text-indigo-300 font-semibold transition flex items-center gap-1.5">
              <i class="fa-solid fa-file-excel text-emerald-400"></i> Excel (.xlsx)
            </button>
          </div>
        </div>

        <!-- Table Viewport -->
        <div class="flex-1 overflow-auto max-h-[500px]">
          <table class="w-full text-left border-collapse text-xs">
            <thead class="bg-[#0c0d14]/90 text-slate-400 uppercase tracking-wider sticky top-0 z-10 font-semibold border-b border-slate-800">
              <tr>
                <th class="py-3 px-3 w-12 text-center">#</th>
                <th class="py-3 px-4">Input IMEI</th>
                <th class="py-3 px-4">IMEI 1</th>
                <th class="py-3 px-4">IMEI 2 / MEID</th>
                <th class="py-3 px-4">Model</th>
                <th class="py-3 px-4">Activation Date</th>
                <th class="py-3 px-4 text-center">Status</th>
              </tr>
            </thead>
            <tbody id="resultsTableBody" class="divide-y divide-slate-800/60 font-mono">
              <tr id="emptyRow" class="text-slate-600 text-center">
                <td colspan="7" class="py-16 text-sm">
                  <i class="fa-solid fa-inbox text-3xl mb-2 block opacity-40"></i>
                  Paste IMEIs on the left and click "Start Check"
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

    </section>
  </main>

  <script>
    const imeiInput = document.getElementById('imeiInput');
    const imeiCountBadge = document.getElementById('imeiCountBadge');
    const btnStart = document.getElementById('btnStart');
    const btnStop = document.getElementById('btnStop');
    const btnDedupe = document.getElementById('btnDedupe');
    const btnClear = document.getElementById('btnClear');
    const tableBody = document.getElementById('resultsTableBody');
    const progressBar = document.getElementById('progressBar');

    const statTotal = document.getElementById('statTotal');
    const statProcessed = document.getElementById('statProcessed');
    const statActivated = document.getElementById('statActivated');
    const statNotActivated = document.getElementById('statNotActivated');
    const statError = document.getElementById('statError');

    const searchInput = document.getElementById('searchInput');
    const filterStatus = document.getElementById('filterStatus');
    const btnCopy = document.getElementById('btnCopy');
    const btnExportCSV = document.getElementById('btnExportCSV');
    const btnExportExcel = document.getElementById('btnExportExcel');

    let allResults = [];
    let isRunning = false;
    let abortController = null;

    function getCleanList() {{
      const text = imeiInput.value;
      return text.split('\\n')
        .map(s => s.trim())
        .filter(s => s.length > 0);
    }}

    imeiInput.addEventListener('input', () => {{
      const list = getCleanList();
      imeiCountBadge.textContent = `${{list.length}} IMEIs`;
    }});

    btnDedupe.addEventListener('click', () => {{
      const list = getCleanList();
      const unique = Array.from(new Set(list));
      imeiInput.value = unique.join('\\n');
      imeiCountBadge.textContent = `${{unique.length}} IMEIs`;
    }});

    btnClear.addEventListener('click', () => {{
      imeiInput.value = '';
      imeiCountBadge.textContent = '0 IMEIs';
    }});

    btnStart.addEventListener('click', async () => {{
      const imeis = getCleanList();
      if (!imeis.length) {{
        alert('Please paste at least one IMEI to check.');
        return;
      }}

      allResults = [];
      tableBody.innerHTML = '';
      statTotal.textContent = imeis.length;
      statProcessed.textContent = '0';
      statActivated.textContent = '0';
      statNotActivated.textContent = '0';
      statError.textContent = '0';
      progressBar.style.width = '0%';

      btnStart.disabled = true;
      btnStart.classList.add('opacity-50');
      btnStop.disabled = false;
      isRunning = true;
      abortController = new AbortController();

      try {{
        const response = await fetch('/api/check-stream', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ imeis }}),
          signal: abortController.signal
        }});

        if (response.status === 401) {{
          alert('Session expired. Please login again.');
          window.location.href = '/login';
          return;
        }}

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {{
          const {{ done, value }} = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, {{ stream: true }});
          const lines = buffer.split('\\n\\n');
          buffer = lines.pop();

          for (const line of lines) {{
            if (line.startsWith('data: ')) {{
              const jsonStr = line.replace('data: ', '').trim();
              if (jsonStr === '[DONE]') break;
              try {{
                const item = JSON.parse(jsonStr);
                addRow(item, imeis.length);
              }} catch (e) {{
                console.error(e);
              }}
            }}
          }}
        }}
      }} catch (err) {{
        if (err.name !== 'AbortError') {{
          console.error(err);
          alert('Stream error: ' + err.message);
        }}
      }} finally {{
        isRunning = false;
        btnStart.disabled = false;
        btnStart.classList.remove('opacity-50');
        btnStop.disabled = true;
      }}
    }});

    btnStop.addEventListener('click', () => {{
      if (abortController) abortController.abort();
    }});

    function addRow(item, totalCount) {{
      allResults.push(item);

      const processed = allResults.length;
      statProcessed.textContent = processed;
      const pct = Math.round((processed / totalCount) * 100);
      progressBar.style.width = `${{pct}}%`;

      let actCount = 0, notActCount = 0, errCount = 0;
      for (const r of allResults) {{
        if (r.status === 'activated') actCount++;
        else if (r.status === 'not_activated') notActCount++;
        else errCount++;
      }}
      statActivated.textContent = actCount;
      statNotActivated.textContent = notActCount;
      statError.textContent = errCount;

      renderRowElement(item);
    }}

    function renderRowElement(item) {{
      let badgeHtml = '';
      if (item.status === 'activated') {{
        badgeHtml = `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-sans font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Activated</span>`;
      }} else if (item.status === 'not_activated') {{
        badgeHtml = `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-sans font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">Not Activated</span>`;
      }} else if (item.status === 'invalid') {{
        badgeHtml = `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-sans font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">Invalid IMEI</span>`;
      }} else {{
        badgeHtml = `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-sans font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">Error</span>`;
      }}

      const tr = document.createElement('tr');
      tr.className = 'hover:bg-slate-800/40 transition';
      tr.dataset.status = item.status;
      tr.dataset.model = (item.model || '').toLowerCase();
      tr.dataset.imei = (item.raw || '').toLowerCase();

      tr.innerHTML = `
        <td class="py-2.5 px-3 text-center text-slate-500 text-[11px]">${{item.index}}</td>
        <td class="py-2.5 px-4 font-semibold text-slate-200">${{item.raw}}</td>
        <td class="py-2.5 px-4 text-slate-300">${{item.imei1 || '<span class="text-slate-600">-</span>'}}</td>
        <td class="py-2.5 px-4 text-slate-400">${{item.imei2 || '<span class="text-slate-600">-</span>'}}</td>
        <td class="py-2.5 px-4 text-indigo-300 font-semibold">${{item.model || '<span class="text-slate-600">-</span>'}}</td>
        <td class="py-2.5 px-4 ${{item.status === 'activated' ? 'text-emerald-400 font-bold' : 'text-slate-400'}}">${{item.activation}}</td>
        <td class="py-2.5 px-4 text-center">${{badgeHtml}}</td>
      `;

      const q = searchInput.value.toLowerCase();
      const statusFilter = filterStatus.value;
      let visible = true;
      if (statusFilter !== 'all' && item.status !== statusFilter) visible = false;
      if (q && !item.raw.includes(q) && !(item.model || '').toLowerCase().includes(q)) visible = false;

      if (!visible) tr.style.display = 'none';

      tableBody.appendChild(tr);
    }}

    function applyFilters() {{
      const q = searchInput.value.toLowerCase();
      const statusFilter = filterStatus.value;
      const rows = tableBody.querySelectorAll('tr');

      rows.forEach(tr => {{
        if (!tr.dataset.imei) return;
        let show = true;
        if (statusFilter !== 'all' && tr.dataset.status !== statusFilter) show = false;
        if (q && !tr.dataset.imei.includes(q) && !tr.dataset.model.includes(q)) show = false;
        tr.style.display = show ? '' : 'none';
      }});
    }}

    searchInput.addEventListener('input', applyFilters);
    filterStatus.addEventListener('change', applyFilters);

    btnExportExcel.addEventListener('click', () => {{
      if (!allResults.length) return alert('No results to export.');
      const data = allResults.map(r => ({{
        '#': r.index,
        'Input IMEI': r.raw,
        'IMEI1': r.imei1,
        'IMEI2 / MEID': r.imei2,
        'Model': r.model,
        'Activation Date': r.activation,
        'Status': r.status
      }}));
      const ws = XLSX.utils.json_to_sheet(data);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, 'IMEI Results');
      XLSX.writeFile(wb, `Device_IMEI_Check_${{new Date().toISOString().slice(0, 10)}}.xlsx`);
    }});

    btnExportCSV.addEventListener('click', () => {{
      if (!allResults.length) return alert('No results to export.');
      let csv = 'Index,Input_IMEI,IMEI1,IMEI2_MEID,Model,Activation_Date,Status\\n';
      for (const r of allResults) {{
        csv += `"${{r.index}}","${{r.raw}}","${{r.imei1}}","${{r.imei2}}","${{r.model}}","${{r.activation}}","${{r.status}}"\\n`;
      }}
      const blob = new Blob([csv], {{ type: 'text/csv;charset=utf-8;' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Device_IMEI_Check_${{new Date().toISOString().slice(0, 10)}}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    }});

    btnCopy.addEventListener('click', () => {{
      if (!allResults.length) return alert('No results to copy.');
      let tsv = 'Input IMEI\\tIMEI1\\tIMEI2\\tModel\\tActivation Date\\n';
      for (const r of allResults) {{
        tsv += `${{r.raw}}\\t${{r.imei1}}\\t${{r.imei2}}\\t${{r.model}}\\t${{r.activation}}\\n`;
      }}
      navigator.clipboard.writeText(tsv).then(() => {{
        const origText = btnCopy.innerHTML;
        btnCopy.innerHTML = '<i class="fa-solid fa-check text-emerald-400"></i> Copied!';
        setTimeout(() => btnCopy.innerHTML = origText, 2000);
      }});
    }});
  </script>
</body>
</html>"""


# ---------- ROUTES ----------
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return HTMLResponse(content=get_login_html())


@app.post("/login", response_class=HTMLResponse)
async def login_submit(username: str = Form(...), password: str = Form(...)):
    username_clean = username.strip().lower()
    expected_password = USERS.get(username_clean)

    if expected_password and hmac.compare_digest(password.strip(), expected_password):
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        token = create_session_token(username_clean)
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            max_age=7 * 86400,
            httponly=True,
            samesite="lax",
            secure=False  # Works on HTTP (local) and HTTPS (Render automatically terminates SSL)
        )
        return response

    return HTMLResponse(
        content=get_login_html(error_msg="Invalid username or password. Please try again."),
        status_code=status.HTTP_401_UNAUTHORIZED
    )


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return HTMLResponse(content=get_dashboard_html(user))


@app.post("/api/check-stream")
async def check_stream(req: Request):
    user = get_current_user(req)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    payload = await req.json()
    imei_list: List[str] = payload.get("imeis", [])

    def event_stream():
        res_queue = queue.Queue()

        def producer():
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
                futures = {
                    executor.submit(check_single_imei, idx, raw): (idx, raw)
                    for idx, raw in enumerate(imei_list, start=1)
                }
                for fut in as_completed(futures):
                    try:
                        res = fut.result()
                        res_queue.put(res)
                    except Exception as e:
                        idx, raw = futures[fut]
                        res_queue.put({
                            "index": idx,
                            "raw": raw,
                            "imei1": "",
                            "imei2": "",
                            "model": "",
                            "activation": f"Error: {type(e).__name__}",
                            "status": "error"
                        })
            res_queue.put(None)

        worker_thread = threading.Thread(target=producer, daemon=True)
        worker_thread.start()

        while True:
            try:
                item = res_queue.get(timeout=35)
                if item is None:
                    yield "data: [DONE]\n\n"
                    break
                yield f"data: {json.dumps(item)}\n\n"
            except queue.Empty:
                yield "data: [DONE]\n\n"
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("\n=======================================================")
    print("  Device Verification Portal running on:")
    print(f"  --> http://localhost:{port}")
    print("=======================================================\n")
    uvicorn.run("web_app:app", host="0.0.0.0", port=port, reload=False)
