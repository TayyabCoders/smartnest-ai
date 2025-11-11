from datetime import datetime, date
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field, HttpUrl, constr


PlateNumber = constr(pattern=r"^[A-Z]{3}-?\d{3}$|^[A-Z]{2}-?\d{3,4}$", to_upper=True)


class EntryRequest(BaseModel):
    plate_number: PlateNumber = Field(..., description="Vehicle license plate number")
    entry_image_url: HttpUrl = Field(..., description="URL to the entry image captured")


class EntryResponse(BaseModel):
    plate_number: str
    entry_time: datetime
    status: Literal["IN"]
    message: str


class ExitRequest(BaseModel):
    plate_number: PlateNumber
    exit_image_url: HttpUrl


class ExitResponse(BaseModel):
    plate_number: str
    entry_time: datetime
    exit_time: datetime
    duration_minutes: int
    fee: int
    message: str


class StatusResponse(BaseModel):
    plate_number: str
    status: Literal["IN", "OUT"]
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    elapsed_minutes: Optional[int] = None
    current_fee: Optional[int] = None
    grace_period_remaining_minutes: Optional[int] = None
    total_fee_paid: Optional[int] = None


class Record(BaseModel):
    plate_number: str
    status: Literal["IN", "OUT"]
    entry_time: datetime
    exit_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    fee: Optional[int] = None
    entry_image_url: Optional[HttpUrl] = None
    exit_image_url: Optional[HttpUrl] = None
    elapsed_minutes: Optional[int] = None
    current_fee: Optional[int] = None


class AllRecordsQuery(BaseModel):
    page: int = Field(1, ge=1)
    limit: int = Field(50, ge=1, le=200)
    status: Optional[Literal["IN", "OUT"]] = None
    date: Optional[date] = None


class AllRecordsResponse(BaseModel):
    total: int
    page: int
    limit: int
    data: List[Record]
