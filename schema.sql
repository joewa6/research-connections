-- Synthetic SUSTech sandbox. Enable foreign keys on every write connection.
PRAGMA foreign_keys = ON;

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE research_areas (
    area_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL
);

CREATE TABLE topics (
    topic_id INTEGER PRIMARY KEY,
    area_id INTEGER NOT NULL REFERENCES research_areas(area_id),
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE capabilities (
    capability_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL
);

CREATE TABLE researchers (
    researcher_id INTEGER PRIMARY KEY,
    researcher_code TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('PI', 'Post-doc', 'PhD')),
    primary_area_id INTEGER NOT NULL REFERENCES research_areas(area_id),
    summary TEXT NOT NULL CHECK (length(trim(summary)) > 0),
    is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic = 1)
);

CREATE TABLE researcher_capabilities (
    researcher_id INTEGER NOT NULL REFERENCES researchers(researcher_id),
    capability_id INTEGER NOT NULL REFERENCES capabilities(capability_id),
    proficiency INTEGER NOT NULL CHECK (proficiency BETWEEN 1 AND 5),
    offer_description TEXT NOT NULL,
    PRIMARY KEY (researcher_id, capability_id)
);

CREATE TABLE projects (
    project_id INTEGER PRIMARY KEY,
    project_code TEXT NOT NULL UNIQUE,
    topic_id INTEGER NOT NULL REFERENCES topics(topic_id),
    title TEXT NOT NULL UNIQUE,
    summary TEXT NOT NULL CHECK (length(trim(summary)) > 0),
    approach TEXT NOT NULL,
    application_context TEXT NOT NULL,
    technical_challenge TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('Concept', 'Lab study', 'Prototype', 'Pilot')),
    is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic = 1)
);

CREATE TABLE researcher_projects (
    researcher_id INTEGER NOT NULL REFERENCES researchers(researcher_id),
    project_id INTEGER NOT NULL REFERENCES projects(project_id),
    contribution TEXT NOT NULL,
    PRIMARY KEY (researcher_id, project_id)
);

CREATE TABLE researcher_needs (
    need_id INTEGER PRIMARY KEY,
    researcher_id INTEGER NOT NULL REFERENCES researchers(researcher_id),
    related_project_id INTEGER NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('Expertise', 'Equipment', 'Data', 'Funding', 'Partner', 'Training')),
    capability_id INTEGER REFERENCES capabilities(capability_id),
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    priority TEXT NOT NULL CHECK (priority IN ('High', 'Medium', 'Low')),
    CHECK ((category = 'Expertise' AND capability_id IS NOT NULL) OR
           (category <> 'Expertise' AND capability_id IS NULL)),
    FOREIGN KEY (researcher_id, related_project_id)
        REFERENCES researcher_projects(researcher_id, project_id)
);

CREATE TABLE researcher_outcomes (
    outcome_id INTEGER PRIMARY KEY,
    researcher_id INTEGER NOT NULL REFERENCES researchers(researcher_id),
    related_project_id INTEGER NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('Research', 'Impact', 'Development')),
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    horizon_months INTEGER NOT NULL CHECK (horizon_months > 0),
    FOREIGN KEY (researcher_id, related_project_id)
        REFERENCES researcher_projects(researcher_id, project_id)
);

CREATE TABLE project_needs (
    need_id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(project_id),
    category TEXT NOT NULL CHECK (category IN ('Expertise', 'Equipment', 'Data', 'Funding', 'Partner')),
    capability_id INTEGER REFERENCES capabilities(capability_id),
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    priority TEXT NOT NULL CHECK (priority IN ('High', 'Medium', 'Low')),
    CHECK ((category = 'Expertise' AND capability_id IS NOT NULL) OR
           (category <> 'Expertise' AND capability_id IS NULL))
);

CREATE TABLE project_outcomes (
    outcome_id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(project_id),
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    metric TEXT NOT NULL,
    target_value REAL NOT NULL CHECK (target_value > 0),
    unit TEXT NOT NULL,
    comparison_basis TEXT NOT NULL,
    horizon_months INTEGER NOT NULL CHECK (horizon_months > 0)
);

