-- API Doctor schema, revision 1.
--
-- Shape: promoted columns for everything queried, filtered or sorted on, plus
-- the full Pydantic model as JSONB. That hybrid is deliberate. The models here
-- are deep (a repair session embeds attempts, diffs, test runs and evidence),
-- and flattening them into forty columns would mean a migration every time the
-- agent learns a new field. Storing the authoritative record as JSONB keeps the
-- models free to evolve; the columns exist so the database, not Python, does
-- the filtering and ordering.
--
-- Note there is no foreign key from projects.owner to users.id. `owner` holds a
-- tenant, which is a user id under AUTH_MODE=user but an API-key tenant or the
-- shared "public" tenant in the other modes. A constraint here would break
-- those deployments.

CREATE TABLE IF NOT EXISTS users (
    id             TEXT PRIMARY KEY,
    name           TEXT        NOT NULL,
    -- Stored already lowercased and trimmed by the service; UNIQUE is what
    -- actually prevents two accounts on one address when two registrations
    -- race each other.
    email          TEXT        NOT NULL UNIQUE,
    password_hash  TEXT        NOT NULL,
    email_verified BOOLEAN     NOT NULL DEFAULT FALSE,
    status         TEXT        NOT NULL DEFAULT 'pending',
    -- Bumped on password reset; every session issued at a lower epoch dies.
    session_epoch  INTEGER     NOT NULL DEFAULT 0,
    last_login_at  TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Settings-page preferences. Added by revision 2; declared here too so a
    -- fresh database gets the column from the initial schema rather than
    -- depending on the ALTER running afterwards.
    preferences    JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS projects (
    id            TEXT PRIMARY KEY,
    owner         TEXT        NOT NULL,
    name          TEXT        NOT NULL,
    source        TEXT        NOT NULL,
    status        TEXT        NOT NULL,
    origin        TEXT,
    description   TEXT,
    error         TEXT,
    metadata      JSONB,
    stats         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    upload_report JSONB,
    -- Denormalised out of metadata so the quota check is one SUM, not a scan
    -- through every project's JSON.
    size_bytes    BIGINT      NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    record        JSONB       NOT NULL
);

-- The project list is the most-hit query in the app, and it is always
-- "this tenant's projects, newest first".
CREATE INDEX IF NOT EXISTS projects_owner_updated_idx
    ON projects (owner, updated_at DESC);

CREATE TABLE IF NOT EXISTS repair_sessions (
    id         TEXT PRIMARY KEY,
    project_id TEXT        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    owner      TEXT        NOT NULL,
    verdict    TEXT        NOT NULL,
    verified   BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    record     JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS repair_sessions_project_idx
    ON repair_sessions (project_id, created_at DESC);
-- Powers the dashboard and history, which are per-tenant and never per-project.
CREATE INDEX IF NOT EXISTS repair_sessions_owner_idx
    ON repair_sessions (owner, created_at DESC);

CREATE TABLE IF NOT EXISTS executions (
    id         TEXT PRIMARY KEY,
    project_id TEXT        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    owner      TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    record     JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS executions_project_idx
    ON executions (project_id, created_at DESC);
