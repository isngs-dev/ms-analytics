"""Canonical schema for the MS Analytics dashboard (see docs/PHASE1_SCHEMA.md).

Hierarchy used everywhere: Client (filename prefix, e.g. HSB / APC) -> Project (middle part of the
filename, or derived from the Form column) -> Form (the `Form` column). Display labels for these
levels are configurable through app_setting so the UI can use the business's own words.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------- discovery registry
class SrcFile(Base):
    __tablename__ = "src_file"
    id: Mapped[int] = mapped_column(primary_key=True)
    drive_file_id: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(Text)
    year: Mapped[int | None]
    quarter: Mapped[int | None]
    client_id: Mapped[int | None] = mapped_column(ForeignKey("dim_client.id"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("dim_project.id"))
    is_multi_project: Mapped[bool] = mapped_column(Boolean, default=False)
    drive_modified_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | excluded | error
    sheets: Mapped[list["SrcSheet"]] = relationship(back_populates="file")


class SrcSheet(Base):
    __tablename__ = "src_sheet"
    __table_args__ = (UniqueConstraint("file_id", "tab_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("src_file.id", ondelete="CASCADE"))
    tab_name: Mapped[str] = mapped_column(Text)
    # operational | rework | escalation | master | client_query | ignored (credentials, never read)
    # | reference (any other tab: its rows are stored as-is) | supplementary (a form-like tab that only
    # adds Job IDs the main tabs do not have)
    kind: Mapped[str] = mapped_column(String(16))
    header: Mapped[list | None] = mapped_column(JSONB)  # column names of a reference tab
    month_start: Mapped[date | None] = mapped_column(Date)
    header_row: Mapped[int | None]
    include: Mapped[bool] = mapped_column(Boolean, default=True)
    rows_seen: Mapped[int] = mapped_column(Integer, default=0)  # raw rows in the tab, header included
    # reconciliation: data rows = placeholder + loaded + rejected (+ duplicates that lost to a newer file)
    rows_loaded: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    rows_placeholder: Mapped[int] = mapped_column(Integer, default=0)  # blank / template rows
    rows_duplicate: Mapped[int] = mapped_column(Integer, default=0)  # repeat Job IDs merged into one form
    content_hash: Mapped[str | None] = mapped_column(String(64))
    file: Mapped[SrcFile] = relationship(back_populates="sheets")


class SrcRecord(Base):
    """One non-blank row of a reference tab (Data Entry, Client Feedbacks, Updates ...), kept exactly as written so
    nothing in a workbook is invisible. Cells are positional, the tab's column names are in src_sheet.header."""
    __tablename__ = "src_record"
    __table_args__ = (UniqueConstraint("sheet_id", "row_no"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("src_sheet.id", ondelete="CASCADE"), index=True)
    row_no: Mapped[int]  # 1-based row in the source tab
    cells: Mapped[list] = mapped_column(JSONB)


# --------------------------------------------------------------------------- dimensions
class DimClient(Base):
    __tablename__ = "dim_client"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)


class ClientAlias(Base):
    __tablename__ = "client_alias"
    alias_norm: Mapped[str] = mapped_column(String(128), primary_key=True)  # lowercased, trimmed
    client_id: Mapped[int] = mapped_column(ForeignKey("dim_client.id", ondelete="CASCADE"))


