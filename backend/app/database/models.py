"""WORKCODE schema. All 29 required entities are defined here."""
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, Column, Date, ForeignKey, Index, Integer, LargeBinary, Numeric,
                        String, Text, UniqueConstraint)
from sqlalchemy import event
from sqlalchemy.orm import attributes, deferred
from sqlalchemy.types import DateTime, TypeDecorator

from app.database.connection import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Always timezone-aware UTC, on PostgreSQL and SQLite alike."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Stamped:
    created_at = Column(UTCDateTime, default=utcnow, nullable=False)
    updated_at = Column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


def fk(target, ondelete="RESTRICT", **kw):
    return Column(Integer, ForeignKey(target, ondelete=ondelete), **kw)


# ---------- people ----------
class User(Base, Stamped):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(150), nullable=False)
    role = Column(String(20), nullable=False, index=True)  # admin|developer|onroll|offroll|intern
    is_active = Column(Boolean, default=True, nullable=False)
    last_login_at = Column(UTCDateTime)
    deleted_at = Column(UTCDateTime)  # soft delete
    # Raised on logout, password change and admin password reset: login tokens made before that stop working.
    token_version = Column(Integer, nullable=False, default=0, server_default="0")


class PasswordResetToken(Base):
    """One "forgot password" link. Only the SHA-256 of the token is kept; the token itself exists only in the e-mail."""
    __tablename__ = "password_reset_tokens"
    id = Column(Integer, primary_key=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(UTCDateTime, default=utcnow, nullable=False)
    expires_at = Column(UTCDateTime, nullable=False)
    used_at = Column(UTCDateTime)          # set when the password was changed with it, or when a newer link replaced it
    requested_ip = Column(String(64))


class EmployeeProfile(Base, Stamped):
    __tablename__ = "employee_profiles"
    id = Column(Integer, primary_key=True)
    user_id = fk("users.id", "CASCADE", unique=True, nullable=False)
    employee_code = Column(String(20), unique=True, nullable=False)
    category = Column(String(20), nullable=False, index=True)  # onroll|offroll|intern
    department_id = fk("departments.id", "SET NULL", index=True)
    reporting_manager_id = fk("users.id", "SET NULL", index=True)
    phone = Column(String(30))
    joining_date = Column(Date)
    contract_start = Column(Date)
    contract_end = Column(Date)
    employment_status = Column(String(20), default="active", nullable=False)  # active|inactive|completed|left
    conversion_status = Column(String(30), default="none", nullable=False)
    performance_note = Column(Text)
    compensation = Column(Numeric(12, 2))  # salary / stipend — admin + owner only


class AdminProfile(Base, Stamped):
    __tablename__ = "admin_profiles"
    id = Column(Integer, primary_key=True)
    user_id = fk("users.id", "CASCADE", unique=True, nullable=False)
    phone = Column(String(30))


class DeveloperProfile(Base, Stamped):
    __tablename__ = "developer_profiles"
    id = Column(Integer, primary_key=True)
    user_id = fk("users.id", "CASCADE", unique=True, nullable=False)
    employee_code = Column(String(20), unique=True, nullable=False)
    responsibilities = Column(Text)
    joining_date = Column(Date)
    phone = Column(String(30))
    compensation = Column(Numeric(12, 2))


class Department(Base, Stamped):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)


class Team(Base, Stamped):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    lead_developer_id = fk("users.id", "SET NULL", index=True)


class TeamMember(Base, Stamped):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id"),)
    id = Column(Integer, primary_key=True)
    team_id = fk("teams.id", "CASCADE", nullable=False, index=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)


class EmploymentHistory(Base, Stamped):
    __tablename__ = "employment_history"
    id = Column(Integer, primary_key=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)
    event = Column(String(30), nullable=False)  # joined|converted|deactivated|activated|left|completed
    from_role = Column(String(20))
    to_role = Column(String(20))
    reason = Column(Text)
    changed_by = fk("users.id", "SET NULL", index=True)
    effective_date = Column(Date)


class InternVacancy(Base, Stamped):
    __tablename__ = "intern_vacancies"
    id = Column(Integer, primary_key=True)
    target_headcount = Column(Integer, nullable=False, default=10)
    updated_by = fk("users.id", "SET NULL", index=True)


# ---------- work ----------
class Project(Base, Stamped):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    description = Column(Text)
    status = Column(String(20), default="active", nullable=False)
    created_by = fk("users.id", "SET NULL", index=True)


