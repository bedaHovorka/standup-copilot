--liquibase formatted sql
-- Schema for the shared memory database (data/memory.db).
-- Single source of truth for every table used by server/memory_dao.py,
-- applied idempotently on each connection (CREATE TABLE IF NOT EXISTS).
-- Written as a Liquibase Formatted SQL changelog so it can also be run
-- with `liquibase update` if a tracked-migration workflow is added later.

--changeset standup-copilot:1
CREATE TABLE IF NOT EXISTS tracked_repos (
    repo TEXT PRIMARY KEY,          -- "owner/name"
    added_on TEXT NOT NULL
);

--changeset standup-copilot:2
CREATE TABLE IF NOT EXISTS standups (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,              -- ISO date
    yesterday TEXT NOT NULL,
    today TEXT NOT NULL,
    blockers TEXT NOT NULL DEFAULT ''
);

--changeset standup-copilot:3
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

--changeset standup-copilot:4
CREATE TABLE IF NOT EXISTS expectations (
    id INTEGER PRIMARY KEY,
    created_on TEXT NOT NULL,
    item TEXT NOT NULL,           -- what is expected from the user
    requested_by TEXT NOT NULL DEFAULT '',
    due TEXT NOT NULL DEFAULT '', -- free-form or ISO date
    status TEXT NOT NULL DEFAULT 'open'  -- open | done | dropped
);

--changeset standup-copilot:5
CREATE TABLE IF NOT EXISTS reminders (
    expectation_id INTEGER PRIMARY KEY,
    last_reminded TEXT NOT NULL
);
