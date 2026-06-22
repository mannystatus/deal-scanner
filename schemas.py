from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class DealOut(BaseModel):
    id: int
    source: str
    title: str
    url: str
    affiliate_url: Optional[str] = None
    deal_price: Optional[Decimal] = None
    original_price: Optional[Decimal] = None
    currency: str = "USD"
    discount_pct: Optional[float] = None
    category: str
    merchant: Optional[str] = None
    posted_at: datetime
    confidence: float
    thumbnail_url: Optional[str] = None

    model_config = {"from_attributes": True}


class DealListOut(BaseModel):
    items: List[DealOut]
    total: int
    limit: int
    offset: int


class CategoryCount(BaseModel):
    category: str
    count: int


class HealthOut(BaseModel):
    status: str
    deal_count: int
    latest_ingest: Optional[datetime] = None
