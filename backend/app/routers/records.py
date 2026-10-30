from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..database import get_session
from ..models import Record, RecordCreate, RecordUpdate, RecordRead

router = APIRouter(prefix="/api/records", tags=["records"])
SessionDep = Annotated[Session, Depends(get_session)]

def find_record(session: Session, record_id: int):
    record = session.get(Record, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return record

@router.post("", response_model=RecordRead, status_code=201)
def create_record(data: RecordCreate, session: SessionDep):
    record = Record(title=data.title, content=data.content)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record

@router.get("", response_model=list[RecordRead])
def list_records(session: SessionDep):
    statement = select(Record).order_by(Record.id.desc()).limit(100)
    return session.exec(statement).all()

@router.get("/{record_id}", response_model=RecordRead)
def get_record(record_id: int, session: SessionDep):
    return find_record(session, record_id)

@router.patch("/{record_id}", response_model=RecordRead)
def update_record(
    record_id: int,
    data: RecordUpdate,
    session: SessionDep
):
    record = find_record(session, record_id)
    changes = data.model_dump(exclude_unset=True)

    if any(value is None for value in changes.values()):
        raise HTTPException(
            status_code=422,
            detail="Null values are not allowed"
        )

    record.sqlmodel_update(changes)
    record.updated_at = datetime.now(timezone.utc)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record

@router.delete("/{record_id}", status_code=204)
def delete_record(record_id: int, session: SessionDep):
    record = find_record(session, record_id)
    session.delete(record)
    session.commit()
