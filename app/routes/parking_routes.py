from datetime import datetime, timezone
from typing import Optional

import httpx
from pathlib import Path
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.schemas import (
    AllRecordsResponse,
    EntryResponse,
    ExitResponse,
    Record,
    StatusResponse,
)
from app.services.parking_service import compute_fee_minutes
from app.db.session import get_db
from app.models.parking_records import ParkingRecord
from app.models.cnic_records import CnicRecord
from app.core.logging import get_logger
from app.core.config import settings
from app.services.video_processing import (
    detect_first_plate_and_snapshot,
    save_uploaded_temp,
)
from app.core.security import get_current_user
from app.services.cnic_ocr import (
    extract_cnic_number_from_image_bytes,
    extract_cnic_fields_from_image_bytes,
    normalize_cnic,
)


router = APIRouter(prefix="/parking", tags=["parking"], dependencies=[Depends(get_current_user)])
logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_public_url(path: Optional[str], request: Request) -> Optional[str]:
    if not path:
        return None
    rel = str(path).replace("\\", "/").lstrip("/")
    base = str(request.base_url).rstrip("/")
    return f"{base}/{rel}"

@router.post("/entry", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def register_entry(
    request: Request,
    db: Session = Depends(get_db),
    plate_number: Optional[str] = Form(None),
    video_file: Optional[UploadFile] = File(None),
    video_url: Optional[str] = Form(None),
    cnic_number: Optional[str] = Form(None),
    cnic_image: Optional[UploadFile] = File(None),
) -> EntryResponse:
    logger.info(
        "entry.request.received",
        plate=plate_number,
        video_file=bool(video_file),
        video_url=video_url,
        cnic_number_provided=bool(cnic_number),
        cnic_image_provided=bool(cnic_image),
    )

    detected_plate = plate_number
    entry_image_path: Optional[str] = None
    detected_cnic: Optional[str] = None
    extracted_fields: Optional[dict] = None

    # Detect/validate CNIC first (required)
    if cnic_number:
        normalized = normalize_cnic(cnic_number)
        if not normalized:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid CNIC format")
        detected_cnic = normalized
    elif cnic_image is not None:
        try:
            img_bytes = cnic_image.file.read()
        finally:
            try:
                cnic_image.file.close()
            except Exception:
                pass
        # Extract all fields from the image
        extracted_fields = extract_cnic_fields_from_image_bytes(img_bytes)
        detected_cnic = (extracted_fields or {}).get("cnic_number") or None
        if not detected_cnic:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No valid CNIC detected in image")
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide cnic_number or cnic_image")

    # If no plate provided, try to detect from video
    if not detected_plate:
        tmp_path = None
        try:
            if video_file is not None:
                file_bytes = video_file.file.read()
                tmp_path = save_uploaded_temp(file_bytes, suffix=Path(video_file.filename or "video.mp4").suffix)
            elif video_url:
                with httpx.Client(timeout=60) as client:
                    resp = client.get(video_url)
                    resp.raise_for_status()
                    tmp_path = save_uploaded_temp(resp.content, suffix=".mp4")
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide plate_number, video_file, or video_url")

            snapshots_dir = settings.upload_dir / "snapshots"
            res = detect_first_plate_and_snapshot(tmp_path, snapshots_dir)
            if not res:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No plate detected in video")
            detected_plate, _ts, entry_image_path = res
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    # Check if already IN
    existing = (
        db.query(ParkingRecord)
        .filter(ParkingRecord.plate_number == detected_plate, ParkingRecord.status == "IN")
        .first()
    )
    if existing:
        logger.warning("entry.conflict", plate=detected_plate)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vehicle already inside")

    # Ensure CNIC exists in cnic_records and upsert known fields
    cnic_row = db.query(CnicRecord).filter(CnicRecord.cnic_number == detected_cnic).first()
    if not cnic_row:
        cnic_row = CnicRecord(cnic_number=detected_cnic)
        db.add(cnic_row)
    # If we extracted more fields from the image, persist them
    if extracted_fields:
        if extracted_fields.get("name"):
            cnic_row.name = extracted_fields.get("name")  # type: ignore[assignment]
        if extracted_fields.get("father_name"):
            cnic_row.father_name = extracted_fields.get("father_name")  # type: ignore[assignment]
        if extracted_fields.get("gender"):
            cnic_row.gender = extracted_fields.get("gender")  # type: ignore[assignment]
        if extracted_fields.get("country_of_stay"):
            cnic_row.country_of_stay = extracted_fields.get("country_of_stay")  # type: ignore[assignment]
        if extracted_fields.get("date_of_birth"):
            cnic_row.date_of_birth = extracted_fields.get("date_of_birth")  # type: ignore[assignment]
        if extracted_fields.get("date_of_issue"):
            cnic_row.date_of_issue = extracted_fields.get("date_of_issue")  # type: ignore[assignment]
        if extracted_fields.get("date_of_expiry"):
            cnic_row.date_of_expiry = extracted_fields.get("date_of_expiry")  # type: ignore[assignment]

    rec = ParkingRecord(
        plate_number=detected_plate,
        cnic_number=detected_cnic or "",
        status="IN",
        entry_time=_now(),
        entry_image_path=entry_image_path,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    logger.info("entry.recorded", plate=detected_plate, id=rec.id)
    return EntryResponse(
        plate_number=detected_plate,
        cnic_number=detected_cnic or "",
        entry_image_url=_to_public_url(entry_image_path, request),  # type: ignore[arg-type]
        entry_time=rec.entry_time,
        status="IN",
        message="Entry recorded successfully",
    )


@router.post("/exit", response_model=ExitResponse)
def register_exit(
    request: Request,
    db: Session = Depends(get_db),
    plate_number: Optional[str] = Form(None),
    video_file: Optional[UploadFile] = File(None),
    video_url: Optional[str] = Form(None),
    cnic_number: Optional[str] = Form(None),
    cnic_image: Optional[UploadFile] = File(None),
) -> ExitResponse:
    logger.info(
        "exit.request.received",
        plate=plate_number,
        video_file=bool(video_file),
        video_url=video_url,
        cnic_number_provided=bool(cnic_number),
        cnic_image_provided=bool(cnic_image),
    )

    detected_plate = plate_number
    exit_image_path: Optional[str] = None
    detected_cnic: Optional[str] = None

    # Require and verify CNIC at exit
    if cnic_number:
        normalized = normalize_cnic(cnic_number)
        if not normalized:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid CNIC format")
        detected_cnic = normalized
    elif cnic_image is not None:
        try:
            img_bytes = cnic_image.file.read()
        finally:
            try:
                cnic_image.file.close()
            except Exception:
                pass
        detected_cnic = extract_cnic_number_from_image_bytes(img_bytes) or None
        if not detected_cnic:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No valid CNIC detected in image")
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide cnic_number or cnic_image")

    if not detected_plate:
        tmp_path = None
        try:
            if video_file is not None:
                file_bytes = video_file.file.read()
                tmp_path = save_uploaded_temp(file_bytes, suffix=Path(video_file.filename or "video.mp4").suffix)
            elif video_url:
                with httpx.Client(timeout=60) as client:
                    resp = client.get(video_url)
                    resp.raise_for_status()
                    tmp_path = save_uploaded_temp(resp.content, suffix=".mp4")
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide plate_number, video_file, or video_url")

            snapshots_dir = settings.upload_dir / "snapshots"
            res = detect_first_plate_and_snapshot(tmp_path, snapshots_dir)
            if not res:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No plate detected in video")
            detected_plate, _ts, exit_image_path = res
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    rec = (
        db.query(ParkingRecord)
        .filter(ParkingRecord.plate_number == detected_plate, ParkingRecord.status == "IN")
        .first()
    )
    if not rec:
        logger.warning("exit.not_found", plate=detected_plate)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plate not found or already exited")

    # CNIC must match the one recorded at entry time
    if (rec.cnic_number or "") != (detected_cnic or ""):
        logger.warning(
            "exit.cnic_mismatch", plate=detected_plate, expected=rec.cnic_number, provided=detected_cnic
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CNIC does not match the entry record")

    exit_time = _now()
    elapsed = int((exit_time - rec.entry_time).total_seconds() // 60)
    fee = compute_fee_minutes(elapsed)

    rec.status = "OUT"
    rec.exit_time = exit_time
    rec.fee = fee
    rec.exit_image_path = exit_image_path
    db.add(rec)
    db.commit()
    db.refresh(rec)

    logger.info("exit.recorded", plate=detected_plate, id=rec.id, fee=fee)
    return ExitResponse(
        plate_number=detected_plate,
        entry_time=rec.entry_time,
        cnic_number=rec.cnic_number,
        exit_image_url=_to_public_url(exit_image_path, request),  # type: ignore[arg-type]
        exit_time=rec.exit_time,  # type: ignore[arg-type]
        duration_minutes=elapsed,
        fee=fee,
        message=f"Exit recorded successfully. Please pay PKR {fee}.",
    )


@router.get("/status/{plate_number}", response_model=StatusResponse)
def get_status(plate_number: str, db: Session = Depends(get_db)) -> StatusResponse:
    rec = (
        db.query(ParkingRecord)
        .filter(ParkingRecord.plate_number == plate_number)
        .order_by(ParkingRecord.entry_time.desc())
        .first()
    )
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plate not found")

    if rec.status == "IN":
        now = _now()
        elapsed = int((now - rec.entry_time).total_seconds() // 60)
        fee_now = compute_fee_minutes(elapsed)
        grace_left = max(0, 10 - elapsed)
        return StatusResponse(
            plate_number=plate_number,
            status="IN",
            entry_time=rec.entry_time,
            elapsed_minutes=elapsed,
            current_fee=fee_now,
            grace_period_remaining_minutes=grace_left,
        )

    return StatusResponse(
        plate_number=plate_number,
        status="OUT",
        exit_time=rec.exit_time,
        total_fee_paid=int(rec.fee or 0),
    )


@router.get("/all", response_model=AllRecordsResponse)
def get_all(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status_filter: Optional[str] = Query(None, regex="^(IN|OUT)$"),
    date_filter: Optional[str] = Query(None, description="YYYY-MM-DD"),
) -> AllRecordsResponse:
    from sqlalchemy import func

    q = db.query(ParkingRecord)
    if status_filter:
        q = q.filter(ParkingRecord.status == status_filter)
    if date_filter:
        try:
            y, m, d = map(int, date_filter.split("-"))
            date_iso = f"{y:04d}-{m:02d}-{d:02d}"
            # Postgres friendly date match
            q = q.filter(func.to_char(ParkingRecord.entry_time, "YYYY-MM-DD") == date_iso)
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format, expected YYYY-MM-DD")

    total = q.count()
    items = (
        q.order_by(ParkingRecord.entry_time.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    data = []
    for r in items:
        elapsed = None
        current_fee = None
        if r.status == "IN":
            elapsed = int((_now() - r.entry_time).total_seconds() // 60)
            current_fee = compute_fee_minutes(elapsed)
        data.append(
            Record(
                plate_number=r.plate_number,
                status=r.status,  # type: ignore[arg-type]
                entry_time=r.entry_time,
                exit_time=r.exit_time,
                duration_minutes=(
                    int((r.exit_time - r.entry_time).total_seconds() // 60) if r.exit_time else None
                ),
                fee=int(r.fee) if r.fee is not None else None,
                entry_image_url=None,
                exit_image_url=None,
                elapsed_minutes=elapsed,
                current_fee=current_fee,
            )
        )

    return AllRecordsResponse(total=total, page=page, limit=limit, data=data)