CREATE INDEX idx_topics_area ON topics(area_id);
CREATE INDEX idx_researchers_area ON researchers(primary_area_id);
CREATE INDEX idx_projects_topic ON projects(topic_id);
CREATE INDEX idx_membership_project ON researcher_projects(project_id);
CREATE INDEX idx_capabilities_match ON researcher_capabilities(capability_id, proficiency);
CREATE INDEX idx_researcher_needs_person ON researcher_needs(researcher_id);
CREATE INDEX idx_researcher_needs_capability ON researcher_needs(capability_id);
CREATE INDEX idx_researcher_outcomes_person ON researcher_outcomes(researcher_id);
CREATE INDEX idx_project_needs_project ON project_needs(project_id);
CREATE INDEX idx_project_outcomes_project ON project_outcomes(project_id);

-- Convenient flat, read-only views; the underlying tables remain normalized.
CREATE VIEW v_researcher_overview AS
SELECT r.researcher_id, r.researcher_code, r.full_name, r.role,
       a.name AS primary_area, r.summary,
       (SELECT count(*) FROM researcher_projects rp
        WHERE rp.researcher_id = r.researcher_id) AS project_count,
       (SELECT group_concat(p.project_code || ': ' || p.title, ' | ')
        FROM researcher_projects rp JOIN projects p USING (project_id)
        WHERE rp.researcher_id = r.researcher_id) AS projects,
       (SELECT group_concat(c.name, ' | ')
        FROM researcher_capabilities rc JOIN capabilities c USING (capability_id)
        WHERE rc.researcher_id = r.researcher_id) AS can_offer,
       (SELECT group_concat(n.description, ' | ')
        FROM researcher_needs n WHERE n.researcher_id = r.researcher_id) AS lacking_or_could_benefit_from,
       (SELECT group_concat(o.description, ' | ')
        FROM researcher_outcomes o WHERE o.researcher_id = r.researcher_id) AS desired_outcomes,
       r.is_synthetic
FROM researchers r JOIN research_areas a ON a.area_id = r.primary_area_id;

CREATE VIEW v_project_overview AS
SELECT p.project_id, p.project_code, p.title, a.name AS research_area,
       t.name AS topic, p.summary, p.stage,
       (SELECT count(*) FROM researcher_projects rp
        WHERE rp.project_id = p.project_id) AS researcher_count,
       (SELECT group_concat(n.description, ' | ') FROM project_needs n
        WHERE n.project_id = p.project_id) AS needs,
       (SELECT group_concat(o.description, ' | ') FROM project_outcomes o
        WHERE o.project_id = p.project_id) AS desired_outcomes,
       p.is_synthetic
FROM projects p JOIN topics t USING (topic_id)
JOIN research_areas a USING (area_id);

-- Illustrative exact-tag matches, not a validated recommendation model.
-- Excludes self-matches and people who already share any project.
CREATE VIEW v_potential_collaborators AS
SELECT n.need_id, n.researcher_id AS seeker_id, seeker.full_name AS seeker_name,
       n.related_project_id, n.description AS need, n.priority,
       c.name AS matching_capability,
       provider.researcher_id AS provider_id, provider.full_name AS provider_name,
       provider.role AS provider_role, rc.proficiency,
       seeker.primary_area_id <> provider.primary_area_id AS cross_area
FROM researcher_needs n
JOIN researchers seeker ON seeker.researcher_id = n.researcher_id
JOIN capabilities c ON c.capability_id = n.capability_id
JOIN researcher_capabilities rc ON rc.capability_id = n.capability_id
JOIN researchers provider ON provider.researcher_id = rc.researcher_id
WHERE n.category = 'Expertise' AND rc.proficiency >= 4
  AND seeker.researcher_id <> provider.researcher_id
  AND NOT EXISTS (
      SELECT 1 FROM researcher_projects sp
      JOIN researcher_projects pp ON sp.project_id = pp.project_id
      WHERE sp.researcher_id = seeker.researcher_id
        AND pp.researcher_id = provider.researcher_id
  );
