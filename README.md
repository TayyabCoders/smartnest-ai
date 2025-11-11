# Parking Management System

An automated, camera-based parking management system that tracks vehicle entry/exit, calculates parking duration, and applies fees accordingly. The system uses YOLOv10 for license plate detection and PaddleOCR for text recognition.

## Features

- 🚗 **Automated Vehicle Tracking**: Detects license plates from video files or URLs
- ⏱️ **Free Grace Period**: First 10 minutes of parking are free
- 💰 **Automatic Fee Calculation**: Calculates fees based on parking duration
  - First 10 minutes: Free
  - Every additional 30 minutes (or part thereof): PKR 50
  - Maximum daily cap: PKR 300
- 📸 **Image Storage**: Securely stores entry/exit images and timestamps
- 📊 **Real-time Status**: Get current parking status and fees for any vehicle
- 🔍 **Admin Dashboard**: Access all parking records with filtering and pagination
- 📹 **Video Processing**: Accept video files or URLs for automated plate detection

## Tech Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL
- **ML Models**: 
  - YOLOv10 for license plate detection
  - PaddleOCR for text recognition
- **Image Processing**: OpenCV
- **Package Manager**: uv
- **Containerization**: Docker & Docker Compose

## Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) package manager
- Docker and Docker Compose (for database)
- PostgreSQL 16 (via Docker)

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd "parking system final"
```

### 2. Install Dependencies

Using `uv`:

```bash
uv sync
```

This will install all required dependencies including:
- FastAPI and Uvicorn
- SQLAlchemy and PostgreSQL driver
- OpenCV, PaddleOCR, and YOLOv10
- Other required packages

### 2a. Patch YOLOv10 Loader (PyTorch 2.6+)

If you are using PyTorch 2.6 or newer, patch the vendor file `app/yolov10/ultralytics/nn/tasks.py` so checkpoint loading works (PyTorch 2.6 defaults to `weights_only=True`). Add the helper below right after line 724 (`def torch_safe_load` section, before the `try:`):

Path:
```
app/yolov10/ultralytics/nn/tasks.py
```

Snippet to insert:

```python
    # Helper function to load with PyTorch 2.6+ compatibility
    def _load_checkpoint(file_path):
        """Load checkpoint with weights_only=False for PyTorch 2.6+ compatibility."""
        import inspect

        # Check if torch.load supports weights_only parameter (PyTorch 2.4+)
        sig = inspect.signature(torch.load)
        supports_weights_only = "weights_only" in sig.parameters

        if supports_weights_only:
            # PyTorch 2.4+: explicitly set weights_only=False to allow custom classes
            # This fixes the issue where PyTorch 2.6+ defaults to weights_only=True
            # which blocks loading models with custom Ultralytics classes
            return torch.load(file_path, map_location="cpu", weights_only=False)
        else:
            # PyTorch < 2.4: weights_only parameter doesn't exist, use standard load
            return torch.load(file_path, map_location="cpu")
```

The remainder of the function (`try: ...`) stays the same, but change calls to `torch.load` within the function to use `_load_checkpoint(...)` if you have not already.

### 3. Start PostgreSQL Database

Start the PostgreSQL database and Adminer (database management UI) using Docker Compose:

```bash
docker compose up -d db adminer
```

This will:
- Start PostgreSQL on port `5433` (to avoid conflicts with local PostgreSQL)
- Start Adminer on port `8090` (access at http://localhost:8090)
- Create the database `parkingSystem_db` automatically

**Database Credentials:**
- User: `postgres`
- Password: `postgres`
- Database: `parkingSystem_db`
- Host: `localhost`
- Port: `5433`

### 4. Configure Settings

The application uses `config/settings.toml` for configuration. Default settings are already configured, but you can modify:

```toml
[app]
name = "Parking System Backend"
environment = "development"
host = "0.0.0.0"
port = 8000

[logging]
level = "INFO"
json = true

