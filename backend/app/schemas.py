from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

Role = Literal["admin", "developer", "onroll", "offroll", "intern"]
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(min_length=1, max_length=200)


class ForgotPasswordIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class ResetTokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


class UserCreate(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=255)
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(min_length=2, max_length=150)
    role: Role
    phone: Optional[str] = Field(None, max_length=30)
    department_id: Optional[int] = None
    reporting_manager_id: Optional[int] = None
    joining_date: Optional[date] = None
    contract_start: Optional[date] = None
    contract_end: Optional[date] = None
    compensation: Optional[float] = Field(None, ge=0)
    responsibilities: Optional[str] = Field(None, max_length=2000)


class UserUpdate(BaseModel):
    email: Optional[str] = Field(None, pattern=EMAIL, max_length=255)
    full_name: Optional[str] = Field(None, min_length=2, max_length=150)
    phone: Optional[str] = Field(None, max_length=30)
    department_id: Optional[int] = None
    reporting_manager_id: Optional[int] = None
    joining_date: Optional[date] = None
    contract_start: Optional[date] = None
    contract_end: Optional[date] = None
    compensation: Optional[float] = Field(None, ge=0)
    responsibilities: Optional[str] = Field(None, max_length=2000)
    performance_note: Optional[str] = Field(None, max_length=4000)
    new_password: Optional[str] = Field(None, min_length=8, max_length=200)


class DeactivateIn(BaseModel):
    status: Literal["inactive", "left", "completed"] = "inactive"
    reason: Optional[str] = Field(None, max_length=1000)


class ConvertIn(BaseModel):
    to_role: Literal["offroll", "onroll", "developer"]
    reason: Optional[str] = Field(None, max_length=1000)
    confirm_early: bool = False


class NameIn(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: Optional[str] = Field(None, max_length=4000)


class TeamIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    lead_developer_id: Optional[int] = None


class TeamUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    lead_developer_id: Optional[int] = None


class MemberIn(BaseModel):
    user_id: int


class VacancyIn(BaseModel):
    target_headcount: int = Field(ge=0, le=1000)


class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: Optional[str] = Field(None, max_length=10000)
    requirements: Optional[str] = Field(None, max_length=10000)
    project_id: Optional[int] = None
    assigned_to: Optional[int] = None
    assigned_to_ids: Optional[list[int]] = Field(None, max_length=50)   # several people: one task each, same group
    reviewer_id: Optional[int] = None                                   # On-Roll reviewer
    deliverables: Optional[str] = Field(None, max_length=10000)
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    start_date: Optional[date] = None
    deadline: Optional[date] = None
    estimated_hours: Optional[float] = Field(None, ge=0, le=9999)


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=200)
    description: Optional[str] = Field(None, max_length=10000)
    requirements: Optional[str] = Field(None, max_length=10000)
    project_id: Optional[int] = None
    assigned_to: Optional[int] = None
    reviewer_id: Optional[int] = None
    deliverables: Optional[str] = Field(None, max_length=10000)
    priority: Optional[Literal["low", "medium", "high", "urgent"]] = None
    start_date: Optional[date] = None
    deadline: Optional[date] = None
    estimated_hours: Optional[float] = Field(None, ge=0, le=9999)


class FileSave(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    content: str = ""
    manual: bool = False


class FileRename(BaseModel):
    new_path: str = Field(min_length=1, max_length=300)


class ReviewIn(BaseModel):
    decision: Literal["approved", "changes_requested", "rejected"]
    comment: Optional[str] = Field(None, max_length=5000)


class NoteIn(BaseModel):
    comment: Optional[str] = Field(None, max_length=5000)


class SubmitIn(BaseModel):
    note: Optional[str] = Field(None, max_length=5000)


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    file_path: Optional[str] = Field(None, max_length=300)
    line_no: Optional[int] = Field(None, ge=1)


class HeartbeatIn(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)
    state: Literal["active", "away", "idle"] = "active"
    task_id: Optional[int] = None      # the task whose workspace is open; its time is credited to task_time


class ClientIn(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)
    auto: bool = False        # True = automatic start when the app opens (never overrides a manual Stop)


class ExtensionReport(BaseModel):
    category: Literal["workcode", "approved", "unapproved", "unfocused"]
    domain: str | None = Field(default=None, max_length=120)   # sent only for approved sites
    idle: Literal["active", "idle", "locked"] = "active"


class ExtensionMeetings(BaseModel):
    open_ids: list[int] = Field(default_factory=list, max_length=50)   # scheduled meetings whose page is open in the browser


class AllowedSiteIn(BaseModel):
    domain: str = Field(min_length=3, max_length=200)
    label: str | None = Field(default=None, max_length=80)
    ignore_inactivity: bool = False


class MeetingIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    agenda: Optional[str] = Field(None, max_length=4000)
    starts_at: datetime
    duration_minutes: int = Field(30, ge=5, le=600)
    link: Optional[str] = Field(None, max_length=400, pattern=r"^https://[^\s]+$")
    participant_ids: list[int] = Field(min_length=1, max_length=200)


class ConversationIn(BaseModel):
    kind: Literal["direct", "group", "announcement"] = "direct"
    title: Optional[str] = Field(None, max_length=150)
    user_ids: list[int] = Field(default_factory=list, max_length=500)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class RecordingStart(BaseModel):
    consent: bool
    task_id: Optional[int] = None
    mime_type: str = Field("video/webm", max_length=60)


class RunIn(BaseModel):
    file_id: int
    stdin: str = Field(default="", max_length=20000)


class PathMove(BaseModel):
    from_path: str = Field(min_length=1, max_length=300)
    to_path: str = Field(min_length=1, max_length=300)


class TemplateApply(BaseModel):
    template_id: str = Field(min_length=1, max_length=40)
    overwrite: bool = False
