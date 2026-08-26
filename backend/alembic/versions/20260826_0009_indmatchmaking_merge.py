"""merge with IndMatchmaking: RBAC/user/admin tables + Event/Match ownership fields (docs/PLAN.md Phase 8)

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-26

Recreates IndMatchmaking's schema end-state directly in this database rather
than replaying its own 15-migration history (docs/PLAN.md Task 53). Table
shapes match app/models/rbac.py, app/models/user.py, and
app/models/matching_admin.py exactly - see those files' module docstrings
for what was ported as-is vs. re-targeted (event_participant_mapping now FKs
this DB's own `events`, email_log FKs `events`/`matches`/`participants`
instead of the old by-value external-id columns, etc.).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Standalone lookup tables (no FK dependencies) ---
    op.create_table(
        "role_master",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("role_name", sa.String(80), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_role_master_role_name", "role_master", ["role_name"])
    op.create_index("ix_role_master_status", "role_master", ["status"])

    op.create_table(
        "permission_master",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("permission_code", sa.String(120), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_permission_master_permission_code", "permission_master", ["permission_code"])
    op.create_index("ix_permission_master_status", "permission_master", ["status"])

    op.create_table(
        "company_master",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_name", sa.String(200), nullable=False, unique=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("company_size", sa.Integer(), nullable=True),
        sa.Column("website", sa.String(255), nullable=True),
        sa.Column("is_known_brand", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_company_master_industry", "company_master", ["industry"])
    op.create_index("ix_company_master_is_known_brand", "company_master", ["is_known_brand"])
    op.create_index("ix_company_master_status", "company_master", ["status"])

    op.create_table(
        "tag_master",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tag_name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tag_master_tag_name", "tag_master", ["tag_name"])
    op.create_index("ix_tag_master_status", "tag_master", ["status"])

    op.create_table(
        "match_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("profile_code", sa.String(40), nullable=False, unique=True),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("gender", sa.String(30), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("marital_status", sa.String(80), nullable=True),
        sa.Column("religion", sa.String(100), nullable=True),
        sa.Column("caste", sa.String(100), nullable=True),
        sa.Column("mother_tongue", sa.String(100), nullable=True),
        sa.Column("education", sa.String(160), nullable=True),
        sa.Column("occupation", sa.String(160), nullable=True),
        sa.Column("annual_income", sa.Numeric(12, 2), nullable=True),
        sa.Column("height_cm", sa.Integer(), nullable=True),
        sa.Column("city", sa.String(120), nullable=True),
        sa.Column("state", sa.String(120), nullable=True),
        sa.Column("country", sa.String(120), nullable=True),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("family_details", sa.Text(), nullable=True),
        sa.Column("expectations", sa.Text(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_match_profiles_profile_code", "match_profiles", ["profile_code"])
    op.create_index("ix_match_profiles_full_name", "match_profiles", ["full_name"])
    op.create_index("ix_match_profiles_gender", "match_profiles", ["gender"])
    op.create_index("ix_match_profiles_status", "match_profiles", ["status"])

    # --- user_master (depends on company_master, role_master, self-FK) ---
    op.create_table(
        "user_master",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("first_name", sa.String(120), nullable=False),
        sa.Column("last_name", sa.String(120), nullable=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("mobile_phone", sa.String(40), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_master.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("job_title", sa.String(160), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("company_size", sa.Integer(), nullable=True),
        sa.Column("looking_for", sa.Text(), nullable=True),
        sa.Column("offering", sa.Text(), nullable=True),
        sa.Column("target_connections", sa.Text(), nullable=True),
        sa.Column("registration_message", sa.Text(), nullable=True),
        sa.Column("member_status", sa.String(40), nullable=True),
        sa.Column(
            "role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("role_master.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_master.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_master_email", "user_master", ["email"])
    op.create_index("ix_user_master_industry", "user_master", ["industry"])
    op.create_index("ix_user_master_member_status", "user_master", ["member_status"])
    op.create_index("ix_user_master_status", "user_master", ["status"])

    # --- Mapping tables depending on user_master ---
    op.create_table(
        "role_permission_mapping",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("role_master.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "permission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("permission_master.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission_mapping_role_perm"),
    )
    op.create_index("ix_role_permission_mapping_role_id", "role_permission_mapping", ["role_id"])
    op.create_index("ix_role_permission_mapping_permission_id", "role_permission_mapping", ["permission_id"])

    op.create_table(
        "user_tag_mapping",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user_master.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "tag_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tag_master.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "tag_id", name="uq_user_tag_mapping_user_tag"),
    )
    op.create_index("ix_user_tag_mapping_user_id", "user_tag_mapping", ["user_id"])
    op.create_index("ix_user_tag_mapping_tag_id", "user_tag_mapping", ["tag_id"])

    op.create_table(
        "smtp_master",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user_master.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("encryption_type", sa.String(40), nullable=True),
        sa.Column("from_email", sa.String(255), nullable=False),
        sa.Column("from_name", sa.String(160), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_smtp_master_user_id", "smtp_master", ["user_id"])

    # --- Event/Match ownership + review-audit columns ---
    op.add_column("events", sa.Column("location", sa.String(255), nullable=True))
    op.add_column(
        "events",
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_master.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "matches",
        sa.Column(
            "reviewed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_master.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("matches", sa.Column("reviewed_at", sa.DateTime(), nullable=True))

    # --- Tables depending on events (this DB's own, not event_master) ---
    op.create_table(
        "event_participant_mapping",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user_master.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column(
            "assigned_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_master.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("event_id", "user_id", name="uq_event_participant_mapping_event_user"),
    )
    op.create_index("ix_event_participant_mapping_event_id", "event_participant_mapping", ["event_id"])
    op.create_index("ix_event_participant_mapping_user_id", "event_participant_mapping", ["user_id"])

    op.create_table(
        "email_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "sender_participant_id",
            sa.Integer(),
            sa.ForeignKey("participants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "receiver_participant_id",
            sa.Integer(),
            sa.ForeignKey("participants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "triggered_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_master.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_email_log_status", "email_log", ["status"])


def downgrade() -> None:
    op.drop_table("email_log")
    op.drop_table("event_participant_mapping")

    op.drop_column("matches", "reviewed_at")
    op.drop_column("matches", "reviewed_by_user_id")
    op.drop_column("events", "owner_user_id")
    op.drop_column("events", "location")

    op.drop_table("smtp_master")
    op.drop_table("user_tag_mapping")
    op.drop_table("role_permission_mapping")
    op.drop_table("user_master")
    op.drop_table("match_profiles")
    op.drop_table("tag_master")
    op.drop_table("company_master")
    op.drop_table("permission_master")
    op.drop_table("role_master")
