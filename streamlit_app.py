"""
Device Verification Portal - Streamlit Edition.

Features:
- Built-in multi-user authentication (admin, shazain, demo).
- Safe 5-worker parallel processing (tested for 300-400+ IMEIs without IP block).
- Realtime table updates and live progress bar as each IMEI completes.
- One-click export to Excel (.xlsx) and CSV.
- 100% fresh live requests every time (no caching).
"""
import os
import io
import time
import random
import hmac
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st
import pandas as pd
import Main1

# ---------- CONFIG & AUTH ----------
USERS = {
    "admin": os.environ.get("ADMIN_PASSWORD", "admin@2026"),
    "shazain": os.environ.get("SHAZAIN_PASSWORD", "shazain@2026"),
    "demo": os.environ.get("DEMO_PASSWORD", "demo@2026"),
}

# If Streamlit secrets exist, allow them to override
try:
    if hasattr(st, "secrets") and "passwords" in st.secrets:
        for u in USERS:
            if u in st.secrets["passwords"]:
                USERS[u] = st.secrets["passwords"][u]
except Exception:
    pass

MAX_PARALLEL_WORKERS = 5
SAFE_JITTER_SECONDS = (0.15, 0.35)


def check_auth(username, password):
    user_clean = username.strip().lower()
    expected_pw = USERS.get(user_clean)
    if expected_pw and hmac.compare_digest(password.strip(), expected_pw):
        return user_clean
    return None


def check_single_imei_live(idx: int, raw_input: str) -> dict:
    raw_str = str(raw_input or "").strip()
    imei = Main1.clean_imei(raw_str)

    if not imei:
        return {
            "#": idx,
            "Input IMEI": raw_str,
            "IMEI 1": "-",
            "IMEI 2 / MEID": "-",
            "Model": "-",
            "Activation Date": "Invalid IMEI",
            "Status": "Invalid"
        }

    time.sleep(random.uniform(*SAFE_JITTER_SECONDS))

    with ThreadPoolExecutor(max_workers=2) as sub_exec:
        fut_info = sub_exec.submit(Main1.get_device_info, imei)
        fut_act = sub_exec.submit(Main1.get_activation_date, imei)

        info_status, info = fut_info.result()
        act_status, act = fut_act.result()

    if info_status == "error" or act_status == "error":
        reason = info if info_status == "error" else act
        imei1_val = (info.get("imei1") or imei) if isinstance(info, dict) else imei
        imei2_val = (info.get("imei2") or "-") if isinstance(info, dict) else "-"
        model_val = (info.get("model") or "-") if isinstance(info, dict) else "-"
        return {
            "#": idx,
            "Input IMEI": raw_str,
            "IMEI 1": imei1_val,
            "IMEI 2 / MEID": imei2_val,
            "Model": model_val,
            "Activation Date": f"Error: {reason}"[:50],
            "Status": "Error"
        }

    if info_status == "notfound":
        model_name = "Not found"
        imei1 = imei
        imei2 = "-"
    else:
        model_name = info.get("model") or "Unknown"
        imei1 = info.get("imei1") or imei
        imei2 = info.get("imei2") or "-"

    if act_status == "ok":
        activation_val = act
        status_tag = "Activated"
    else:
        activation_val = "Not activated"
        status_tag = "Not Activated"

    return {
        "#": idx,
        "Input IMEI": raw_str,
        "IMEI 1": imei1,
        "IMEI 2 / MEID": imei2,
        "Model": model_name,
        "Activation Date": activation_val,
        "Status": status_tag
    }


# ---------- LOGIN SCREEN ----------
def show_login():
    col1, col2, col3 = st.columns([1, 1.8, 1])
    with col2:
        st.write("")
        st.write("")
        with st.container(border=True):
            st.title("📱 Device Verification Portal")
            st.caption("Sign in to access bulk verification tools")
            st.write("---")

            with st.form("login_form"):
                username_input = st.text_input("Username", placeholder="e.g. admin, shazain, demo")
                password_input = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

                if submitted:
                    user = check_auth(username_input, password_input)
                    if user:
                        st.session_state.authenticated = True
                        st.session_state.username = user
                        st.rerun()
                    else:
                        st.error("Invalid username or password.")


