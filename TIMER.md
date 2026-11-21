# Automatic work timer (build 15)

The existing timer was upgraded in place: same tables (`work_sessions`, `attendance`), same endpoints
(`/api/sessions/*`), same widget. No second timer system was added.

## How it decides

The **server** decides the state from three inputs and measures time with its own clock.

| Input | Sent by | Content |
|---|---|---|
| Tab heartbeat (15 s) | WORKCODE page | `active` (tab in front, input in the last 5 min), `idle` (in front, no input for 5 min), `away` (hidden / not in front) |
| Extension report (30 s + on every tab / window / idle change) | Chrome extension | `workcode`, `approved` (+ approved domain), `unapproved`, `unfocused`; and `active` / `idle` / `locked` |
| Pause / Resume / Stop / Start | the user | |

| State | When | Counts as work |
|---|---|---|
| `RUNNING` | WORKCODE tab in front with input, **or** extension reports an approved website | yes |
| `PAUSED_INACTIVE` | 5 minutes without input (warning shown at 4 minutes) | no |
| `PAUSED_EXTERNAL` | unapproved website, another program in front, or left WORKCODE without a live extension | no |
| `PAUSED_MANUAL` | user pressed Pause; only Resume ends it | no |
| `STOPPED` | user pressed Stop, or logout. After Stop, the automatic start stays off for that day until Start is pressed | – |
| `SESSION_EXPIRED` | no report for 30 minutes; closed at the last report | – |

Rules:
- Active time = session duration − paused duration; each second goes to exactly one bucket, per session and per day.
- One session per user. Several tabs, devices and the extension all report into it; an interval is credited once.
- A silent gap is credited for at most 45 seconds (sleeping laptop, lost network).
- Extension reports older than 75 seconds are ignored, so a stopped or removed extension means "pause when you leave WORKCODE".
- The server checks every "approved" claim against the allowlist. The address of an unapproved site is never sent or stored.
- Meeting sites (`ignore_inactivity`, default: meet.google.com) do not pause after 5 quiet minutes, because listening is work. A locked screen still pauses.
- A meeting stay that stops reporting is counted up to **its last report**, not up to now (build 34.1): a Meet tab that
  was killed or slept cannot inflate the day, and the employee's own dashboard already shows the number the report
  will settle on after the sweep. A stay that is still being reported keeps running.
- The `● live` recording dot in the Admin report means chunks are **still arriving** (within `STALE_SECONDS`, 120 s),
  not that a row with status `recording` exists: a browser that was closed without stopping the recording cannot keep
  claiming that somebody is being filmed (the row itself is repaired to `interrupted` by the recordings list).
- Genuine input = trusted mouse, click, keyboard, scroll, wheel, touch and typing events, including the code editor and the terminal. API calls and scripted events are ignored.

## Without the extension
A web page cannot see other tabs. Without the extension the timer pauses whenever the WORKCODE tab is not in front,
including on ChatGPT and Google Meet. External-site detection works only with the extension.

## Chrome extension (`extension/`)
Install: `chrome://extensions` → Developer mode → Load unpacked → pick the `extension` folder. Then in WORKCODE open
Admins: Monitoring → **Create connection code** → paste it into the extension popup. (Build 20.4 removed the Internet page, which was the only place where other roles could create a code.)

| Permission | Why |
|---|---|
| `tabs` | read the address of the active tab, to compare its host with the approved list (the address stays in the browser) |
| `idle` | know whether the computer was used in the last 5 minutes / is locked |
| `storage` | keep the connection code and the approved list |
| `alarms` | report every 30 seconds |
| WORKCODE address (asked at connect time) | send the report to your WORKCODE server only |

No content scripts. It does not read page content, titles, forms, passwords, messages, cookies or history.

