from __future__ import annotations

import re
from typing import Optional, Dict
from datetime import datetime

import numpy as np
import cv2

from app.services.ocr import get_ocr
from app.core.logging import get_logger

_logger = get_logger(__name__)

# CNIC formats:
# - With dashes: 5-7-1 => #####-#######-#
# - Without dashes: 13 digits => ############# (normalize to dashed)
_CNIC_DASHED_RE = re.compile(r"^(\d{5})-(\d{7})-(\d)$")
_CNIC_DIGITS_RE = re.compile(r"^(\d{13})$")

# Additional patterns
_DATE_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_GENDER_RE = re.compile(r"\b([MF])\b", re.I)


def normalize_cnic(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = re.sub(r"[^0-9-]", "", raw)
    m = _CNIC_DASHED_RE.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    s_digits = re.sub(r"[^0-9]", "", s)
    m2 = _CNIC_DIGITS_RE.match(s_digits)
    if m2:
        d = m2.group(1)
        return f"{d[0:5]}-{d[5:12]}-{d[12]}"
    return None


def _preprocess_variants(img: np.ndarray) -> list[np.ndarray]:
    variants: list[np.ndarray] = []
    # Base grayscale + CLAHE
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    den = cv2.bilateralFilter(gray, 9, 75, 75)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enh = clahe.apply(den)
    variants.append(cv2.cvtColor(enh, cv2.COLOR_GRAY2BGR))

    # Otsu threshold
    _, otsu = cv2.threshold(enh, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR))

    # Adaptive threshold (mean)
    adap = cv2.adaptiveThreshold(enh, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 10)
    variants.append(cv2.cvtColor(adap, cv2.COLOR_GRAY2BGR))

    # Morph close to join digits separated by small gaps
    kernel = np.ones((3, 3), np.uint8)
    closed = cv2.morphologyEx(enh, cv2.MORPH_CLOSE, kernel, iterations=1)
    variants.append(cv2.cvtColor(closed, cv2.COLOR_GRAY2BGR))

    return variants


def _rotate_variants(img: np.ndarray) -> list[np.ndarray]:
    rots = [img]
    rots.append(cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE))
    rots.append(cv2.rotate(img, cv2.ROTATE_180))
    rots.append(cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE))
    return rots


def extract_cnic_number_from_image_bytes(image_bytes: bytes, min_conf: float = 0.35) -> Optional[str]:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        _logger.warning("cnic_ocr.decode_failed")
        return None

    # Upscale base image if small
    h0, w0 = img.shape[:2]
    if min(h0, w0) < 600:
        scale = max(1, int(600 / max(1, min(h0, w0))))
        if scale > 1:
            img = cv2.resize(img, (w0 * scale, h0 * scale), interpolation=cv2.INTER_LANCZOS4)

    ocr = get_ocr()

    # Try rotations and preprocessing variants
    for rotated in _rotate_variants(img):
        for proc in _preprocess_variants(rotated):
            result = ocr.predict(proc)

            # Aggregate texts that meet min_conf
            kept: list[str] = []
            for r in result:
                rec_texts = r.get("rec_texts", [])
                rec_scores = r.get("rec_scores", [])
                for detected_text, score in zip(rec_texts, rec_scores):
                    try:
                        score_f = float(score)
                    except Exception:
                        continue
                    if np.isnan(score_f) or score_f < min_conf:
                        continue
                    kept.append(str(detected_text))

            if not kept:
                continue

            blob = " ".join(kept)
            # First look for dashed pattern anywhere in blob
            m = re.search(r"(\d{5}-\d{7}-\d)", blob)
            if m:
                norm = normalize_cnic(m.group(1))
                if norm:
                    _logger.info("cnic_ocr.detected", cnic=norm)
                    return norm

            # Then look for 13 consecutive digits
            m2 = re.search(r"(\d{13})", blob)
            if m2:
                norm2 = normalize_cnic(m2.group(1))
                if norm2:
                    _logger.info("cnic_ocr.detected", cnic=norm2)
                    return norm2

    _logger.info("cnic_ocr.not_found")
    return None


def _parse_date(txt: str) -> Optional[datetime]:
    txt = txt.strip().replace("/", ".").replace("-", ".")
    m = _DATE_RE.search(txt.replace("/", ".").replace("-", "."))
    if not m:
        return None
    try:
        d, m_, y = map(int, m.groups())
        return datetime(y, m_, d)
    except Exception:
        return None


