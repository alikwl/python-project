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

2. **Start the application**:
   ```bash
   python web_app.py
   ```

3. Open your browser at:
   ```
   http://localhost:8000
   ```

## Cloud Deployment (Render.com)

1. Connect this repository to your **Render** account.
2. Select **New Web Service**.
3. Configure the build settings:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn web_app:app --host 0.0.0.0 --port $PORT`
4. Optional Environment Variables:
   - `ADMIN_PASSWORD`: Custom password for the `admin` account
   - `SHAZAIN_PASSWORD`: Custom password for the `shazain` account
   - `DEMO_PASSWORD`: Custom password for the `demo` account
   - `SESSION_SECRET`: Custom session encryption key

## License

Private & Confidential - All Rights Reserved.

