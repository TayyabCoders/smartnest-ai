from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple
import numpy as np
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



def _extract_plate_text_v1(image_bgr: np.ndarray, debug_dir: Path = None) -> str:
    ocr = get_ocr()

    debug_dir = debug_dir or Path("uploads/output_debug_v1")
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)

    # ... your preprocessing code stays exactly the same ...
    cv2.imwrite(str(debug_dir / f"{ts}_0_original.jpg"), image_bgr)
    
    # Grayscale
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    cv2.imwrite(str(debug_dir / f"{ts}_1_gray.jpg"), gray)
    
    # Gentle upscale for very small crops
    h, w = gray.shape
    if h < 48 or w < 200:
        scale = max(50/h, 200/w)
        new_w, new_h = int(w * scale), int(h * scale)
        gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        cv2.imwrite(str(debug_dir / f"{ts}_2_resized.jpg"), gray)
    
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
    gray = cv2.morphologyEx(gray, cv2.MORPH_OPEN, kernel)
        
    # Auto brightness correction
    if gray.mean() < 80:
        gamma = 1.6
        table = np.array([(i/255.0)**(1/gamma)*255 for i in range(256)]).astype("uint8")
        gray = cv2.LUT(gray, table)
    
    cv2.imwrite(str(debug_dir / f"{ts}_2b_brightness_fixed.jpg"), gray)
    
    # Denoise BEFORE threshold
    denoised = cv2.bilateralFilter(gray, 5, 30, 30)
    cv2.imwrite(str(debug_dir / f"{ts}_2b_denoised.jpg"), denoised)

    # Contrast stretching
    p_low, p_high = np.percentile(denoised, (1, 99))
    gray = np.clip((gray - p_low) * (255 / (p_high - p_low)), 0, 255).astype(np.uint8)
    cv2.imwrite(str(debug_dir / f"{ts}_2c_contrast_stretched.jpg"), gray)
    
    # Convert to BGR for PaddleOCR
    processed = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.imwrite(str(debug_dir / f"{ts}_7_processed.jpg"), processed)
    
    # OCR
    result = ocr.predict(processed) 
    print(result)
    
    plate_code = ""
    plate_digits = ""

    for r in result:
        rec_texts = r.get("rec_texts", [])
        rec_scores = r.get("rec_scores", [])

        # ---------- SINGLE-LINE PLATE -------------
        if len(rec_texts) == 1:
            raw = str(rec_texts[0]).upper()
            cleaned = re.sub(r"[^A-Z0-9]", "", raw)

            # Letters 2-3 + digits 3-4
            if re.match(r"^[A-Z]{2,3}[0-9]{3,4}$", cleaned):
                return cleaned  # perfect match
            # Else fall through to multiline logic
        # ------------------------------------------

        # ---------- MULTI-LINE PLATE --------------
        for text, score in zip(rec_texts, rec_scores):
            if score is None or np.isnan(score) or float(score) < 0.40:
                continue  # ignore low quality

            raw = str(text).upper()
            cleaned = re.sub(r"[^A-Z0-9]", "", raw)

            # Letters only (2–3)
            if re.match(r"^[A-Z]{2,3}$", cleaned):
                plate_code = cleaned
                continue

            # Digits only (3–4)
            if re.match(r"^[0-9]{3,4}$", cleaned):
                plate_digits = cleaned
                continue

            # Mixed like "LEA2" or "MN14"
            m = re.match(r"^([A-Z]{2,3})([0-9]{1,4})$", cleaned)
            if m:
                letters, digits = m.groups()
                if len(letters) >= 2:
                    plate_code = letters
                if len(digits) >= 3:
                    plate_digits = digits
                continue
        # ------------------------------------------

    # Save processed image for debug
    try:
        output_dir = settings.upload_dir / "outputt"
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"plate_{ts}.jpg"
        cv2.imwrite(str(out_path), processed)
        _logger.info("video.preprocessed.saved", plate=plate_code+plate_digits, path=str(out_path))
    except Exception as e:
        _logger.warning("video.preprocessed.save_failed", error=str(e))

    # Final combined output
    return plate_code + plate_digits

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
                plate_text = _extract_plate_text_v1(crop)

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

def detect_plate_from_image(
    image_path: str,
    snapshots_dir: Path,
    conf: float = 0.45,
) -> Optional[Tuple[str, str]]:
    """
    Detects plate(s) from a single image.
    Returns: (plate_number, snapshot_path)
    """
    logger = _logger.bind(image=image_path)
    yolo = _get_yolo()

    img = cv2.imread(image_path)
    if img is None:
        logger.error("image.open.failed")
        return None

    snapshots_dir.mkdir(parents=True, exist_ok=True)

    results = yolo.predict(source=img, conf=conf, verbose=False)
    if not results:
        return None

    boxes = results[0].boxes
    if boxes is None:
        return None

    for box in boxes:
        x1, y1, x2, y2 = box.xyxy[0]
        x1, y1, x2, y2 = map(int, [x1, y1, x2, y2])

        # Safe crop boundaries
        h, w = img.shape[:2]
        x1 = max(0, min(x1, w - 1))
        x2 = max(1, min(x2, w))
        y1 = max(0, min(y1, h - 1))
        y2 = max(1, min(y2, h))
        if x2 <= x1 or y2 <= y1:
            continue

        crop = img[y1:y2, x1:x2]
        plate_text = _extract_plate_text_v1(crop)

        # Draw box + label
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        if plate_text:
            cv2.putText(img, plate_text, (x1, max(0, y1 - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        if not plate_text:
            continue

        # Save snapshot image
        snap_name = f"{plate_text}_{int(datetime.now().timestamp()*1000)}.jpg"
        snap_path = snapshots_dir / snap_name
        cv2.imwrite(str(snap_path), img)

        logger.info("image.plate.detected", plate=plate_text, snapshot=str(snap_path))
        return plate_text, str(snap_path)

    return None


def save_uploaded_temp(file_bytes: bytes, suffix: str = ".mp4") -> str:
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(file_bytes)
    return tmp_path



    