def _extract_fields(ocr_blob: str) -> Dict[str, Optional[object]]:
    # ------------------------------------------------------------------
    # 1. Normalise the OCR text
    # ------------------------------------------------------------------
    lines = [l.strip() for l in ocr_blob.splitlines() if l.strip()]
    lower = ocr_blob.lower()

    result: Dict[str, Optional[object]] = {
        "cnic_number": None,
        "name": None,
        "father_name": None,
        "gender": None,
        "country_of_stay": None,
        "date_of_birth": None,
        "date_of_issue": None,
        "date_of_expiry": None,
    }

    # ------------------------------------------------------------------
    # 2. CNIC number (unchanged)
    # ------------------------------------------------------------------
    m = re.search(r"(\d{5}-\d{7}-\d)", ocr_blob)
    if m:
        result["cnic_number"] = normalize_cnic(m.group(1))
    else:
        m = re.search(r"(\d{13})", ocr_blob)
        if m:
            result["cnic_number"] = normalize_cnic(m.group(1))

    # ------------------------------------------------------------------
    # 3. Helper – value after a label (robust)
    # ------------------------------------------------------------------
    def value_after(labels: list[str], max_skip: int = 2) -> Optional[str]:
        lbls = [lbl.lower() for lbl in labels]
        for i, line in enumerate(lines):
            if any(l in line.lower() for l in lbls):
                for j in range(i + 1, min(i + 1 + max_skip, len(lines))):
                    cand = lines[j].strip()
                    if cand:
                        return cand
        return None

    # ------------------------------------------------------------------
    # 4. Name / Father name
    # ------------------------------------------------------------------
    result["name"]        = value_after(["Name", "Name:", "Holder"])
    result["father_name"] = value_after(["Father Name", "Father's Name", "Father"])

    # ------------------------------------------------------------------
    # 5. Gender
    # ------------------------------------------------------------------
    gm = _GENDER_RE.search(ocr_blob)
    if gm:
        result["gender"] = gm.group(1).upper()

    # ------------------------------------------------------------------
    # 6. Country of Stay  (M  Pakistan)
    # ------------------------------------------------------------------
    # look for the word “Pakistan” anywhere – it is the only country name on the card
    if "pakistan" in lower:
        result["country_of_stay"] = "PAKISTAN"

    # ------------------------------------------------------------------
    # 7. Dates – first try label proximity, then fallback to order
    # ------------------------------------------------------------------
    date_matches = list(_DATE_RE.finditer(ocr_blob))

    def parse_match(m) -> Optional[datetime]:
        try:
            d, mon, y = map(int, m.groups())
            # accept 2-digit year → assume 19xx/20xx
            if y < 100:
                y += 1900 if y >= 50 else 2000
            return datetime(y, mon, d)
        except Exception:
            return None

    # ---- label-based assignment ------------------------------------------------
    def assign_by_label(label_keys: list[str]) -> Optional[datetime]:
        for key in label_keys:
            pos = lower.find(key)
            if pos == -1:
                continue
            for m in date_matches:
                if abs(m.start() - pos) < 250:          # close enough on the same line / column
                    return parse_match(m)
        return None

    result["date_of_birth"] = assign_by_label(["date of birth", "dob", "birth"])
    result["date_of_issue"] = assign_by_label(["date of issue", "issue", "doi"])
    result["date_of_expiry"]= assign_by_label(["date of expiry", "expiry", "doe"])

    # ---- fallback: use the three dates in the order they appear ------------
    if date_matches and not all([result["date_of_birth"], result["date_of_issue"], result["date_of_expiry"]]):
        parsed = [parse_match(m) for m in date_matches if parse_match(m)]
        parsed = [d for d in parsed if d]               # filter None
        parsed.sort()                                   # oldest → newest

        if not result["date_of_birth"] and parsed:
            result["date_of_birth"] = parsed[0]
        if not result["date_of_issue"] and len(parsed) > 1:
            result["date_of_issue"] = parsed[1]
        if not result["date_of_expiry"] and len(parsed) > 2:
            result["date_of_expiry"] = parsed[2]

    return result


def extract_cnic_fields_from_image_bytes(
    image_bytes: bytes, min_conf: float = 0.35
) -> Dict[str, Optional[object]]:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return {k: None for k in [
            "cnic_number","name","father_name","gender",
            "country_of_stay","date_of_birth","date_of_issue","date_of_expiry"
        ]}

    h0, w0 = img.shape[:2]
    if min(h0, w0) < 600:
        scale = max(1, int(600 / max(1, min(h0, w0))))
        if scale > 1:
            img = cv2.resize(img, (w0 * scale, h0 * scale), interpolation=cv2.INTER_LANCZOS4)

    ocr = get_ocr()

    best_fields: Optional[Dict[str, Optional[object]]] = None
    for rotated in _rotate_variants(img):
        for proc in _preprocess_variants(rotated):
            result = ocr.predict(proc)
            kept: list[str] = []
            for r in result:
                rec_texts = r.get("rec_texts", [])
                rec_scores = r.get("rec_scores", [])
                for detected_text, score in zip(rec_texts, rec_scores):
                    try:
                        score_f = float(score)
                    except Exception:
                        continue
                    if np.isnan(score_f) or score_f < min_conf:
                        continue
                    kept.append(str(detected_text))

            if not kept:
                continue

            blob = "\n".join(kept)
            _logger.debug("OCR Blob:\n%s", blob)
            fields = _extract_fields(blob)
            if fields.get("cnic_number"):
                return fields
            if best_fields is None:
                best_fields = fields

    if best_fields is not None:
        return best_fields

    return {k: None for k in [
        "cnic_number","name","father_name","gender",
        "country_of_stay","date_of_birth","date_of_issue","date_of_expiry"
    ]}
