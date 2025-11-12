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
from app.core.logging import get_logger
from app.core.config import settings
from app.services.video_processing import (
    detect_first_plate_and_snapshot,
    save_uploaded_temp,
)
from app.core.security import get_current_user


router = APIRouter(prefix="/parking", tags=["parking"], dependencies=[Depends(get_current_user)])
logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)

@router.post("/entry", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def register_entry(
    db: Session = Depends(get_db),
    plate_number: Optional[str] = Form(None),
    video_file: Optional[UploadFile] = File(None),
    video_url: Optional[str] = Form(None),
) -> EntryResponse:
    logger.info("entry.request.received", plate=plate_number, video_file=bool(video_file), video_url=video_url)

    detected_plate = plate_number
    entry_image_path: Optional[str] = None

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

    rec = ParkingRecord(
        plate_number=detected_plate,
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
        entry_time=rec.entry_time,
        status="IN",
        message="Entry recorded successfully",
    )


@router.post("/exit", response_model=ExitResponse)
def register_exit(
    db: Session = Depends(get_db),
    plate_number: Optional[str] = Form(None),
    video_file: Optional[UploadFile] = File(None),
    video_url: Optional[str] = Form(None),
) -> ExitResponse:
    logger.info("exit.request.received", plate=plate_number, video_file=bool(video_file), video_url=video_url)

    detected_plate = plate_number
    exit_image_path: Optional[str] = None

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




