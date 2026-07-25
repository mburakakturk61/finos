import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CompanyBase(BaseModel):
    legal_name: str = Field(..., min_length=1, max_length=255)
    trade_name: str | None = Field(default=None, max_length=255)
    tax_number: str = Field(..., min_length=1, max_length=32)
    tax_office: str | None = Field(default=None, max_length=255)
    sector: str | None = Field(default=None, max_length=255)
    nace_code: str | None = Field(default=None, max_length=16)
    currency: str = Field(default="TRY", min_length=3, max_length=3)


class CompanyCreate(CompanyBase):
    pass


class CompanyRead(CompanyBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