## API
All need `Authorization: Bearer <login token>` unless noted. Dates are `YYYY-MM-DD` in the server's local day.

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/api/sessions/start` `{client_id, auto}` | any | start or rejoin the session; `auto: true` never overrides a manual Stop |
| POST | `/api/sessions/heartbeat` `{client_id, state}` | any | tab report; returns session with `mode`, `pause_reason`, `category`, `extension_connected` |
| POST | `/api/sessions/pause` · `/resume` · `/stop` | any | manual controls |
| GET | `/api/sessions/current` | any | restore after refresh |
| GET | `/api/sessions/live` | admin, developer (team) | who is working now |
| GET | `/api/timer/overview?start&end&role&format=json\|csv` | admin: all · developer: own team · others: self | state, today, active, paused, inactive, last activity, session start / end, category; CSV export |
| GET | `/api/timer/sessions?user_id&start&end` | self, or permitted viewer | sessions with the full pause / resume history |
| GET | `/api/timer/allowlist` | any | approved websites |
| POST | `/api/timer/allowlist` `{domain, label, ignore_inactivity}` | admin | add (domain validated and normalised; audited) |
| DELETE | `/api/timer/allowlist/{id}` | admin | remove (audited) |
| POST | `/api/extension/token` | any | 30-day token with scope `extension`; rejected everywhere except `/api/extension/*` |
| GET | `/api/extension/config` | extension token | approved list, inactivity seconds |
| POST | `/api/extension/report` `{category, domain?, idle}` | extension token | site category report; returns the resulting `mode` |

## Database (migration `0003_automatic_timer`, additive)
- `work_sessions` + `mode`, `last_activity_at`, `ext_category`, `ext_domain`, `ext_idle`, `ext_at`
- `timer_events` (user, session, time, from, to, reason, category): the pause / resume history; indexed by user, session, time
- `website_allowlist` (domain unique, label, ignore_inactivity); seeded with meet.google.com, chatgpt.com, www.chatgpt.com
- Daily summaries stay in the existing `attendance` table (unique per user and day).
- Not added: per-user timer settings. The 5-minute rule is one company-wide setting (`INACTIVITY_TIMEOUT_SECONDS`).

Run `alembic upgrade head` once on an existing database.

## The 20 scenarios
| # | Scenario | Checked by |
|---|---|---|
| 1–5 | Runs in Admin, Developer, On-Roll, Off-Roll, Intern panels | `test_timer_runs_in_all_five_panels` |
| 6–8 | Runs on Meet, ChatGPT, any approved site | `test_approved_sites_run_and_unapproved_sites_pause`, `test_allowlist_is_admin_managed_and_enforced_by_the_server` |
| 9 | Pauses on an unapproved site | same |
| 10 | Warning at 4 minutes | frontend test "warns at 4 minutes…" |
| 11 | Pause at 5 minutes | `test_five_minute_inactivity_pauses_and_activity_resumes` + frontend test |
| 12 | Resume on return and input | same |
| 13 | Activity on an unapproved site stays paused | `test_approved_sites_run…` |
| 14 | Manual stop stays stopped | `test_manual_pause_and_stop_are_respected` + frontend test |
| 15 | Refresh restores the session | same |
| 16 | Several tabs: no double time | `test_two_tabs_and_the_extension_never_double_count` |
| 17 | Network loss reconciled | `test_network_loss_and_extension_loss_are_safe` |
| 18 | Logout closes the session | `test_manual_pause_and_stop_are_respected` |
| 19 | Admin reports correct | `test_admin_overview_history_and_csv` |
| 20 | Extension disconnect → safe pause | `test_network_loss_and_extension_loss_are_safe` |

These are server and component tests. 6–9, 13 and 20 use simulated extension reports: the extension itself was **not run in a
real Chrome** (the build machine has no browser). Its decision logic is tested with `node --test` in `extension/`.

## Known limits
- Extension: Chrome / Edge desktop only; never executed in a real browser yet.
- The page cannot tell real input from an OS-level mouse jiggler.
- Developers see the timer report of their own team; other employees see only themselves.

## The workday: 8 h regular + a separate Continue schedule (build 29)

Applies to Developer, On-Roll and Off-Roll (interns and admins run the plain timer).

- Active time (RUNNING mode seconds) counts toward the regular day of `WORKDAY_TARGET_HOURS` (default 8, env).
  Away / idle / manual-pause seconds never count toward it — same rules as the automatic timer.
- When the day's active seconds reach the target, the server closes the regular session
  (`end_reason = day_complete`) and stamps `attendance.regular_completed_at`. A refresh or re-login sees the state;
  it never restarts the regular session automatically.
- **Continue Working** (the button after completion, or `POST /api/sessions/continue`) starts a separate session with
  `schedule = extra`. Its seconds land in `attendance.extra_seconds` and on its own session row — the regular 8 h
  numbers never change. Pause / Resume / Stop work the same way; while it runs, the timer report shows *continue*.
- The employee can always just stop; the day stays complete either way.
- Reports: the timer overview CSV / table shows *Continue today*, *8 h done*, *Recording now*; `/api/reports/summary`
  reports `extra_hours` and `full_days` separately from active hours.

## The completion popup (build 30)

When the regular day closes (`day_complete`), the employee is asked right in the app: *Continue Working* starts the
extra schedule; *Not Now* dismisses it for the rest of that day. The answer is stored on the device only — the
server state (session closed, day completed) is the same either way, and reopening the app the next day asks again.

## Recording and the workday (build 31)

The recording is tied to the same attention signal as this timer. Opening a workspace starts it (with the person's
own consent and the browser's screen-share dialog — never bypassed); leaving the tab pauses it at once, so nothing
outside the workspace is ever filmed, and after `RECORDING_AWAY_GRACE_SECONDS` (default 60) away it is closed and
saved. Coming back resumes it without another prompt; after a close the workspace asks for one click to start again,
because the browser will not share a screen on its own. Timer seconds and recording state stay independent: leaving
pauses both, and neither one invents time or footage for the other.
