from sqlalchemy import Column, Integer, String, DateTime, Float, Index
from sqlalchemy.sql import func
from app.db.session import Base


class ParkingRecord(Base):
    __tablename__ = "parking_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    plate_number = Column(String(40), nullable=False, index=True)
    entry_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    exit_time = Column(DateTime(timezone=True), nullable=True)
    fee = Column(Float, nullable=True)
    entry_image_path = Column(String(500), nullable=True)
    exit_image_path = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="IN")  # IN, OUT
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# Composite indexes to speed up queries
Index("ix_parking_plate_status", ParkingRecord.plate_number, ParkingRecord.status)
Index("ix_parking_entry_time", ParkingRecord.entry_time)
