-- Run: sqlite3 -header -column data/sustech_synthetic.sqlite < example_queries.sql

-- 1. People by area and role.
SELECT a.name AS area, r.role, count(*) AS researchers
FROM researchers r JOIN research_areas a ON a.area_id = r.primary_area_id
GROUP BY a.area_id, r.role ORDER BY a.area_id, r.role;

-- 2. Confirm that each person has between one and five distinct projects.
SELECT project_count, count(*) AS researchers
FROM v_researcher_overview GROUP BY project_count ORDER BY project_count;

-- 3. Inspect one person's projects and contribution. Change the ID to explore.
SELECT r.full_name, r.role, p.project_code, p.title, p.summary, rp.contribution
FROM researchers r JOIN researcher_projects rp USING (researcher_id)
JOIN projects p USING (project_id)
WHERE r.researcher_id = 1 ORDER BY p.project_id;

-- 4. The same person's gaps, with the relevant project for context.
SELECT n.category, c.name AS missing_expertise, n.priority,
       p.project_code, n.description
FROM researcher_needs n JOIN projects p ON p.project_id = n.related_project_id
LEFT JOIN capabilities c USING (capability_id)
WHERE n.researcher_id = 1 ORDER BY n.need_id;

-- 5. The same person's desired outcomes, including career development.
SELECT o.category, p.project_code, o.description, o.horizon_months
FROM researcher_outcomes o JOIN projects p ON p.project_id = o.related_project_id
WHERE o.researcher_id = 1 ORDER BY o.outcome_id;

-- 6. The most frequently requested expertise across people.
-- Counts unique people, not repeated needs from the same person.
SELECT c.name, count(DISTINCT n.researcher_id) AS people_requesting_support
FROM researcher_needs n JOIN capabilities c USING (capability_id)
GROUP BY c.capability_id ORDER BY people_requesting_support DESC, c.name LIMIT 12;

-- 7. Potential new collaborators across areas, based on exact expertise tags.
-- A baseline demonstration: actual availability and suitability are not modelled.
SELECT seeker_name, matching_capability, provider_name, provider_role, proficiency
FROM v_potential_collaborators
WHERE seeker_id = 1 AND cross_area = 1
ORDER BY CASE priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
         proficiency DESC, provider_id LIMIT 10;

-- 8. Shared projects that connect researchers from different primary areas.
SELECT p.project_code, p.title, count(DISTINCT r.researcher_id) AS people,
       count(DISTINCT r.primary_area_id) AS connected_areas
FROM projects p JOIN researcher_projects rp USING (project_id)
JOIN researchers r USING (researcher_id)
GROUP BY p.project_id HAVING connected_areas > 1
ORDER BY connected_areas DESC, people DESC, p.project_id LIMIT 10;

-- 9. Expertise demand compared with the number of advanced/specialist offers.
-- Correlated counts avoid multiplying rows by joining both many-to-many tables.
SELECT c.name,
       (SELECT count(DISTINCT n.researcher_id) FROM researcher_needs n
        WHERE n.capability_id = c.capability_id) AS people_needing_support,
       (SELECT count(*) FROM researcher_capabilities rc
        WHERE rc.capability_id = c.capability_id AND rc.proficiency >= 4) AS potential_providers
FROM capabilities c ORDER BY people_needing_support DESC, c.name LIMIT 15;