class Task(Base, Stamped):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    requirements = Column(Text)
    project_id = fk("projects.id", "SET NULL", index=True)
    assigned_by = fk("users.id", nullable=False, index=True)
    assigned_to = fk("users.id", nullable=False, index=True)
    priority = Column(String(10), default="medium", nullable=False)
    start_date = Column(Date)
    deadline = Column(Date)
    estimated_hours = Column(Numeric(6, 1))
    status = Column(String(20), default="assigned", nullable=False, index=True)
    review_status = Column(String(30), default="none", nullable=False)
    submitted_at = Column(UTCDateTime)
    completed_at = Column(UTCDateTime)
    deleted_at = Column(UTCDateTime)
    # build 16: review routing, acceptance, life-cycle stamps
    reviewer_id = fk("users.id", "SET NULL", index=True)     # On-Roll reviewer chosen by the admin (optional)
    deliverables = Column(Text)                               # expected deliverables
    group_code = Column(String(20), index=True)               # same value on tasks created together for several people
    accepted_at = Column(UTCDateTime)
    started_at = Column(UTCDateTime)
    cancelled_at = Column(UTCDateTime)
    archived_at = Column(UTCDateTime)
    reminded_on = Column(Date)                                # last day a deadline reminder was sent


class TaskHistory(Base, Stamped):
    """Append-only history of a task. No API updates or deletes these rows."""
    __tablename__ = "task_history"
    id = Column(Integer, primary_key=True)
    task_id = fk("tasks.id", "CASCADE", nullable=False, index=True)
    user_id = fk("users.id", "SET NULL", index=True)
    user_role = Column(String(20))
    action = Column(String(40), nullable=False)
    from_status = Column(String(30))
    to_status = Column(String(30))
    comment = Column(Text)
    submission_id = Column(Integer, index=True)               # version this entry belongs to, if any


class TaskAttachment(Base, Stamped):
    __tablename__ = "task_attachments"
    id = Column(Integer, primary_key=True)
    task_id = fk("tasks.id", "CASCADE", nullable=False, index=True)
    kind = Column(String(12), nullable=False)                 # reference (from the assigner) | deliverable (from the assignee)
    filename = Column(String(200), nullable=False)
    content_type = Column(String(100))
    size_bytes = Column(Integer, nullable=False)
    storage_path = Column(String(400), nullable=False)        # "database" since build 20; older rows: a path on disk
    data = deferred(Column(LargeBinary))                      # the file itself; loaded only when it is downloaded
    uploaded_by = fk("users.id", "SET NULL", index=True)
    submission_id = Column(Integer)                           # set when a deliverable is frozen into a submission
    deleted_at = Column(UTCDateTime)


class TaskTime(Base, Stamped):
    """Working time per task and person, credited by the one work timer."""
    __tablename__ = "task_time"
    __table_args__ = (UniqueConstraint("task_id", "user_id"),)
    id = Column(Integer, primary_key=True)
    task_id = fk("tasks.id", "CASCADE", nullable=False, index=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)
    active_seconds = Column(Integer, default=0, nullable=False)
    paused_seconds = Column(Integer, default=0, nullable=False)
    first_at = Column(UTCDateTime)
    last_at = Column(UTCDateTime)


class FileEvent(Base, Stamped):
    """File-level change log of a workspace: created, edited, renamed, deleted, restored, submitted."""
    __tablename__ = "file_events"
    id = Column(Integer, primary_key=True)
    workspace_id = fk("workspaces.id", "CASCADE", nullable=False, index=True)
    file_id = Column(Integer, index=True)
    path = Column(String(300), nullable=False)
    action = Column(String(12), nullable=False)
    from_path = Column(String(300))
    prev_version_no = Column(Integer)
    version_no = Column(Integer)
    user_id = fk("users.id", "SET NULL", index=True)
    summary = Column(String(200))
    submission_id = Column(Integer)


class TaskAssignment(Base, Stamped):
    """Assignment history (a task can be re-assigned)."""
    __tablename__ = "task_assignments"
    id = Column(Integer, primary_key=True)
    task_id = fk("tasks.id", "CASCADE", nullable=False, index=True)
    assigned_by = fk("users.id", nullable=False, index=True)
    assigned_to = fk("users.id", nullable=False, index=True)


class Workspace(Base, Stamped):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("task_id", "user_id"),)
    id = Column(Integer, primary_key=True)
    task_id = fk("tasks.id", "CASCADE", nullable=False, index=True)
    user_id = fk("users.id", nullable=False, index=True)
    project_id = fk("projects.id", "SET NULL", index=True)
    last_saved_at = Column(UTCDateTime)


