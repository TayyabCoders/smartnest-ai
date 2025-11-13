from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import cv2
from ultralytics import YOLOv10
import numpy as np
from app.services.ocr import get_ocr

from app.core.config import settings
from app.core.logging import get_logger

_logger = get_logger(__name__)

# Lazy singletons to avoid heavy reinitialization per request
_yolo_model: Optional[YOLOv10] = None


def _get_yolo() -> YOLOv10:
    global _yolo_model
    if _yolo_model is None:
        weights_path = Path("app/weights/best.pt")
        _logger.info("video.yolo.load", weights=str(weights_path))
        _yolo_model = YOLOv10(str(weights_path))
    return _yolo_model


def _clean_plate_text(text: str) -> str:
    pattern = re.compile(r"[\W_]+")
    text = pattern.sub("", text)
    text = text.replace("O", "0")
    return text.upper()


def _extract_plate_text(image_bgr: np.ndarray) -> str:
    ocr = get_ocr()

    # ---------- LIGHT PREPROCESSING ----------
    # Convert to grayscale for contrast improvement
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    # --- 3. Resize small plates (helps OCR) ---
    h, w = gray.shape
    if min(h, w) < 100:
        scale = 2 if min(h, w) < 60 else 1
        if scale > 1:
            gray = cv2.resize(gray, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4)
            image_bgr = cv2.resize(image_bgr, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4)
            _logger.info("image.resized_for_ocr", original_size=(w, h), new_size=(w * scale, h * scale))

    # Mild noise reduction (keeps edges)
    denoised = cv2.bilateralFilter(gray, 9, 75, 75)

    # Slight CLAHE to boost contrast
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)

    # Convert back to 3-channel for PaddleOCR
    processed = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
    # ------------------------------------------

    result = ocr.predict(processed)

    for r in result:
        rec_texts = r.get("rec_texts", [])
        rec_scores = r.get("rec_scores", [])
        for detected_text, score in zip(rec_texts, rec_scores):
            if np.isnan(score):
                continue
            if float(score) >= 0.6:
                cleaned = _clean_plate_text(str(detected_text))
                if cleaned:
                    # Save the preprocessed plate image to uploads/output
                    try:
                        output_dir = settings.upload_dir / "outputt"
                        output_dir.mkdir(parents=True, exist_ok=True)
                        ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                        out_path = output_dir / f"{cleaned}_{ts_ms}.jpg"
                        cv2.imwrite(str(out_path), processed)
                        _logger.info("video.preprocessed.saved", plate=cleaned, path=str(out_path))
                    except Exception as e:
                        _logger.warning("video.preprocessed.save_failed", error=str(e))
                    return cleaned
    return ""



def detect_first_plate_and_snapshot(
    video_path: str,
    snapshots_dir: Path,
    conf: float = 0.45,
) -> Optional[Tuple[str, datetime, str]]:
    """
    Returns (plate_number, timestamp_utc, snapshot_path) for the first detected plate.
    """
    logger = _logger.bind(video=video_path)
    yolo = _get_yolo()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error("video.open.failed")
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_idx = 0
    plate_found: Optional[Tuple[str, datetime, str]] = None

    snapshots_dir.mkdir(parents=True, exist_ok=True)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame_idx += 1

            results = yolo.predict(source=frame, conf=conf, verbose=False)
            if not results:
                continue
            boxes = results[0].boxes
            if boxes is None:
                continue

            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0]
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                # Safe crop
                h, w = frame.shape[:2]
                x1 = max(0, min(x1, w - 1))
                x2 = max(1, min(x2, w))
                y1 = max(0, min(y1, h - 1))
                y2 = max(1, min(y2, h))
                if x2 <= x1 or y2 <= y1:
                    continue
                crop = frame[y1:y2, x1:x2]
                plate_text = _extract_plate_text(crop)

                # Draw bounding box and text on frame (for snapshot only)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                if plate_text:
                    cv2.putText(frame, plate_text, (x1, max(0, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

                if not plate_text:
                    continue

                # Save snapshot and compute timestamp
                ts_sec = frame_idx / fps
                ts_utc = datetime.now(timezone.utc)
                snap_name = f"{plate_text}_{int(ts_sec*1000)}.jpg"
                snap_path = snapshots_dir / snap_name
                cv2.imwrite(str(snap_path), frame)

                logger.info("video.plate.detected", plate=plate_text, snapshot=str(snap_path))
                plate_found = (plate_text, ts_utc, str(snap_path))
                return plate_found
    finally:
        cap.release()
        # No cv2.destroyAllWindows() needed since no windows were shown

    logger.info("video.plate.not_found")
    return None


def save_uploaded_temp(file_bytes: bytes, suffix: str = ".mp4") -> str:
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(file_bytes)
    return tmp_path



    