# ---------- MAIN DASHBOARD ----------
def show_dashboard():
    # Sidebar
    with st.sidebar:
        st.subheader(f"👤 Logged in as: **{st.session_state.username}**")
        if st.button("Logout", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.username = None
            st.session_state.results = []
            st.rerun()

        st.write("---")
        st.markdown("""
        **System Specs:**
        - ⚡ **5 Parallel Workers**
        - 🛡️ **Anti-Ban Jitter Enabled**
        - 🔄 **100% Fresh Live Queries**
        """)

    # Main Area
    st.title("Device IMEI Bulk Checker Pro")
    st.caption("High-Speed & Safe 5-Worker Parallel Device Verification")

    col_input, col_view = st.columns([1, 2], gap="medium")

    with col_input:
        with st.container(border=True):
            st.subheader("📋 Input IMEI List")
            imei_raw = st.text_area(
                "Paste IMEIs (1 per line)",
                height=320,
                placeholder="866627081977061\n866627081975750\n862484082466858"
            )

            # Clean and get lines
            lines = [line.strip() for line in imei_raw.split("\n") if line.strip()]
            st.caption(f"**{len(lines)}** IMEIs detected")

            col_btn1, col_btn2 = st.columns([2, 1])
            with col_btn1:
                start_clicked = st.button("🚀 Start Check", type="primary", use_container_width=True, disabled=st.session_state.is_checking)
            with col_btn2:
                if st.button("🧹 Clear", use_container_width=True):
                    st.session_state.results = []
                    st.rerun()

    with col_view:
        # Results container
        status_box = st.empty()
        prog_bar = st.empty()
        metrics_placeholder = st.empty()
        table_placeholder = st.empty()
        export_placeholder = st.empty()

        if start_clicked and lines:
            st.session_state.is_checking = True
            st.session_state.results = []
            results_list = []
            total = len(lines)

            # Process parallel
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
                futures = {
                    executor.submit(check_single_imei_live, idx, raw): idx
                    for idx, raw in enumerate(lines, start=1)
                }

                for i, fut in enumerate(as_completed(futures), start=1):
                    res = fut.result()
                    results_list.append(res)
                    # Sort results by original index
                    results_sorted = sorted(results_list, key=lambda x: x["#"])
                    df_live = pd.DataFrame(results_sorted)

                    # Update progress
                    pct = int((i / total) * 100)
                    prog_bar.progress(pct, text=f"Checking {i}/{total} ({pct}% complete)...")

                    # Live metrics
                    act = sum(1 for r in results_list if r["Status"] == "Activated")
                    not_act = sum(1 for r in results_list if r["Status"] == "Not Activated")
                    err = len(results_list) - act - not_act

                    with metrics_placeholder.container():
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Total", total)
                        m2.metric("Processed", f"{i}/{total}")
                        m3.metric("Activated", act)
                        m4.metric("Not Active / Err", f"{not_act} | {err}")

                    table_placeholder.dataframe(df_live, use_container_width=True, height=360)

            st.session_state.results = results_sorted
            st.session_state.is_checking = False
            prog_bar.empty()
            status_box.success("✅ Bulk verification complete!")

        # Render saved results if available
        if st.session_state.results and not start_clicked:
            df = pd.DataFrame(st.session_state.results)

            act = sum(1 for r in st.session_state.results if r["Status"] == "Activated")
            not_act = sum(1 for r in st.session_state.results if r["Status"] == "Not Activated")
            err = len(st.session_state.results) - act - not_act

            with metrics_placeholder.container():
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total", len(df))
                m2.metric("Processed", f"{len(df)}/{len(df)}")
                m3.metric("Activated", act)
                m4.metric("Not Active / Err", f"{not_act} | {err}")

            table_placeholder.dataframe(df, use_container_width=True, height=360)

            # Export Buttons
            with export_placeholder.container():
                c1, c2 = st.columns(2)
                with c1:
                    csv_data = df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label="📥 Download CSV",
                        data=csv_data,
                        file_name=f"IMEI_Check_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                with c2:
                    excel_buffer = io.BytesIO()
                    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                        df.to_excel(writer, index=False, sheet_name="IMEI Results")
                    excel_data = excel_buffer.getvalue()
                    st.download_button(
                        label="📊 Download Excel (.xlsx)",
                        data=excel_data,
                        file_name=f"IMEI_Check_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )


def main():
    try:
        st.set_page_config(
            page_title="Device Verification Portal",
            page_icon="📱",
            layout="wide"
        )
    except Exception:
        pass

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "username" not in st.session_state:
        st.session_state.username = None
    if "results" not in st.session_state:
        st.session_state.results = []
    if "is_checking" not in st.session_state:
        st.session_state.is_checking = False

    if not st.session_state.authenticated:
        show_login()
    else:
        show_dashboard()


if __name__ == "__main__":
    main()