[storage]
upload_dir = "uploads"

[database]
user = "postgres"
password = "postgres"
host = "localhost"
port = 5433
name = "parkingSystem_db"
pool_size = 10
max_overflow = 10
```

### 5. Run the Application

Start the FastAPI server:

```bash
uv run uvicorn app.services.main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at:
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs (Swagger UI)
- **ReDoc**: http://localhost:8000/redoc

## API Documentation

### Base URL

```
http://localhost:8000
```

### Endpoints

#### 1. Register Vehicle Entry

**POST** `/parking/entry`

Register a vehicle entry. You can provide either a plate number directly, or a video file/URL for automatic detection.

**Request (multipart/form-data):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `plate_number` | string | No* | Vehicle license plate number (e.g., "ABC-123") |
| `video_file` | file | No* | Video file to process for plate detection |
| `video_url` | string | No* | URL to video file for plate detection |

*At least one of `plate_number`, `video_file`, or `video_url` must be provided.

**Example with plate number:**
```bash
curl -X POST http://localhost:8000/parking/entry \
  -F plate_number=ABC-123
```

**Example with video file:**
```bash
curl -X POST http://localhost:8000/parking/entry \
  -F video_file=@data/carLicence1.mp4
```

**Example with video URL:**
```bash
curl -X POST http://localhost:8000/parking/entry \
  -F video_url=https://example.com/test.mp4
```

**Response:**
```json
{
  "plate_number": "ABC-123",
  "entry_time": "2025-01-11T10:05:00.000Z",
  "status": "IN",
  "message": "Entry recorded successfully"
}
```

#### 2. Register Vehicle Exit

**POST** `/parking/exit`

Register a vehicle exit and calculate parking fees.

**Request (multipart/form-data):**

Same fields as entry endpoint.

**Example:**
```bash
curl -X POST http://localhost:8000/parking/exit \
  -F plate_number=ABC-123
```

**Response:**
```json
{
  "plate_number": "ABC-123",
  "entry_time": "2025-01-11T10:05:00.000Z",
  "exit_time": "2025-01-11T11:30:00.000Z",
  "duration_minutes": 85,
  "fee": 100,
  "message": "Exit recorded successfully. Please pay PKR 100."
}
```

#### 3. Get Vehicle Status

**GET** `/parking/status/{plate_number}`

Get the current status and fee for a vehicle.

**Example:**
```bash
curl http://localhost:8000/parking/status/ABC-123
```

**Response (Vehicle IN):**
```json
{
  "plate_number": "ABC-123",
  "status": "IN",
  "entry_time": "2025-01-11T10:05:00.000Z",
  "elapsed_minutes": 45,
  "current_fee": 50,
  "grace_period_remaining_minutes": 0
}
```

**Response (Vehicle OUT):**
```json
{
  "plate_number": "ABC-123",
  "status": "OUT",
  "exit_time": "2025-01-11T11:30:00.000Z",
  "total_fee_paid": 100
}
```

#### 4. Get All Records

**GET** `/parking/all`

Get all parking records with filtering and pagination.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | integer | 1 | Page number (≥ 1) |
| `limit` | integer | 50 | Records per page (1-200) |
| `status_filter` | string | None | Filter by status: "IN" or "OUT" |
| `date_filter` | string | None | Filter by date: "YYYY-MM-DD" |

**Example:**
```bash
curl "http://localhost:8000/parking/all?page=1&limit=50&status_filter=IN&date_filter=2025-01-11"
```

**Response:**
```json
{
  "total": 150,
  "page": 1,
  "limit": 50,
  "data": [
    {
      "plate_number": "ABC-123",
      "status": "IN",
      "entry_time": "2025-01-11T10:05:00.000Z",
      "exit_time": null,
      "duration_minutes": null,
      "fee": null,
      "entry_image_url": null,
      "exit_image_url": null,
      "elapsed_minutes": 45,
      "current_fee": 50
    }
  ]
}
```