class WorkspaceFile(Base, Stamped):
    __tablename__ = "workspace_files"
    __table_args__ = (UniqueConstraint("workspace_id", "path"),)
    id = Column(Integer, primary_key=True)
    workspace_id = fk("workspaces.id", "CASCADE", nullable=False, index=True)
    path = Column(String(300), nullable=False)
    content = Column(Text, default="", nullable=False)
    deleted_at = Column(UTCDateTime)


class FileVersion(Base, Stamped):
    __tablename__ = "file_versions"
    __table_args__ = (UniqueConstraint("file_id", "version_no"),)
    id = Column(Integer, primary_key=True)
    file_id = fk("workspace_files.id", "CASCADE", nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    saved_by = fk("users.id", "SET NULL", index=True)
    kind = Column(String(10), default="auto", nullable=False)  # auto|manual|restore|submit


class Submission(Base, Stamped):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("task_id", "version_no"),)
    id = Column(Integer, primary_key=True)
    task_id = fk("tasks.id", "CASCADE", nullable=False, index=True)
    workspace_id = fk("workspaces.id", "CASCADE", nullable=False, index=True)
    submitted_by = fk("users.id", nullable=False, index=True)
    submitter_role = Column(String(20), nullable=False)  # role at the moment of submission
    version_no = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=False)  # [{path, content}] frozen copy
    stage = Column(String(20), nullable=False, index=True)  # onroll_review|admin_review|closed
    status = Column(String(30), nullable=False, index=True)
    # pending_onroll_review|pending_admin_review|changes_requested|rejected|approved
    submitted_at = Column(UTCDateTime, default=utcnow, nullable=False)
    # build 16
    version_label = Column(String(12))                        # 1.0, 1.1, 1.2 … 2.0
    note = Column(Text)                                       # submission notes from the employee
    changes = Column(JSON)                                    # {added: [], modified: [], deleted: []} against the previous version
    authors = Column(JSON)                                    # {path: {user_id, name, at}} who last changed each file
    decided_at = Column(UTCDateTime)


@event.listens_for(Submission, "before_update")
def _snapshot_is_frozen(mapper, connection, target):
    """A submitted version can never be changed afterwards."""
    for field in ("snapshot", "version_no", "task_id", "submitted_by", "version_label"):
        hist = attributes.get_history(target, field)
        if hist.deleted and hist.added and list(hist.deleted) != list(hist.added):
            raise ValueError(f"Submission.{field} is immutable")


class Review(Base, Stamped):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True)
    submission_id = fk("submissions.id", "CASCADE", nullable=False, index=True)
    reviewer_id = fk("users.id", nullable=False, index=True)
    stage = Column(String(20), nullable=False)  # developer_review|admin_review
    decision = Column(String(20), nullable=False)  # approved|changes_requested|rejected
    comment = Column(Text)


class ReviewComment(Base, Stamped):
    __tablename__ = "review_comments"
    id = Column(Integer, primary_key=True)
    submission_id = fk("submissions.id", "CASCADE", nullable=False, index=True)
    review_id = fk("reviews.id", "CASCADE", index=True)
    author_id = fk("users.id", nullable=False, index=True)
    file_path = Column(String(300))
    line_no = Column(Integer)
    body = Column(Text, nullable=False)


# ---------- time & activity ----------
class WorkSession(Base, Stamped):
    __tablename__ = "work_sessions"
    id = Column(Integer, primary_key=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)
    started_at = Column(UTCDateTime, default=utcnow, nullable=False)
    ended_at = Column(UTCDateTime)
    last_heartbeat_at = Column(UTCDateTime, default=utcnow, nullable=False)
    state = Column(String(10), default="running", nullable=False, index=True)  # running|paused|ended
    client_state = Column(String(10), default="active", nullable=False)  # active|away|idle
    client_id = Column(String(64))  # the one browser tab allowed to report
    active_seconds = Column(Integer, default=0, nullable=False)
    away_seconds = Column(Integer, default=0, nullable=False)
    idle_seconds = Column(Integer, default=0, nullable=False)
    paused_seconds = Column(Integer, default=0, nullable=False)
    end_reason = Column(String(20))
    last_return_at = Column(UTCDateTime)  # last time the user came back from away/idle
    # automatic timer (migration 0003)
    mode = Column(String(20), default="RUNNING", nullable=False, server_default="RUNNING")  # effective state, decided by the server
    last_activity_at = Column(UTCDateTime)   # last time genuine activity was reported
    ext_category = Column(String(12))        # what the browser extension last reported: workcode|approved|unapproved|unfocused
    ext_domain = Column(String(120))         # only ever an approved domain; other sites are never stored
    ext_idle = Column(Boolean, default=False, nullable=False, server_default="0")
    ext_at = Column(UTCDateTime)             # when the extension last reported
    task_id = Column(Integer)                                 # task the user is working on right now (for task_time)
    # build 29: "regular" counts toward the 8 h workday; "extra" (Continue Working) is tracked on its own
    schedule = Column(String(10), nullable=False, default="regular", server_default="regular")  # regular|extra


