from __future__ import annotations

from typing import Optional

from paddleocr import PaddleOCR

from app.core.logging import get_logger

_logger = get_logger(__name__)

_ocr_singleton: Optional[PaddleOCR] = None


def get_ocr() -> PaddleOCR:
    global _ocr_singleton
    if _ocr_singleton is None:
        _logger.info("ocr.singleton.init")
        _ocr_singleton = PaddleOCR(
            use_textline_orientation=True,
            lang="en",
            device="cpu",
        )
    return _ocr_singleton