## Project Structure

```
parking system final/
├── app/
│   ├── core/
│   │   ├── config.py          # Configuration management
│   │   └── logging.py          # Structured logging setup
│   ├── db/
│   │   └── session.py          # Database session management
│   ├── models/
│   │   └── parking_records.py # SQLAlchemy models
│   ├── routes/
│   │   └── parking_routes.py  # API endpoints
│   ├── schemas/
│   │   └── parking.py         # Pydantic schemas
│   ├── services/
│   │   ├── main.py            # FastAPI application
│   │   ├── parking_service.py # Fee calculation logic
│   │   └── video_processing.py # Video processing & plate detection
│   ├── weights/
│   │   └── best.pt            # YOLOv10 model weights
│   └── yolov10/               # YOLOv10 library
├── config/
│   └── settings.toml          # Application configuration
├── data/                      # Test videos and images
├── uploads/                    # Uploaded files and snapshots (auto-created)
├── docker-compose.yml         # Docker services configuration
└── pyproject.toml             # Project dependencies
```

## Fee Calculation

The parking fee is calculated based on the following rules:

1. **Free Period**: First 10 minutes are free
2. **Charging Blocks**: Every additional 30 minutes (or part thereof) costs PKR 50
3. **Daily Cap**: Maximum fee per day is PKR 300

**Examples:**
- 5 minutes: PKR 0 (within grace period)
- 15 minutes: PKR 50 (5 minutes chargeable = 1 block)
- 45 minutes: PKR 50 (35 minutes chargeable = 1 block)
- 75 minutes: PKR 100 (65 minutes chargeable = 2 blocks)
- 500 minutes: PKR 300 (capped at maximum)

## Video Processing

The system can automatically detect license plates from video files:

1. Upload a video file or provide a video URL
2. The system processes the video frame by frame
3. YOLOv10 detects license plate regions
4. PaddleOCR extracts the plate text
5. The first detected plate is used for entry/exit registration
6. A snapshot of the detected frame is saved to `uploads/snapshots/`

**Supported Video Formats:**
- MP4, AVI, MOV, and other formats supported by OpenCV

## Database

The system uses PostgreSQL to store parking records. The database schema includes:

- `parking_records` table with fields:
  - `id`: Primary key
  - `plate_number`: License plate number (indexed)
  - `entry_time`: Entry timestamp
  - `exit_time`: Exit timestamp (nullable)
  - `fees`: Calculated fee (nullable)
  - `entry_image_path`: Path to entry snapshot
  - `exit_image_path`: Path to exit snapshot
  - `status`: "IN" or "OUT"
  - `created_at`, `updated_at`: Timestamps

**Access Database:**
- Adminer UI: http://localhost:8090
- Connection: Use credentials from `config/settings.toml`

## Logging

The application uses structured logging with `structlog`. Logs are output in JSON format by default and include:

- Request/response logging
- Video processing events
- Database operations
- Error tracking

Log level can be configured in `config/settings.toml`.

## Development

### Code Formatting

The project uses `black` and `ruff` for code formatting and linting:

```bash
uv run black app/
uv run ruff check app/
```

### Running Tests

(Add test commands when tests are implemented)

## Troubleshooting

### Port Already in Use

If you get a "port is already allocated" error:

1. Check if PostgreSQL is running locally on port 5432
2. Either stop the local PostgreSQL service, or
3. Change the port in `docker-compose.yml` and `config/settings.toml`

### Video Processing Fails

- Ensure the video file is a valid video format
- Check that `app/weights/best.pt` exists
- Verify PaddleOCR models are downloaded (first run may take time)

### Database Connection Issues

- Ensure Docker containers are running: `docker compose ps`
- Check database credentials in `config/settings.toml`
- Verify PostgreSQL is healthy: `docker compose logs db`

## License

[Add your license information here]

## Author

Rasil Abro

## Contributing

[Add contribution guidelines if applicable]

