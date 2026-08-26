"""Generic admin CRUD routes for configured database tables.

Ported from IndMatchmaking (D:\\Python\\IndMatchmaking\\src\\app\\domain\\tables\\controller.py)
as part of docs/PLAN.md Phase 8 (Task 60). Adapted: TABLE_MODELS drops the 5
shadow tables eliminated by this merge (EventMaster, ExcelRawData,
ExcelUpload, MatchScoreLog, ParticipantMatchMaster - see
app/models/matching_admin.py's module docstring) along with their
EventMaster-specific ownership-scoping branches (`if model is EventMaster:
...`) in every handler below. QBCals' own Event/Participant/Match are
deliberately NOT added here - they already have purpose-built, validated
endpoints in app/routers/events.py (ingestion validation, tier
normalization, ownership enforcement via Task 59); exposing them through
this raw dict-based generic editor too would open a second, unvalidated
write path around all of that. This router stays a pure RBAC/lookup-table
admin tool.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect
from sqlalchemy.sql.sqltypes import Boolean, Date, DateTime, Integer, Numeric, String, Text

from app.core.async_database import get_async_db
from app.models.matching_admin import EmailLog, EventParticipantMapping, SmtpMaster
from app.models.rbac import CompanyMaster, PermissionMaster, RoleMaster, RolePermissionMapping, TagMaster, UserTagMapping
from app.models.user import UserMaster
from app.services.auth.deps import current_admin

router = APIRouter(prefix="/admin/tables", tags=["admin-tables"], dependencies=[Depends(current_admin)])

TABLE_MODELS = {
    "company_master": CompanyMaster,
    "email_log": EmailLog,
    "event_participant_mapping": EventParticipantMapping,
    "permission_master": PermissionMaster,
    "role_master": RoleMaster,
    "role_permission_mapping": RolePermissionMapping,
    "smtp_master": SmtpMaster,
    "tag_master": TagMaster,
    "user_master": UserMaster,
    "user_tag_mapping": UserTagMapping,
}

READONLY_FIELDS = {"id", "created_at", "updated_at", "created_by", "approved_by", "approved_at", "sent_at"}
SECRET_FIELDS = {"password_hash", "password_encrypted"}


def _model_for(table_name: str) -> type[Any]:
    model = TABLE_MODELS.get(table_name)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")
    return model


def _column_type(column: Any) -> str:
    column_type = column.type
    if isinstance(column_type, Boolean):
        return "boolean"
    if isinstance(column_type, Integer):
        return "integer"
    if isinstance(column_type, Numeric):
        return "decimal"
    if isinstance(column_type, DateTime):
        return "datetime"
    if isinstance(column_type, Date):
        return "date"
    if isinstance(column_type, String | Text):
        return "string"
    return "json"


def _column_metadata(column: Any) -> dict[str, Any]:
    foreign_key = next(iter(column.foreign_keys), None)
    return {
        "name": column.name,
        "type": _column_type(column),
        "nullable": bool(column.nullable),
        "primary_key": bool(column.primary_key),
        "readonly": column.name in READONLY_FIELDS or bool(column.primary_key),
        "secret": column.name in SECRET_FIELDS,
        "foreign_key": str(foreign_key.column) if foreign_key is not None else None,
    }


def _serialize_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _serialize_row(row: Any) -> dict[str, Any]:
    columns = inspect(row.__class__).columns
    return {
        column.name: None if column.name in SECRET_FIELDS else _serialize_value(getattr(row, column.name))
        for column in columns
    }


def _coerce_value(value: Any, column: Any) -> Any:
    if value == "":
        return None if column.nullable else value
    if value is None:
        return None

    field_type = _column_type(column)
    if field_type == "integer":
        return int(value)
    if field_type == "decimal":
        return Decimal(str(value))
    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "on"}
    if field_type == "date":
        return date.fromisoformat(str(value))
    if field_type == "datetime":
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if str(column.type).upper() == "UUID":
        return uuid.UUID(str(value))
    return value


def _editable_columns(model: type[Any]) -> list[Any]:
    return [
        column
        for column in inspect(model).columns
        if column.name not in READONLY_FIELDS and not column.primary_key and column.name not in SECRET_FIELDS
    ]


@router.get("")
async def list_tables() -> dict[str, Any]:
    """Return table metadata for the admin data manager."""
    return {
        "tables": [
            {
                "name": table_name,
                "label": table_name.replace("_", " ").title(),
                "columns": [_column_metadata(column) for column in inspect(model).columns],
            }
            for table_name, model in TABLE_MODELS.items()
        ],
    }


@router.get("/{table_name}/records")
async def list_records(
    table_name: str,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_async_db),
) -> dict[str, Any]:
    """List records from a configured table."""
    model = _model_for(table_name)
    statement = select(model)
    count_statement = select(func.count()).select_from(model)

    if q:
        query = f"%{q}%"
        searchable_columns = [
            getattr(model, column.name)
            for column in inspect(model).columns
            if isinstance(column.type, String | Text) and column.name not in SECRET_FIELDS
        ]
        if searchable_columns:
            filter_clause = or_(*(column.ilike(query) for column in searchable_columns))
            statement = statement.where(filter_clause)
            count_statement = count_statement.where(filter_clause)

    total = await db.scalar(count_statement)
    rows = await db.scalars(statement.limit(limit).offset(offset))
    return {"items": [_serialize_row(row) for row in rows], "total": total or 0}


@router.post("/{table_name}/records", status_code=status.HTTP_201_CREATED)
async def create_record(
    table_name: str, payload: dict[str, Any], user: UserMaster = Depends(current_admin), db: AsyncSession = Depends(get_async_db)
) -> dict[str, Any]:
    """Create a record in a configured table."""
    model = _model_for(table_name)
    values = {}
    for column in _editable_columns(model):
        if column.name in payload:
            values[column.name] = _coerce_value(payload[column.name], column)
    if any(column.name == "created_by" for column in inspect(model).columns):
        values["created_by"] = user.id
    row = model(**values)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _serialize_row(row)


@router.get("/{table_name}/records/{record_id}")
async def get_record(table_name: str, record_id: uuid.UUID, db: AsyncSession = Depends(get_async_db)) -> dict[str, Any]:
    """Return a single record from a configured table."""
    model = _model_for(table_name)
    row = await db.get(model, record_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    return _serialize_row(row)


@router.patch("/{table_name}/records/{record_id}")
async def update_record(
    table_name: str, record_id: uuid.UUID, payload: dict[str, Any], db: AsyncSession = Depends(get_async_db)
) -> dict[str, Any]:
    """Update a record in a configured table."""
    model = _model_for(table_name)
    row = await db.get(model, record_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")

    for column in _editable_columns(model):
        if column.name in payload:
            setattr(row, column.name, _coerce_value(payload[column.name], column))

    await db.commit()
    await db.refresh(row)
    return _serialize_row(row)


@router.delete("/{table_name}/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_record(table_name: str, record_id: uuid.UUID, db: AsyncSession = Depends(get_async_db)) -> None:
    """Delete a record from a configured table."""
    model = _model_for(table_name)
    row = await db.get(model, record_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    await db.delete(row)
    await db.commit()