class DimProject(Base):
    __tablename__ = "dim_project"
    __table_args__ = (UniqueConstraint("client_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("dim_client.id"))
    name: Mapped[str] = mapped_column(String(256))
    # NULL = auto (true once any row has a QC member/date); True/False = Admin override.
    qc_applicable_override: Mapped[bool | None] = mapped_column(Boolean)
    qc_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    active_from: Mapped[date | None] = mapped_column(Date)
    active_to: Mapped[date | None] = mapped_column(Date)


class DimPerson(Base):
    __tablename__ = "dim_person"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # one person may edit and QC


class PersonAlias(Base):
    __tablename__ = "person_alias"
    alias_norm: Mapped[str] = mapped_column(String(128), primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("dim_person.id", ondelete="CASCADE"))


class DimErrorCategory(Base):
    __tablename__ = "dim_error_category"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("dim_error_category.id"))


# --------------------------------------------------------------------------- facts
class Form(Base):
    __tablename__ = "forms"
    __table_args__ = (
        UniqueConstraint("client_id", "project_id", "job_id", name="uq_forms_identity"),
        Index("ix_forms_received", "received_date"),
        Index("ix_forms_edit", "edit_date"),
        Index("ix_forms_qc", "qc_date"),
        Index("ix_forms_project", "project_id"),
        Index("ix_forms_editor", "editor_id"),
        Index("ix_forms_qcmember", "qc_member_id"),
        Index("ix_forms_source_sheet", "source_sheet_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("dim_client.id"))
    project_id: Mapped[int] = mapped_column(ForeignKey("dim_project.id"))
    job_id: Mapped[str] = mapped_column(String(64))  # Shop ID == Job ID
    form_name: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[str | None] = mapped_column(String(32))

    # event dates: each metric is counted by its own date, never by current status
    received_date: Mapped[date | None] = mapped_column(Date)  # Input Date
    shop_date: Mapped[date | None] = mapped_column(Date)  # shopper's visit date only
    edit_date: Mapped[date | None] = mapped_column(Date)  # Transaction Date
    qc_date: Mapped[date | None] = mapped_column(Date)  # QC Date

    editor_type: Mapped[str | None] = mapped_column(String(32))  # iSN Team | Freelancer
    editor_id: Mapped[int | None] = mapped_column(ForeignKey("dim_person.id"))
    qc_member_id: Mapped[int | None] = mapped_column(ForeignKey("dim_person.id"))

    input_status: Mapped[str | None] = mapped_column(String(64))  # Completed / Hold A / Hold B
    edit_status: Mapped[str | None] = mapped_column(String(64))  # canonical Ops Status
    qc_status: Mapped[str | None] = mapped_column(String(64))
    hold_category: Mapped[str | None] = mapped_column(Text)
    incomplete_status: Mapped[str | None] = mapped_column(String(64))
    client_escalation: Mapped[str | None] = mapped_column(Text)
    error_category_raw: Mapped[str | None] = mapped_column(String(128))
    comments_to_shopper: Mapped[str | None] = mapped_column(Text)
    qc_feedback: Mapped[str | None] = mapped_column(Text)

    source_sheet_id: Mapped[int | None] = mapped_column(ForeignKey("src_sheet.id"))
    source_row_no: Mapped[int | None]
    row_hash: Mapped[str] = mapped_column(String(64))
    dup_count: Mapped[int] = mapped_column(Integer, default=0)  # extra occurrences of same identity
    # How many forms this row stands for. 1 for ordinary projects; for the projects counted by images (Global Data)
    # it is the sheet's '#images' cell, so every volume figure is a sum of units, not a row count.
    units: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)  # unmapped columns, never dropped
    first_seen_at: Mapped[datetime] = _ts()
    last_seen_at: Mapped[datetime] = _ts()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Rework(Base):
    """One row per RW-tab row. The same job repeats with a new date/status per rework round."""
    __tablename__ = "rework"
    __table_args__ = (
        UniqueConstraint("client_id", "project_id", "job_id", "rw_seq", name="uq_rework_round"),
        Index("ix_rework_date", "rw_date"),
        Index("ix_rework_project", "project_id"),
        Index("ix_rework_editor", "rw_editor_id"),
        Index("ix_rework_source_sheet", "source_sheet_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("dim_client.id"))
    project_id: Mapped[int] = mapped_column(ForeignKey("dim_project.id"))
    job_id: Mapped[str] = mapped_column(String(64))
    form_id: Mapped[int | None] = mapped_column(ForeignKey("forms.id"))
    rw_seq: Mapped[int] = mapped_column(Integer)  # 1-based round for this job
    form_name: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    received_date: Mapped[date | None] = mapped_column(Date)  # Input Date on the RW row
    shop_date: Mapped[date | None] = mapped_column(Date)
    rw_date: Mapped[date | None] = mapped_column(Date)  # Transaction Date
    editor_type: Mapped[str | None] = mapped_column(String(32))
    rw_editor_id: Mapped[int | None] = mapped_column(ForeignKey("dim_person.id"))
    rw_status: Mapped[str | None] = mapped_column(String(64))
    qc_member_id: Mapped[int | None] = mapped_column(ForeignKey("dim_person.id"))
    qc_date: Mapped[date | None] = mapped_column(Date)
    qc_status: Mapped[str | None] = mapped_column(String(64))
    feedback: Mapped[str | None] = mapped_column(Text)
    error_category_id: Mapped[int | None] = mapped_column(ForeignKey("dim_error_category.id"))
    comments_to_shopper: Mapped[str | None] = mapped_column(Text)
    source_sheet_id: Mapped[int | None] = mapped_column(ForeignKey("src_sheet.id"))
    source_row_no: Mapped[int | None]
    row_hash: Mapped[str] = mapped_column(String(64))
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Escalation(Base):
    __tablename__ = "escalations"
    __table_args__ = (Index("ix_esc_date", "raised_date"), Index("ix_esc_project", "project_id"),
                      Index("ix_esc_job", "client_id", "project_id", "job_id"),
                      Index("ix_escalations_source_sheet", "source_sheet_id"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("dim_client.id"))
    project_id: Mapped[int] = mapped_column(ForeignKey("dim_project.id"))
    job_id: Mapped[str | None] = mapped_column(String(64))  # free-standing escalations allowed
    form_id: Mapped[int | None] = mapped_column(ForeignKey("forms.id"))
    raised_date: Mapped[date | None] = mapped_column(Date)  # Input Date
    editor_type: Mapped[str | None] = mapped_column(String(32))
    editor_id: Mapped[int | None] = mapped_column(ForeignKey("dim_person.id"))
    qc_member_id: Mapped[int | None] = mapped_column(ForeignKey("dim_person.id"))
    qc_date: Mapped[date | None] = mapped_column(Date)
    client_feedback: Mapped[str | None] = mapped_column(Text)
    root_cause: Mapped[str | None] = mapped_column(Text)
    preventive_action: Mapped[str | None] = mapped_column(Text)
    corrective_action: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    error_category_id: Mapped[int | None] = mapped_column(ForeignKey("dim_error_category.id"))
    # tracked in-app (not in the sheets): open | in_progress | closed
    action_status: Mapped[str] = mapped_column(String(16), default="open")
    action_owner: Mapped[str | None] = mapped_column(String(128))
    closed_date: Mapped[date | None] = mapped_column(Date)
    source_sheet_id: Mapped[int | None] = mapped_column(ForeignKey("src_sheet.id"))
    source_row_no: Mapped[int | None]
    row_hash: Mapped[str] = mapped_column(String(64), unique=True)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------- sync + health
class SyncLog(Base):
    __tablename__ = "sync_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = _ts()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(String(16))  # schedule | manual | seed
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | ok | partial | failed
    files_total: Mapped[int | None] = mapped_column(Integer)  # for progress bars
    files_scanned: Mapped[int] = mapped_column(Integer, default=0)
    files_changed: Mapped[int] = mapped_column(Integer, default=0)
    rows_upserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    error_text: Mapped[str | None] = mapped_column(Text)


class SyncIssue(Base):
    __tablename__ = "sync_issue"
    __table_args__ = (Index("ix_issue_sync", "sync_id"), Index("ix_issue_type", "type"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sync_id: Mapped[int] = mapped_column(ForeignKey("sync_log.id", ondelete="CASCADE"))
    severity: Mapped[str] = mapped_column(String(8))  # info | warn | error
    # duplicate | missing_date | missing_editor | missing_qc_status | unmapped_column |
    # unmapped_status | bad_filename | bad_date | sheet_error
    type: Mapped[str] = mapped_column(String(32))
    file_id: Mapped[int | None] = mapped_column(ForeignKey("src_file.id"))
    sheet_id: Mapped[int | None] = mapped_column(ForeignKey("src_sheet.id"))
    row_no: Mapped[int | None]
    detail: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------- admin-editable mapping
class ColumnMap(Base):
    __tablename__ = "column_map"
    __table_args__ = (UniqueConstraint("scope", "scope_ref", "sheet_kind", "source_header_norm"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(8), default="global")  # global | client | project
    scope_ref: Mapped[str] = mapped_column(String(256), default="")  # client/project name or ''
    sheet_kind: Mapped[str] = mapped_column(String(16))  # operational | rework | escalation
    source_header_norm: Mapped[str] = mapped_column(String(128))  # lowercased, punctuation stripped
    canonical_field: Mapped[str] = mapped_column(String(64))
    transform: Mapped[str | None] = mapped_column(String(32))  # e.g. 'date_us'


class StatusMap(Base):
    __tablename__ = "status_map"
    __table_args__ = (UniqueConstraint("field", "source_value_norm"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    field: Mapped[str] = mapped_column(String(32))  # input_status | edit_status | qc_status
    source_value_norm: Mapped[str] = mapped_column(String(64))
    canonical_value: Mapped[str] = mapped_column(String(64))
    # Default per business rule: only 'Edited & Saved' counts as Edited.
    counts_as_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    counts_as_finalised: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hold_or_incomplete: Mapped[bool] = mapped_column(Boolean, default=False)


class SheetRule(Base):
    __tablename__ = "sheet_rule"
    id: Mapped[int] = mapped_column(primary_key=True)
    priority: Mapped[int] = mapped_column(Integer)  # lowest first; first match wins
    pattern: Mapped[str] = mapped_column(String(128))  # case-insensitive regex on tab name
    kind: Mapped[str] = mapped_column(String(16))
    include: Mapped[bool] = mapped_column(Boolean, default=True)
    read_cells: Mapped[bool] = mapped_column(Boolean, default=True)  # False => tab is never fetched


class SnapshotMonthly(Base):
    __tablename__ = "snapshot_monthly"
    __table_args__ = (UniqueConstraint("period", "client_id", "project_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[date] = mapped_column(Date)  # first day of the month
    client_id: Mapped[int | None] = mapped_column(ForeignKey("dim_client.id"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("dim_project.id"))
    metrics: Mapped[dict] = mapped_column(JSONB)
    taken_at: Mapped[datetime] = _ts()


class AppUser(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))  # admin | manager | viewer
    password_hash: Mapped[str] = mapped_column(String(256))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _ts()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppSetting(Base):
    __tablename__ = "app_setting"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)  # e.g. level labels, refresh schedule
