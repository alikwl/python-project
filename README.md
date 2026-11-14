# Device Verification Portal

A high-performance batch IMEI verification and inspection tool featuring safe parallel workers, real-time live streaming, and instant reporting.

## Key Features

- **Batch Verification**: Process hundreds of IMEIs simultaneously with automatic formatting, deduplication, and Luhn checksum completion.
- **Safe Parallel Engine**: Bounded 5-worker concurrency with smart rate-limiting and jitter to ensure optimal throughput and stability.
- **Real-Time Live Table**: Stream results dynamically row-by-row into a spreadsheet view without page reloads.
- **One-Click Export**: Export complete datasets directly to Excel (`.xlsx`) or CSV, or copy formatted data ready for spreadsheets.
- **Secure Authentication**: Built-in session security with role-based user authentication.

## Quick Start (Local)

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Start with Streamlit**:
   ```bash
   streamlit run streamlit_app.py
   ```

3. **Or start with Web App**:
   ```bash
   python web_app.py
   ```

## Cloud Deployment

### 1. Streamlit Community Cloud (Free)
1. Go to [share.streamlit.io](https://share.streamlit.io).
2. Connect your GitHub repository.
3. Set **Main file path** to `streamlit_app.py`.
4. Click **Deploy**.

### 2. Render.com / Hugging Face Spaces (Free)
- **Start Command**: `uvicorn web_app:app --host 0.0.0.0 --port $PORT`

## License

Private & Confidential - All Rights Reserved.
