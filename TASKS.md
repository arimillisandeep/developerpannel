# Task management, review, approval and version control (build 16)

Four panels only: **Admin, On-Roll, Off-Roll, Intern**. The old Developer role is retired
(migration 0004 converts existing Developer accounts to On-Roll; they keep their teams).

## Review route (enforced in the backend)

| Who did the work | First review | Final approval |
|---|---|---|
| Intern, Off-Roll | On-Roll reviewer | Admin |
| On-Roll | none, goes directly | Admin |

- The On-Roll reviewer is the one chosen on the task; if none is chosen, the On-Roll lead of the
  employee's team; if there is no lead, any On-Roll user.
- Nobody can review their own work. Admin cannot skip the On-Roll stage. Only Admin approval sets COMPLETED.
- Reject and "request rework" need a written reason. After a rejection (also an Admin rejection)
  the next submission goes through the full route again.

## Statuses

CREATED, ASSIGNED, ACCEPTED, IN_PROGRESS, SUBMITTED, UNDER_ONROLL_REVIEW, ONROLL_APPROVED, ONROLL_REJECTED,
UNDER_ADMIN_REVIEW, ADMIN_APPROVED, ADMIN_REJECTED, REWORK_REQUIRED, RESUBMITTED, COMPLETED, CANCELLED, ARCHIVED
(stored in lower case). A status changes only inside `services/workflow.py: move()`, in the same database
transaction as the action, and every change writes a row to `task_history` (who, role, action, from, to,
comment, version). Some statuses are passed through within one request (for example SUBMITTED →
UNDER_ONROLL_REVIEW), so you see them in the history, not in the list.

Files can be edited only in ACCEPTED, IN_PROGRESS, REWORK_REQUIRED, ONROLL_REJECTED, ADMIN_REJECTED.
A task must be accepted first; during review the project is locked.

## Versions

- Every submit freezes the whole project into a new version: 1.0, 1.1, 1.2 … After a version was finally
  approved, Admin can "Reopen"; the next submission is then 2.0.
- A version stores: files, who submitted (name, role), time, added / modified / deleted files, note,
  who last changed each file, reviews, result, and the deliverable files uploaded for it.
- A stored version can never be changed (the database layer refuses it). Tasks are soft-deleted, so
  versions are never removed.
- Compare any two versions (real line diff), download a version as zip, run a file of the submitted
  version, restore a version into the workspace (assignee only, only while the task is editable; the
  current files stay in each file's saved versions).
- Submitting with no change since the last version is refused ("Nothing changed").

## File history

Workspace → 🕘 File history: created, edited, renamed, deleted, restored, submitted, with path,
previous → new file version, who, when and a line summary.

## Timer

No second timer. While your own editable task is open in the workspace, the existing work timer also
books each interval on that Task ID + User ID (active and paused seconds). The task shows active,
paused, total and review time, plus started / submitted / completed times.

## Where things are

- Admin: **Tasks** (All assignments, Pending approvals, With On-Roll reviewer, Rework / rejected, Completed,
  Cancelled / archived; Assign a task) and **Code reviews** (Pending final approval, With On-Roll reviewer,
  Approved, Rejected / rework, All versions, My review history). Task reports and the audit log are the
  existing Reports and Audit log pages.
- On-Roll: **Tasks** (My tasks, Assigned by me, All I can see, My rework, Completed) and **Reviews**
  (Pending reviews, Intern submissions, Off-Roll submissions, Approved, Rejected, Review history,
  My own submissions). Version comparison is inside each review and each task.
- Off-Roll / Intern: **My tasks** (My tasks, In progress, Submitted, Rework required, Completed) and
  **My submissions**. Version history is inside each task.

## Main API

`POST /api/tasks` (`assigned_to_ids`, `reviewer_id`, `deliverables`), `POST /api/tasks/{id}/accept|start|cancel|archive|reopen`,
`GET /api/tasks/{id}/history|versions|compare?a=&b=`, `POST|GET|DELETE /api/tasks/{id}/attachments`,
`POST /api/workspaces/{id}/submit {note}`, `GET /api/workspaces/{id}/history`,
`GET /api/submissions?view=queue|mine|all|reviewed`, `GET /api/submissions/{id}`,
`POST /api/submissions/{id}/review|comments|run|restore`, `GET /api/submissions/{id}/download`,
`GET /api/users/reviewers`.

## Not in this build

- "Install permitted packages" and live preview of React/Node projects need IDE Phase B (not built).
- Run needs Docker Desktop on the server PC; without it the app answers "runner not available".
- Deadline reminders are sent when somebody opens the task list (at most every 10 minutes); there is no
  background worker.
- Notifications are in-app only (no e-mail).
- Assigning to several people creates one task per person (own Task ID, workspace and review), linked
  as "Same assignment". There is no shared workspace for several people.

## Check it yourself

`python backend/scripts/live_task_check.py` runs the whole flow (35 checks) against a running demo
server with the demo logins.
