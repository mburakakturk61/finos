import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import PeriodStatus, PeriodType


class FinancialPeriodBase(BaseModel):
    year: int = Field(..., ge=1900, le=2100)
    period_type: PeriodType
    period_number: int = Field(..., ge=1, le=12)
    start_date: date
    end_date: date
    months_covered: int = Field(..., ge=1, le=12)
    is_year_end: bool = False
    status: PeriodStatus = PeriodStatus.DRAFT

    @model_validator(mode="after")
    def check_date_range(self) -> "FinancialPeriodBase":
        if self.end_date < self.start_date:
            raise ValueError("end_date, start_date'ten önce olamaz.")
        return self


class FinancialPeriodCreate(FinancialPeriodBase):
    pass


class FinancialPeriodRead(FinancialPeriodBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
