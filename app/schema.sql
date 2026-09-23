CREATE TABLE IF NOT EXISTS business_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    industry TEXT NOT NULL,
    contact TEXT NOT NULL,
    is_demo INTEGER NOT NULL DEFAULT 1 CHECK (is_demo IN (0, 1))
);

CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    interests TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(interests)),
    skills TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(skills)),
    technologies TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(technologies)),
    is_demo INTEGER NOT NULL DEFAULT 1 CHECK (is_demo IN (0, 1))
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES business_profiles(id) ON DELETE RESTRICT,
    original_text TEXT NOT NULL CHECK (length(trim(original_text)) > 0),
    draft_text TEXT NOT NULL CHECK (length(trim(draft_text)) > 0),
    topic TEXT NOT NULL DEFAULT '',
    questions TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(questions)),
    answers TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(answers)),
    proposed_card TEXT NOT NULL CHECK (json_valid(proposed_card)),
    confirmed_card TEXT CHECK (confirmed_card IS NULL OR json_valid(confirmed_card)),
    confirmed_rating TEXT CHECK (confirmed_rating IS NULL OR json_valid(confirmed_rating)),
    published_card TEXT CHECK (published_card IS NULL OR json_valid(published_card)),
    published_rating TEXT CHECK (published_rating IS NULL OR json_valid(published_rating)),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
    confirmed_at TEXT,
    published_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((confirmed_card IS NULL AND confirmed_at IS NULL AND confirmed_rating IS NULL)
        OR (confirmed_card IS NOT NULL AND confirmed_at IS NOT NULL AND confirmed_rating IS NOT NULL)),
    CHECK ((status = 'draft' AND published_card IS NULL AND published_rating IS NULL AND published_at IS NULL)
        OR (status = 'published' AND published_card IS NOT NULL AND published_rating IS NOT NULL
            AND published_at IS NOT NULL AND confirmed_card IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(business_id);

CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
    idea TEXT NOT NULL,
    plan TEXT NOT NULL,
    timeline TEXT NOT NULL,
    prototype_url TEXT,
    questions TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'selected', 'rejected')),
    created_at TEXT NOT NULL,
    decided_at TEXT,
    CHECK ((status = 'submitted' AND decided_at IS NULL) OR (status != 'submitted' AND decided_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_proposals_task ON proposals(task_id);
CREATE INDEX IF NOT EXISTS idx_proposals_team ON proposals(team_id);

CREATE TABLE IF NOT EXISTS milestones (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES proposals(id) ON DELETE RESTRICT,
    description TEXT NOT NULL,
    result_url TEXT,
    status TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'confirmed')),
    points_awarded INTEGER NOT NULL DEFAULT 0 CHECK (points_awarded >= 0),
    created_at TEXT NOT NULL,
    confirmed_at TEXT,
    CHECK ((status = 'submitted' AND points_awarded = 0 AND confirmed_at IS NULL)
        OR (status = 'confirmed' AND confirmed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_milestones_proposal ON milestones(proposal_id);