class TimerEvent(Base, Stamped):
    """Every change of timer state (pause / resume history)."""
    __tablename__ = "timer_events"
    id = Column(Integer, primary_key=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)
    session_id = fk("work_sessions.id", "CASCADE", nullable=False, index=True)
    at = Column(UTCDateTime, nullable=False, index=True)
    from_state = Column(String(20))
    to_state = Column(String(20), nullable=False)
    reason = Column(String(30), nullable=False)
    category = Column(String(20))            # workcode | approved_external | None


class AllowedSite(Base, Stamped):
    """Approved external work websites (admin-managed). The timer keeps running on these, via the extension."""
    __tablename__ = "website_allowlist"
    id = Column(Integer, primary_key=True)
    domain = Column(String(120), nullable=False, unique=True)
    label = Column(String(80))
    ignore_inactivity = Column(Boolean, default=False, nullable=False, server_default="0")  # e.g. meetings: listening counts
    created_by = fk("users.id", "SET NULL", index=True)


class Attendance(Base, Stamped):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("user_id", "day"),)
    id = Column(Integer, primary_key=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)
    day = Column(Date, nullable=False, index=True)
    first_login_at = Column(UTCDateTime)
    last_seen_at = Column(UTCDateTime)
    active_seconds = Column(Integer, default=0, nullable=False)
    away_seconds = Column(Integer, default=0, nullable=False)
    idle_seconds = Column(Integer, default=0, nullable=False)
    paused_seconds = Column(Integer, default=0, nullable=False)
    status = Column(String(15), default="present", nullable=False)
    # build 29: the separate Continue schedule; its seconds never touch active_seconds
    extra_seconds = Column(Integer, default=0, nullable=False, server_default="0")
    regular_completed_at = Column(UTCDateTime)   # server time the 8 h regular schedule was completed


class ActivityLog(Base, Stamped):
    __tablename__ = "activity_logs"
    id = Column(Integer, primary_key=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)
    session_id = fk("work_sessions.id", "SET NULL", index=True)
    kind = Column(String(40), nullable=False, index=True)
    detail = Column(JSON)
    ip_address = Column(String(64))


class ScreenRecording(Base, Stamped):
    __tablename__ = "screen_recordings"
    id = Column(Integer, primary_key=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)
    session_id = fk("work_sessions.id", "SET NULL", index=True)
    task_id = fk("tasks.id", "SET NULL", index=True)
    storage_path = Column(String(400))
    mime_type = Column(String(60))
    size_bytes = Column(Integer, default=0, nullable=False)
    status = Column(String(20), default="recording", nullable=False)
    consent_at = Column(UTCDateTime)
    started_at = Column(UTCDateTime, default=utcnow, nullable=False)
    ended_at = Column(UTCDateTime)
    retention_until = Column(UTCDateTime)   # build 29: when the video and its chunks are deleted automatically


class RecordingChunk(Base):
    """The video of a screen recording, stored in the database in the pieces the browser uploaded."""
    __tablename__ = "recording_chunks"
    __table_args__ = (UniqueConstraint("recording_id", "seq"),)
    id = Column(Integer, primary_key=True)
    recording_id = fk("screen_recordings.id", "CASCADE", nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    data = deferred(Column(LargeBinary, nullable=False))


class AuditLog(Base, Stamped):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    actor_id = fk("users.id", "SET NULL", index=True)
    action = Column(String(60), nullable=False, index=True)
    entity = Column(String(40), nullable=False)
    record_id = Column(String(40))
    previous_value = Column(JSON)
    new_value = Column(JSON)
    ip_address = Column(String(64))


# ---------- communication ----------
class Notification(Base, Stamped):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = fk("users.id", "CASCADE", nullable=False)
    type = Column(String(40), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text)
    link = Column(String(300))
    is_read = Column(Boolean, default=False, nullable=False)


Index("ix_notifications_user_unread", Notification.user_id, Notification.is_read)


class ChatConversation(Base, Stamped):
    __tablename__ = "chat_conversations"
    id = Column(Integer, primary_key=True)
    kind = Column(String(15), nullable=False)  # direct|group|announcement
    title = Column(String(150))
    created_by = fk("users.id", "SET NULL", index=True)


class ChatMember(Base, Stamped):
    __tablename__ = "chat_members"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id"),)
    id = Column(Integer, primary_key=True)
    conversation_id = fk("chat_conversations.id", "CASCADE", nullable=False, index=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)
    last_read_message_id = Column(Integer)


class ChatMessage(Base, Stamped):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True)
    conversation_id = fk("chat_conversations.id", "CASCADE", nullable=False, index=True)
    sender_id = fk("users.id", nullable=False, index=True)
    body = Column(Text)
    attachment_path = Column(String(400))
    attachment_name = Column(String(200))
    deleted_at = Column(UTCDateTime)


