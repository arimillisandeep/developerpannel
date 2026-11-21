-- WORKCODE — timer and extra (Continue) timer: how to read it straight from PostgreSQL
-- ---------------------------------------------------------------------------
-- Run in pgAdmin (Query Tool) or psql against the workcode_v2 database.
-- Facts these queries rely on (from the app's own model, migration 0010):
--   * work_sessions.schedule  = 'regular' | 'extra'   → the Continue schedule is the 'extra' row
--   * attendance.active_seconds  = regular hours      (extra time is NEVER added here)
--   * attendance.extra_seconds   = Continue hours     (only sessions with schedule='extra' land here)
--   * attendance.regular_completed_at is set when the 8 h schedule closed (end_reason 'day_complete')
--   * every *_at column is "timestamp with time zone" stored in UTC; attendance.day is a LOCAL day
--     (the server uses TIMEZONE=Asia/Kolkata), so "today" is computed in that zone below.
--   * the 8 h target is WORKDAY_TARGET_HOURS * 3600 = 28800 seconds; change the one number in `target`.

-- 0 ─ Is this database migrated far enough for the extra timer? (all four must be 1, migration 0010)
select (select version_num from alembic_version)                                as migration,
       (select count(*) from information_schema.columns
         where table_name='work_sessions'     and column_name='schedule')               as work_sessions_schedule,
       (select count(*) from information_schema.columns
         where table_name='attendance'        and column_name='extra_seconds')          as attendance_extra_seconds,
       (select count(*) from information_schema.columns
         where table_name='attendance'        and column_name='regular_completed_at')   as regular_completed_at,
       (select count(*) from information_schema.columns
         where table_name='screen_recordings' and column_name='retention_until')        as recording_retention_until;


-- 1 ─ TODAY, per person: regular hours vs extra hours (this is the Admin "Extra work today" table)
with target as (select 28800 as secs)
select coalesce(ep.employee_code, '—')                     as id,
       u.full_name,
       u.role,
       to_char(make_interval(secs => a.active_seconds), 'FMHH24"H" FMMI"M"')  as regular_time,
       case when a.regular_completed_at is not null then 'Completed'
            when u.role in ('developer','onroll','offroll') and a.active_seconds >= t.secs then 'At target'
            else 'In progress' end                         as status,
       to_char(make_interval(secs => a.extra_seconds),  'FMHH24"H" FMMI"M"')  as extra_time,
       (a.regular_completed_at at time zone 'Asia/Kolkata') as regular_closed_at,
       to_char(make_interval(secs => a.away_seconds),  'FMHH24:MI:ss')        as away,
       to_char(make_interval(secs => a.paused_seconds), 'FMHH24:MI:ss')       as paused,
       a.status                                             as attendance_state
from attendance a
join users u            on u.id = a.user_id
left join employee_profiles ep on ep.user_id = u.id
cross join target t
where a.day = (now() at time zone 'Asia/Kolkata')::date
order by a.extra_seconds desc, u.full_name;


-- 2 ─ A period, per person: regular / extra / total hours (what the timer report's "Range totals" line adds up)
with target as (select 28800 as secs)
select u.full_name,
       u.role,
       count(*) filter (where a.regular_completed_at is not null or a.active_seconds >= t.secs) as full_days,
       round(sum(a.active_seconds) / 3600.0, 2)                       as regular_hours,
       round(sum(a.extra_seconds)  / 3600.0, 2)                       as extra_hours,
       round((sum(a.active_seconds) + sum(a.extra_seconds)) / 3600.0, 2) as total_hours
from attendance a
join users u on u.id = a.user_id
cross join target t
where a.day between date '2026-11-01' and date '2026-11-30'          -- ← the range you want
group by u.id, u.full_name, u.role
order by total_hours desc;


-- 3 ─ The ledger: every timer session with its schedule (regular vs Continue)
select u.full_name,
       s.id                                                as session_id,
       s.schedule,
       s.state,
       s.mode,
       to_char(s.started_at at time zone 'Asia/Kolkata', 'DD Mon HH24:MI:ss') as started,
       coalesce(to_char(s.ended_at at time zone 'Asia/Kolkata', 'DD Mon HH24:MI:ss'), 'still open') as ended,
       to_char(make_interval(secs => s.active_seconds), 'FMHH24:MI:ss')       as active,
       to_char(make_interval(secs => s.away_seconds + s.idle_seconds + s.paused_seconds), 'FMHH24:MI:ss') as paused,
       round(extract(epoch from (coalesce(s.ended_at, now()) - s.started_at)) / 60.0, 1) as wall_clock_min,
       coalesce(s.end_reason, '—')                          as end_reason,
       coalesce(t.code, '—')                                as task
from work_sessions s
join users u on u.id = s.user_id
left join tasks t on t.id = s.task_id
where s.started_at >= now() - interval '7 days'
order by s.started_at desc;


-- 4 ─ Who is on the Continue schedule RIGHT NOW (the extra timer is still running)
select u.full_name,
       s.id                                    as extra_session_id,
       to_char(s.started_at at time zone 'Asia/Kolkata', 'DD Mon HH24:MI:ss') as extra_started,
       to_char(make_interval(secs => s.active_seconds), 'FMHH24:MI:ss')       as credited_so_far,
       to_char(make_interval(secs => (extract(epoch from (now() - s.last_heartbeat_at)))::int), 'FMHH24:MI:ss') as since_last_beat,
       s.mode,
       now() - s.last_heartbeat_at > interval '30 minutes'                     as no_signal
from work_sessions s
join users u on u.id = s.user_id
where s.state <> 'ended' and s.schedule = 'extra'
order by s.started_at desc;


-- 5 ─ The 8 h boundary: exactly when each day closed, and what came after it
with target as (select 28800 as secs)
select u.full_name,
       a.day,
       to_char(make_interval(secs => a.active_seconds), 'FMHH24:MI:ss') as regular,
       a.regular_completed_at is not null                                as day_closed,
       to_char(a.regular_completed_at at time zone 'Asia/Kolkata', 'DD Mon HH24:MI:ss') as closed_at,
       to_char(make_interval(secs => a.extra_seconds),  'FMHH24:MI:ss') as extra_afterwards,
       (a.active_seconds >= t.secs)                                      as reached_target
from attendance a
join users u on u.id = a.user_id
cross join target t
where a.day >= (now() at time zone 'Asia/Kolkata')::date - 14
  and (a.extra_seconds > 0 or a.regular_completed_at is not null)
order by a.day desc, u.full_name;


-- 6 ─ Proof that extra time never moved the regular totals (attendance vs the sessions behind it)
with sess as (
  select user_id,
         (started_at at time zone 'Asia/Kolkata')::date                   as day,
         sum(active_seconds) filter (where schedule = 'regular')          as regular_secs,
         sum(active_seconds) filter (where schedule = 'extra')            as extra_secs
  from work_sessions
  group by 1, 2
)
select u.full_name,
       a.day,
       a.active_seconds                          as att_regular,
       coalesce(s.regular_secs, 0)               as session_regular,
       a.active_seconds - coalesce(s.regular_secs, 0) as diff_regular,
       a.extra_seconds                           as att_extra,
       coalesce(s.extra_secs, 0)                 as session_extra,
       a.extra_seconds - coalesce(s.extra_secs, 0)   as diff_extra
from attendance a
join users u on u.id = a.user_id
left join sess s on s.user_id = a.user_id and s.day = a.day
where a.day >= (now() at time zone 'Asia/Kolkata')::date - 14
order by a.day desc, u.full_name;
-- Small differences (a few minutes) are normal: a session can cross midnight and the server only credits
-- a gap for at most HEARTBEAT_MAX_GAP_SECONDS. What must never happen is diff_extra being large while
-- att_extra stays 0 — that would mean extra time leaked into the regular column.


-- 7 ─ Screen recordings attached to those sessions (+ the retention promise)
select u.full_name,
       r.id                                              as recording_id,
       coalesce(s.schedule, 'manual')                     as schedule,
       r.status,
       to_char(r.started_at at time zone 'Asia/Kolkata', 'DD Mon HH24:MI:ss') as started,
       to_char(r.ended_at   at time zone 'Asia/Kolkata', 'DD Mon HH24:MI:ss') as ended,
       round(r.size_bytes / 1048576.0, 2)                 as mb,
       (select count(*) from recording_chunks c where c.recording_id = r.id) as chunks,
       coalesce(t.code, '—')                              as task,
       to_char(r.retention_until at time zone 'Asia/Kolkata', 'DD Mon YYYY') as kept_until,
       r.retention_until < now()                          as due_for_cleanup
from screen_recordings r
join users u on u.id = r.user_id
left join work_sessions s on s.id = r.session_id
left join tasks t          on t.id = r.task_id
order by r.id desc
limit 30;


-- 8 ─ One person, last 7 days (the employee's own "Daily attendance" table)
select a.day,
       to_char(make_interval(secs => a.active_seconds), 'FMHH24:MI:ss') as regular,
       case when a.regular_completed_at is not null then 'done' else '—' end as eight_h,
       to_char(make_interval(secs => a.extra_seconds),  'FMHH24:MI:ss') as extra,
       to_char(make_interval(secs => a.away_seconds),   'FMHH24:MI:ss')  as away,
       to_char(make_interval(secs => a.paused_seconds), 'FMHH24:MI:ss')  as paused,
       a.status
from attendance a
join users u on u.id = a.user_id
where u.email = 'onroll@workcode.local'                                  -- ← whose week you want
  and a.day >= (now() at time zone 'Asia/Kolkata')::date - 6
order by a.day desc;


-- 9 ─ Pause / resume trail of today (why a number is what it is)
select u.full_name,
       to_char(e.at at time zone 'Asia/Kolkata', 'HH24:MI:ss') as at_local,
       coalesce(e.from_state, '—') as from_state,
       e.to_state,
       e.reason,
       coalesce(e.category, '—')    as category,
       coalesce(s.schedule, '—')    as schedule
from timer_events e
join users u on u.id = e.user_id
left join work_sessions s on s.id = e.session_id
where e.at::date = (now() at time zone 'UTC')::date
order by e.at desc
limit 60;
