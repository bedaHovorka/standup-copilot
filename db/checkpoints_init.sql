--liquibase formatted sql
-- Reference-only schema for data/checkpoints.db, actually created and
-- migrated by langgraph-checkpoint-sqlite's AsyncSqliteSaver.setup() at
-- runtime (see agent/graph.py build_agent()). This file is NOT executed by
-- any code in this repo - it documents the current library-owned schema for
-- readers browsing db/, and may drift if the library's internal schema
-- changes on upgrade. Do not hand-edit data/checkpoints.db against this file.

--changeset standup-copilot:1
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint BLOB,
    metadata BLOB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

--changeset standup-copilot:2
CREATE TABLE IF NOT EXISTS writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    value BLOB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
