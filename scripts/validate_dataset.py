#!/usr/bin/env python3
"""Check the user's data requirements, relational integrity, and nested exports."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3


def validate(db_path, profiles_path=None, sample_path=None):
    db = sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    checks = {}

    def scalar(sql):
        return db.execute(sql).fetchone()[0]

    counts = {row[0]: scalar(f'SELECT count(*) FROM {row[0]}')
              for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
    checks['sqlite_integrity'] = scalar('PRAGMA integrity_check') == 'ok'
    checks['foreign_keys'] = not list(db.execute('PRAGMA foreign_key_check'))
    checks['exactly_1000_researchers'] = counts['researchers'] == 1000
    checks['exactly_1500_projects'] = counts['projects'] == 1500
    checks['exactly_3000_memberships'] = counts['researcher_projects'] == 3000
    checks['four_areas_and_32_topics'] = counts['research_areas'] == 4 and counts['topics'] == 32
    distribution = dict(db.execute('SELECT n, count(*) FROM (SELECT r.researcher_id, count(rp.project_id) AS n FROM researchers r LEFT JOIN researcher_projects rp USING(researcher_id) GROUP BY r.researcher_id) GROUP BY n'))
    checks['one_to_five_distinct_projects_per_person'] = distribution == {1: 200, 2: 200, 3: 200, 4: 200, 5: 200}
    roles = dict(db.execute('SELECT role, count(*) FROM researchers GROUP BY role'))
    checks['role_distribution'] = roles == {'PI': 150, 'Post-doc': 350, 'PhD': 500}
    checks['all_people_and_projects_marked_synthetic'] = scalar('SELECT count(*) FROM researchers WHERE is_synthetic<>1') == 0 and scalar('SELECT count(*) FROM projects WHERE is_synthetic<>1') == 0
    checks['every_project_has_1_to_8_members'] = scalar('SELECT count(*) FROM (SELECT p.project_id, count(rp.researcher_id) AS n FROM projects p LEFT JOIN researcher_projects rp USING(project_id) GROUP BY p.project_id HAVING n NOT BETWEEN 1 AND 8)') == 0
    checks['every_topic_has_projects'] = scalar('SELECT count(*) FROM topics t WHERE NOT EXISTS (SELECT 1 FROM projects p WHERE p.topic_id=t.topic_id)') == 0
    checks['every_person_has_project_in_primary_area'] = scalar('SELECT count(*) FROM researchers r WHERE NOT EXISTS (SELECT 1 FROM researcher_projects rp JOIN projects p USING(project_id) JOIN topics t USING(topic_id) WHERE rp.researcher_id=r.researcher_id AND t.area_id=r.primary_area_id)') == 0
    checks['expertise_gaps_not_already_offered_by_same_person'] = scalar('SELECT count(*) FROM researcher_needs n JOIN researcher_capabilities rc ON n.researcher_id=rc.researcher_id AND n.capability_id=rc.capability_id') == 0
    for table, owner_table, owner_column, lower, upper in [
        ('researcher_needs', 'researchers', 'researcher_id', 2, 4),
        ('researcher_outcomes', 'researchers', 'researcher_id', 2, 3),
        ('researcher_capabilities', 'researchers', 'researcher_id', 3, 6),
        ('project_needs', 'projects', 'project_id', 3, 5),
        ('project_outcomes', 'projects', 'project_id', 2, 2),
    ]:
        checks[f'{table}_complete'] = scalar(f'SELECT count(*) FROM {owner_table} o WHERE (SELECT count(*) FROM {table} d WHERE d.{owner_column}=o.{owner_column}) NOT BETWEEN {lower} AND {upper}') == 0
    for table, column in [('researchers', 'summary'), ('projects', 'summary'),
                          ('researcher_needs', 'description'), ('researcher_outcomes', 'description'),
                          ('project_needs', 'description'), ('project_outcomes', 'description'),
                          ('researcher_projects', 'contribution')]:
        checks[f'{table}_{column}_nonempty'] = scalar(f"SELECT count(*) FROM {table} WHERE {column} IS NULL OR length(trim({column}))=0") == 0

    areas = [dict(row) for row in db.execute('SELECT a.name, (SELECT count(*) FROM researchers r WHERE r.primary_area_id=a.area_id) AS researchers, (SELECT count(*) FROM projects p JOIN topics t USING(topic_id) WHERE t.area_id=a.area_id) AS projects FROM research_areas a ORDER BY a.area_id')]
    checks['balanced_areas'] = all(a['researchers'] == 250 and a['projects'] == 375 for a in areas)
    checks['overview_views_complete'] = scalar('SELECT count(*) FROM v_researcher_overview') == 1000 and scalar('SELECT count(*) FROM v_project_overview') == 1500
    matches = list(db.execute('SELECT * FROM v_potential_collaborators WHERE cross_area=1 LIMIT 5'))
    checks['cross_area_matching_examples_exist'] = len(matches) == 5

    export_count = None
    if profiles_path is not None:
        seen, export_errors = set(), []
        for line_number, line in enumerate(Path(profiles_path).read_text(encoding='utf-8').splitlines(), 1):
            person = json.loads(line)
            rid = person['researcher_id']
            if rid in seen:
                export_errors.append(f'duplicate researcher {rid}')
            seen.add(rid)
            expected = db.execute('SELECT * FROM researchers WHERE researcher_id=?', (rid,)).fetchone()
            if not expected or any(person.get(k) != expected[k] for k in expected.keys()):
                export_errors.append(f'person record differs on line {line_number}')
                continue
            expected_memberships = dict(db.execute('SELECT project_id, contribution FROM researcher_projects WHERE researcher_id=?', (rid,)))
            actual_projects = person['projects']
            if len(actual_projects) != len(expected_memberships) or {p['project_id'] for p in actual_projects} != set(expected_memberships):
                export_errors.append(f'membership mismatch for {rid}')
            for project in actual_projects:
                pid = project['project_id']
                expected_project = db.execute('SELECT * FROM projects WHERE project_id=?', (pid,)).fetchone()
                if not expected_project or any(project.get(k) != expected_project[k] for k in expected_project.keys()) or project['personal_contribution'] != expected_memberships.get(pid):
                    export_errors.append(f'project mismatch for {rid}/{pid}')
                for field, table, order_column in [('needs', 'project_needs', 'need_id'), ('desired_outcomes', 'project_outcomes', 'outcome_id')]:
                    expected_rows = [dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE project_id=? ORDER BY {order_column}', (pid,))]
                    actual_rows = project[field]
                    if len(actual_rows) != len(expected_rows) or any(any(actual.get(k) != expected[k] for k in expected) for actual, expected in zip(actual_rows, expected_rows)):
                        export_errors.append(f'{table} mismatch for {rid}/{pid}')
            for field, table, order_column in [('lacking_or_could_benefit_from', 'researcher_needs', 'need_id'), ('desired_outcomes', 'researcher_outcomes', 'outcome_id')]:
                expected_rows = [dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE researcher_id=? ORDER BY {order_column}', (rid,))]
                actual_rows = person[field]
                if len(actual_rows) != len(expected_rows) or any(any(actual.get(k) != expected[k] for k in expected) for actual, expected in zip(actual_rows, expected_rows)):
                    export_errors.append(f'{table} mismatch for {rid}')
            expected_offers = [dict(r) for r in db.execute('SELECT c.name AS capability, rc.proficiency, rc.offer_description FROM researcher_capabilities rc JOIN capabilities c USING(capability_id) WHERE researcher_id=? ORDER BY c.name', (rid,))]
            if person['can_offer'] != expected_offers:
                export_errors.append(f'capability mismatch for {rid}')
        export_count = len(seen)
        checks['all_1000_profiles_exported_exactly_once'] = seen == set(range(1, 1001)) and not any('duplicate' in e for e in export_errors)
        checks['nested_export_matches_database'] = not export_errors
    else:
        export_errors = []

    if sample_path is not None:
        sample = json.loads(Path(sample_path).read_text(encoding='utf-8'))['researchers']
        combinations = Counter((p['primary_area_id'], p['role']) for p in sample)
        checks['sample_covers_every_role_and_area'] = len(sample) == 12 and combinations == Counter({(aid, role): 1 for aid in range(1, 5) for role in roles})

    report = {
        'passed': all(checks.values()), 'checks': checks, 'table_counts': counts,
        'role_distribution': roles, 'projects_per_researcher_distribution': distribution,
        'areas': areas,
        'shared_projects': scalar('SELECT count(*) FROM (SELECT project_id FROM researcher_projects GROUP BY project_id HAVING count(*)>1)'),
        'researchers_with_cross_area_projects': scalar('SELECT count(DISTINCT rp.researcher_id) FROM researcher_projects rp JOIN researchers r USING(researcher_id) JOIN projects p USING(project_id) JOIN topics t USING(topic_id) WHERE r.primary_area_id<>t.area_id'),
        'projects_with_cross_area_teams': scalar('SELECT count(*) FROM (SELECT rp.project_id FROM researcher_projects rp JOIN researchers r USING(researcher_id) GROUP BY rp.project_id HAVING count(DISTINCT r.primary_area_id)>1)'),
        'exported_researcher_profiles': export_count,
        'export_errors': export_errors[:20],
        'notice': 'Checks confirm structural consistency, not scientific feasibility or representativeness. Every record is fictional.',
    }
    db.close()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--profiles', type=Path)
    parser.add_argument('--sample', type=Path)
    args = parser.parse_args()
    result = validate(args.database, args.profiles, args.sample)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)
