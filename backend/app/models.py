from datetime import datetime, timezone
from sqlmodel import SQLModel, Field

def utc_now():
    return datetime.now(timezone.utc)

class Record(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    content: str = ""
    ai_result: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

class RecordCreate(SQLModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = ""

class RecordUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None

class RecordRead(SQLModel):
    id: int
    title: str
    content: str
    ai_result: str | None
    created_at: datetime
    updated_at: datetime
