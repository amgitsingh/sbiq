from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base

# QBCals-native (not ported from IndMatchmaking) - added post-merge
# (docs/PLAN.md Phase 8, IndMatchmaking-parity follow-up) to restore a
# capability IndMatchmaking's ExcelUpload/ExcelRawData tables provided: a
# queryable-after-the-fact record of what happened on a given upload,
# including which rows were rejected and why. Deliberately not a resurrection
# of those shadow tables (see the "eliminate shadow tables" decision in
# docs/PLAN.md Phase 8) - this captures the same summary
# run_ingestion_pipeline already computes for the synchronous response,
# just persisted instead of response-only, as one row per upload call
# rather than one row per source Excel row.


class ParticipantUploadBatch(Base):
    __tablename__ = "participant_upload_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user_master.id", ondelete="SET NULL")
    )
    file_name: Mapped[str] = mapped_column(String(255))
    total_rows: Mapped[int] = mapped_column(Integer)
    parse_skipped: Mapped[int] = mapped_column(Integer)
    valid_count: Mapped[int] = mapped_column(Integer)
    flagged_count: Mapped[int] = mapped_column(Integer)
    rejected_count: Mapped[int] = mapped_column(Integer)
    unmapped_headers: Mapped[list | None] = mapped_column(JSON)
    rejected_details: Mapped[list | None] = mapped_column(JSON)
    # "completed" (no rejections) / "completed_with_errors" (some valid or
    # flagged rows plus some rejections) / "failed" (nothing usable came out
    # of the file at all) - same three-state convention as IndMatchmaking's
    # old ExcelUpload.status.
    status: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
