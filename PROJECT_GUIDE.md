# Parking Management System - Project Guide

This document provides a theoretical overview and a step-by-step guide to running the Parking Management System.

---

## 1. Project Overview (Theoretical)
The **Parking Management System** is an automated backend application designed to track vehicles entering and exiting a parking facility using Computer Vision (AI).

### How it Works (The Workflow)
1.  **Entry Phase**:
    *   A vehicle arrives. The system receives either a **Plate Number** manually or a **File (Video or Image)**.
    *   **AI (Invisible Magic)**: If you upload a file, the system "looks" at it.
        *   **Step A (Detection)**: It uses **YOLOv10** to find the box where the License Plate is.
        *   **Step B (Reading)**: It uses **PaddleOCR** to read the letters and numbers inside that box.
    *   **Automatic Results**: You don't need to tell the system the number; it detects it automatically from the image/video.
    *   **CNIC Verification**: A CNIC (Number or Image) is also required for security.
    *   **Database Entry**: A record is created with the detected plate, actual time, and a snapshot for proof.

2.  **Stay Phase**:
    *   The vehicle is marked as `IN`.
    *   You can query the status of any vehicle to see how long it has been parked and the current accrued fee.

3.  **Exit Phase**:
    *   The vehicle leaves. The system again detects the plate and verifies the CNIC matches the entry record.
    *   **Fee Calculation**: The system calculates the total stay duration and applies pricing rules.
    *   **Database Update**: The record is updated to `OUT`, and the final fee is saved.

---

## 2. Technology Stack
*   **Web Framework**: **FastAPI** (Python) - Handles the API requests and logic.
*   **AI / Computer Vision**:
    *   **YOLOv10**: Used for detecting the bounding box of a license plate in an image or video.
    *   **PaddleOCR**: Used for recognizing the alphanumeric characters on the detected plate and CNIC.
*   **Database**: **PostgreSQL** - Stores all parking records, user info, and CNIC data.
*   **DevOps**: **Docker & Docker Compose** - Used to run the database easily.
*   **Package Manager**: **uv** - A modern, fast Python package manager.

---

## 3. Implementation Status (Working vs Not)

### What is Working:
*   ✅ **Authentication**: Login and JWT token generation are implemented.
*   ✅ **Parking Logic**: Registering entry/exit, calculating fees, and tracking status.
*   ✅ **Fee Calculation**: Logic is in `app/services/parking_service.py`.
*   ✅ **AI Integration**: The `video_processing.py` script is ready to use YOLO and PaddleOCR.
*   ✅ **Database Schema**: SQLAlchemy models are defined for Users, Parking Records, and CNIC records.

### Points to Note (Discrepancies):
*   ⚠️ **Fee Rules**: There is a mismatch between the `README.md` and the code:
    *   `README.md`: 10 mins free, PKR 50 per 30 mins, max PKR 300.
    *   `Code (parking_service.py)`: 10 mins free, **PKR 100** per 30 mins, max **PKR 800**.
*   ⚠️ **Dependencies**: The `pyproject.toml` is missing `ultralytics` (required for YOLOv10). You may need to run `pip install ultralytics` or update the `uv` environment.

---

## 4. How to Run the Project

### Step 1: Prepare the Environment
1.  Ensure you have **Python 3.11+** and **Docker** installed.
2.  Install `uv` if you haven't: `pip install uv`.

### Step 2: Start the Database
Run the following command to start PostgreSQL:
```bash
docker compose up -d db
```

### Step 3: Install Dependencies
```bash
uv sync
```
*(Note: If it fails due to missing packages like `ultralytics`, run `uv pip install ultralytics`)*

### **Important: Support for Images**
Although the field is named `video_file`, the system **automatically supports images** (like `.jpg` or `.png`). If you upload an image of a car to the `video_file` field, it will detect the plate exactly like it does for a video.

### Step 4: Setup a User (Optional but recommended)
Run the script to create an admin user so you can log in:
```bash
uv run python scripts/create_user.py
```

### Step 5: Start the Application
```bash
uv run uvicorn app.services.main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 6: Access the Documentation
Once running, go to:
*   **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
*   You can test the `/auth/login` and then the `/parking/entry` endpoints directly from there.

---

## 5. Directory Structure at a Glance
*   `app/routes/`: API endpoint definitions (Auth & Parking).
*   `app/services/`: Core logic (Fee calculation, AI/Video processing).
*   `app/models/`: Database tables.
*   `app/weights/`: The AI "brain" (`best.pt` file for YOLO).
*   `config/`: App settings (DB ports, secrets).
