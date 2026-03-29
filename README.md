# 🎓 CV Attendance System

> Automated attendance tracking using Computer Vision with PTZ camera, AI-powered scan planning, and an Excel-style management dashboard.

---

## 📑 Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Running the System](#running-the-system)
- [API Endpoints](#api-endpoints)
- [Hardware Compatibility](#hardware-compatibility)
- [License](#license)

---

## Overview

```
PTZ Camera → Frame Capture → Face Detection → Face Recognition
    → [Recognized]    → attendance_records (present)
    → [Unrecognized]  → unknown_faces queue → Admin verify → attendance_records
```

**Core Workflow:**
1. PTZ camera automatically scans the classroom following an AI-computed schedule based on enrollment size
2. Faces are detected and recognized using InsightFace (ArcFace 512-dim embeddings) with pgvector similarity search
3. Unrecognized faces are queued for manual admin verification (with DBSCAN clustering to group same-person detections)
4. Attendance is displayed as an Excel-like pivot table (students × session dates) with export support

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | Python · FastAPI |
| CV Pipeline | OpenCV · InsightFace (SCRFD detection + ArcFace recognition) |
| Liveness Detection | ONNX model + Heuristic fallback |
| AI Inference Runtime | ONNX Runtime (TensorRT / CUDA / CPU auto-detect) |
| PTZ Control | ONVIF (zeep) + RTSP (OpenCV) |
| Database | PostgreSQL + pgvector extension |
| Task Queue | Celery + Redis |
| Frontend | React + TypeScript + Ant Design + Vite |
| Export | openpyxl (styled Excel export) |
| Auth | JWT (python-jose) + bcrypt |

---

## Project Structure

```
cv-attendance/
├── .env.example              # Environment variables template
├── .gitignore
├── docker-compose.yml        # 5 services: db, redis, backend, worker, frontend
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/              # Database migrations (Alembic)
│   ├── models/               # Model weights directory (auto-download)
│   ├── tests/
│   └── app/
│       ├── main.py           # FastAPI entry point (factory pattern)
│       ├── config.py         # Pydantic Settings (env-based config)
│       ├── database.py       # SQLAlchemy async engine (asyncpg)
│       ├── models/           # 7 ORM models (User, Class, Student, FaceEmbedding, Session, AttendanceRecord, UnknownFace)
│       ├── schemas/          # Pydantic request/response schemas
│       ├── api/              # 7 API routers (auth, classes, students, sessions, attendance, unknown_faces, ptz)
│       ├── cv/               # CV pipeline (detector, recognizer, liveness, clustering)
│       ├── ptz/              # PTZ camera controller + room zone configs
│       ├── agent/            # AI scan planner + coverage checker
│       └── tasks/            # Celery async tasks (scan orchestration, frame processing)
└── frontend/
    ├── Dockerfile            # Multi-stage: Node build + Nginx serve
    ├── package.json
    ├── vite.config.ts
    ├── index.html
    └── src/
        ├── App.tsx           # Root component (Ant Design theme, routing, auth guard)
        ├── index.css         # Global styles (Inter font, CSS tokens, Ant Design overrides)
        ├── api/              # Axios client + typed API functions
        ├── components/       # Reusable: Layout, AttendanceTable, FaceCard, ScanPlanBadge
        └── pages/            # Login, Dashboard, AttendanceSheet, Sessions, UnknownQueue, Students
```

---

## Installation

### Prerequisites
- **Docker + Docker Compose** (recommended), OR
- Python 3.11+, Node.js 20+, PostgreSQL 16 (with pgvector), Redis 7

### Setup
```bash
git clone https://github.com/<your-username>/cv-attendance.git
cd cv-attendance
cp .env.example .env
# Edit .env: set DATABASE_URL, SECRET_KEY, PTZ camera credentials
```

---

## Running the System

### Option 1: Docker Compose (Recommended)
```bash
docker compose up -d
# Frontend:  http://localhost:3000
# API Docs:  http://localhost:8000/docs
```

To enable GPU access (Jetson / RTX), uncomment the `deploy` section in `docker-compose.yml` under the `worker` service.

### Option 2: Development Mode

**Backend:**
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Initialize database
alembic revision --autogenerate -m "initial"
alembic upgrade head

# Start server
uvicorn app.main:app --reload --port 8000
```

**Celery Worker:**
```bash
celery -A app.tasks worker --loglevel=info
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

### Option 3: Jetson Deployment
```bash
# Install ONNX Runtime GPU for Jetson (from NVIDIA Jetson repo)
pip install onnxruntime-gpu
# The system auto-detects TensorRT provider
```

---

## API Endpoints

### Auth
| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/register` | Create account |
| `POST` | `/auth/login` | Login (returns JWT) |
| `GET` | `/auth/me` | Current user info |

### Classes
| Method | Path | Description |
|---|---|---|
| `GET` | `/classes` | List classes |
| `POST` | `/classes` | Create class |
| `GET/PATCH/DELETE` | `/classes/{id}` | CRUD single class |

### Students
| Method | Path | Description |
|---|---|---|
| `GET` | `/students` | List students |
| `POST` | `/students/import?class_id=` | Import from Excel (.xlsx) |
| `POST` | `/students/{id}/enroll-face` | Enroll face (3-5 images) |
| `DELETE` | `/students/{id}/embedding` | Delete face embeddings |

### Sessions
| Method | Path | Description |
|---|---|---|
| `GET/POST` | `/sessions` | List / Create sessions |
| `POST` | `/sessions/{id}/start-scan` | Start PTZ attendance scan |
| `GET` | `/sessions/{id}/scan-plan` | View scan plan |
| `GET` | `/sessions/{id}/coverage` | Recognition coverage % |

### Attendance
| Method | Path | Description |
|---|---|---|
| `GET` | `/attendance/sheet` | Pivot table data |
| `GET` | `/attendance/export` | Export styled .xlsx file |

### Unknown Faces
| Method | Path | Description |
|---|---|---|
| `GET` | `/unknown-faces` | Unrecognized faces queue |
| `PATCH` | `/unknown-faces/{id}/match` | Assign to student |
| `PATCH` | `/unknown-faces/{id}/stranger` | Mark as stranger |
| `PATCH` | `/unknown-faces/{id}/false-positive` | Mark as false positive |
| `POST` | `/unknown-faces/bulk-resolve` | Resolve entire cluster |

### PTZ Camera
| Method | Path | Description |
|---|---|---|
| `GET` | `/ptz/status` | Camera connection status |
| `GET` | `/ptz/presets` | List presets |
| `POST` | `/ptz/move` | Move to preset |
| `POST` | `/ptz/capture` | Capture test frame |

---

## Hardware Compatibility

| Platform | Architecture | ONNX Provider | Detection |
|---|---|---|---|
| **NVIDIA Jetson** (Nano/Xavier/Orin) | ARM64 | `TensorrtExecutionProvider` | `/proc/device-tree/model` |
| **PC with RTX GPU** (3060/4090…) | x86_64 | `CUDAExecutionProvider` | `nvidia-smi` check |
| **CPU only** | any | `CPUExecutionProvider` | Always available |

Provider chain is automatic: **TensorRT → CUDA → CPU**. Override via environment variable:
```env
ONNX_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider
```

---

## License

MIT
# Bachelor-Final-Project
