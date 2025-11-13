import uuid
from sqlalchemy import Column, String, DateTime, Index
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base


class CnicRecord(Base):
    __tablename__ = "cnic_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    cnic_number = Column(String(15), nullable=False, index=True)
    name = Column(String(100), nullable=True)
    father_name = Column(String(100), nullable=True)
    gender = Column(String(20), nullable=True)
    country_of_stay = Column(String(100), nullable=True)
    date_of_birth = Column(DateTime(timezone=True), nullable=True)
    date_of_issue = Column(DateTime(timezone=True), nullable=True)
    date_of_expiry = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


Index("ix_cnic_number", CnicRecord.cnic_number)
Index("ix_cnic_name_dob", CnicRecord.name, CnicRecord.date_of_birth)