class Meeting(Base, Stamped):
    __tablename__ = "meetings"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    agenda = Column(Text)
    starts_at = Column(UTCDateTime, nullable=False, index=True)
    duration_minutes = Column(Integer, default=30, nullable=False)
    link = Column(String(400))
    created_by = fk("users.id", nullable=False, index=True)
    cancelled_at = Column(UTCDateTime)


class MeetingParticipant(Base, Stamped):
    __tablename__ = "meeting_participants"
    __table_args__ = (UniqueConstraint("meeting_id", "user_id"),)
    id = Column(Integer, primary_key=True)
    meeting_id = fk("meetings.id", "CASCADE", nullable=False, index=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)
    response = Column(String(15), default="invited", nullable=False)


class MeetingAttendance(Base, Stamped):
    """Meeting timer (build 27): one row per stay of a person in an external meeting (Google Meet, Zoom, Teams ...).
    Separate from the work timer: nothing here is read or written by app/services/timer.py."""
    __tablename__ = "meeting_attendance"
    id = Column(Integer, primary_key=True)
    meeting_id = fk("meetings.id", "CASCADE", nullable=False, index=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)
    joined_at = Column(UTCDateTime, nullable=False, index=True)
    left_at = Column(UTCDateTime)                                       # empty = in the meeting now
    last_seen_at = Column(UTCDateTime, nullable=False)                  # last report that the meeting is still open
    source = Column(String(15), default="manual", nullable=False)       # extension = meeting tab seen by the browser extension · manual = Join / Leave buttons
    end_reason = Column(String(20))                                     # left · tab_closed · no_signal · limit · switched · cancelled


# ---- AI assistant (build 17) -------------------------------------------------------------
class AIProvider(Base, Stamped):
    """An AI service the admin configured. The API key is stored encrypted and never returned by the API."""
    __tablename__ = "ai_providers"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    kind = Column(String(20), default="openai", nullable=False)       # openai = any OpenAI-compatible API
    base_url = Column(String(300), nullable=False)
    api_key_enc = Column(Text)
    models = Column(JSON, default=list, nullable=False)                # model ids offered to users
    default_model = Column(String(120))
    is_enabled = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(UTCDateTime)


class AISetting(Base, Stamped):
    """One row (id 1): who may use the assistant and how much."""
    __tablename__ = "ai_settings"
    id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, default=True, nullable=False)
    role_enabled = Column(JSON, nullable=False)                        # {role: bool}
    daily_limits = Column(JSON, nullable=False)                        # {role: messages per day, 0 = no limit}
    max_context_chars = Column(Integer, default=60000, nullable=False)
    max_output_tokens = Column(Integer, default=4000, nullable=False)
    extra_instructions = Column(Text)


class AIConversation(Base, Stamped):
    """A private chat of one user, optionally tied to a task (project)."""
    __tablename__ = "ai_conversations"
    id = Column(Integer, primary_key=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)
    title = Column(String(160), nullable=False)
    task_id = fk("tasks.id", "SET NULL", index=True)
    workspace_id = Column(Integer)
    model = Column(String(160))
    deleted_at = Column(UTCDateTime)


class AIMessage(Base, Stamped):
    __tablename__ = "ai_messages"
    id = Column(Integer, primary_key=True)
    conversation_id = fk("ai_conversations.id", "CASCADE", nullable=False, index=True)
    user_id = fk("users.id", "CASCADE", nullable=False, index=True)
    role = Column(String(10), nullable=False)                          # user | assistant
    content = Column(Text, default="", nullable=False)
    context = Column(JSON)                                             # user message: what project context was sent
    provider_id = Column(Integer)
    model = Column(String(120))
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    status = Column(String(12), default="ok", nullable=False)          # ok | streaming | stopped | error
    error = Column(String(300))
    saved = Column(Boolean, default=False, nullable=False)
