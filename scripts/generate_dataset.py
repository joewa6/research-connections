#!/usr/bin/env python3
"""Build a reproducible SQLite sandbox and nested researcher-profile exports.

Uses only the Python standard library. No real-person records are downloaded.
"""

import argparse
from collections import Counter, defaultdict
import itertools
import json
from pathlib import Path
import random
import sqlite3
import tempfile

from catalogue import AREAS, COMMON_SKILLS, FAMILY_NAMES, GIVEN_NAMES, TOPICS
from validate_dataset import validate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = 20261126
RESEARCHER_COUNT = 1000
PROJECT_COUNT = 1500


def insert_rows(db, table, rows):
    if not rows:
        return
    columns = list(rows[0])
    db.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        [[row[column] for column in columns] for row in rows],
    )


def build_projects(rng):
    projects = []
    scenarios = {}
    for tid, spec in enumerate(TOPICS, 1):
        scenarios[tid] = list(itertools.product(spec['approaches'], spec['contexts'], spec['challenges']))
        rng.shuffle(scenarios[tid])
    for aid, _, _ in AREAS:
        tids = [i for i, spec in enumerate(TOPICS, 1) if spec['area_id'] == aid]
        for index in range(PROJECT_COUNT // 4):
            tid = tids[index % len(tids)]
            spec = TOPICS[tid - 1]
            approach, context, challenge = scenarios[tid].pop()
            pid = len(projects) + 1
            projects.append(dict(
                project_id=pid, project_code=f'SYN-P{pid:04d}', topic_id=tid,
                title=f"{spec['name']}: {approach.lower()} for {context} ({challenge})",
                summary=(f"This fictional study will investigate {approach.lower()} to {spec['aim']} "
                         f"for {context}. It will compare a candidate design with a predefined internal "
                         f"control while varying conditions associated with {challenge}. "
                         "The work will record performance, resource use and failure modes before "
                         "deciding whether further development is justified."),
                approach=approach, application_context=context, technical_challenge=challenge,
                stage=rng.choices(['Concept', 'Lab study', 'Prototype', 'Pilot'], [15, 45, 30, 10])[0],
                is_synthetic=1,
            ))
    return projects


def build_people_and_memberships(rng, projects):
    names = rng.sample(sorted({f'{first} {last}' for first in GIVEN_NAMES for last in FAMILY_NAMES}), RESEARCHER_COUNT)
    roles = ['PI'] * 150 + ['Post-doc'] * 350 + ['PhD'] * 500
    rng.shuffle(roles)
    researchers, targets = [], {}
    for aid, _, _ in AREAS:
        counts = [count for count in range(1, 6) for _ in range(50)]
        rng.shuffle(counts)
        for count in counts:
            rid = len(researchers) + 1
            targets[rid] = count
            researchers.append(dict(
                researcher_id=rid, researcher_code=f'SYN-R{rid:04d}', full_name=names[rid - 1],
                role=roles[rid - 1], primary_area_id=aid, summary='', is_synthetic=1,
            ))

    person_projects, project_people = defaultdict(list), defaultdict(list)
    remaining = targets.copy()

    def assign(rid, pid):
        person_projects[rid].append(pid)
        project_people[pid].append(rid)
        remaining[rid] -= 1

    # Cover every project first; the remaining slots create shared projects.
    for project in projects:
        aid = TOPICS[project['topic_id'] - 1]['area_id']
        candidates = [r['researcher_id'] for r in researchers
                      if r['primary_area_id'] == aid and remaining[r['researcher_id']] > 0]
        rid = rng.choices(candidates, weights=[remaining[candidate] for candidate in candidates])[0]
        assign(rid, project['project_id'])

    order = researchers.copy()
    rng.shuffle(order)
    for person in order:
        rid, aid = person['researcher_id'], person['primary_area_id']
        while remaining[rid]:
            current = person_projects[rid]
            # Keep a person's first assignment in their primary area.
            cross_area = bool(current) and rng.random() < 0.22
            candidates = [p for p in projects
                          if p['project_id'] not in current and len(project_people[p['project_id']]) < 8
                          and ((TOPICS[p['topic_id'] - 1]['area_id'] != aid) if cross_area
                               else (TOPICS[p['topic_id'] - 1]['area_id'] == aid))]
            if current and not cross_area and rng.random() < 0.55:
                existing_topics = {projects[pid - 1]['topic_id'] for pid in current}
                related = [p for p in candidates if p['topic_id'] in existing_topics]
                candidates = related or candidates
            assign(rid, rng.choice(candidates)['project_id'])

    contribution_templates = {
        'PI': ["Coordinate the study design and interpret results on {challenge}.",
               "Guide the comparison protocol and assess the route to use in {context}.",
               "Define the scientific questions and connect the work to complementary projects."],
        'Post-doc': ["Develop the {approach} workflow and troubleshoot {challenge}.",
                     "Integrate characterization results and compare candidate designs for {context}.",
                     "Coordinate repeat experiments and quantify uncertainty in the performance measurements."],
        'PhD': ["Run controlled experiments on {challenge} and curate the measurement records.",
                "Prepare and test candidate designs using {approach}.",
                "Build a reproducible analysis of performance and failure modes for {context}."],
    }
    memberships = []
    for person in researchers:
        rid = person['researcher_id']
        assigned = [projects[pid - 1] for pid in sorted(person_projects[rid])]
        primary_topics = list(dict.fromkeys(
            TOPICS[p['topic_id'] - 1]['name'].lower() for p in assigned
            if TOPICS[p['topic_id'] - 1]['area_id'] == person['primary_area_id']))
        anchor = next(p for p in assigned if TOPICS[p['topic_id'] - 1]['area_id'] == person['primary_area_id'])
        focus = ' and '.join(primary_topics[:2])
        role_description = {'PI': 'A principal investigator', 'Post-doc': 'A postdoctoral researcher', 'PhD': 'A doctoral researcher'}[person['role']]
        other_areas = sorted({TOPICS[p['topic_id'] - 1]['area_id'] for p in assigned} - {person['primary_area_id']})
        cross_text = (' Their projects also connect to ' + ', '.join(AREAS[aid - 1][1].lower() for aid in other_areas) + '.') if other_areas else ''
        person['summary'] = (f"{role_description} working on {focus}. Their current work examines "
                             f"{anchor['technical_challenge']} in {anchor['application_context']}, "
                             f"with an emphasis on reproducible comparisons and practical resource use.{cross_text}")
        for project in assigned:
            memberships.append(dict(
                researcher_id=rid, project_id=project['project_id'],
                contribution=rng.choice(contribution_templates[person['role']]).format(
                    approach=project['approach'].lower(), challenge=project['technical_challenge'],
                    context=project['application_context']),
            ))
    return researchers, memberships, person_projects


def build_project_details(rng, projects, skill_ids):
    needs, outcomes = [], []
    for project in projects:
        pid = project['project_id']
        spec = TOPICS[project['topic_id'] - 1]
        skills = rng.sample(spec['skills'], rng.randint(1, 2))
        if rng.random() < 0.35:
            skills.append(rng.choice(COMMON_SKILLS))
        for skill in dict.fromkeys(skills):
            needs.append(dict(
                need_id=len(needs) + 1, project_id=pid, category='Expertise', capability_id=skill_ids[skill],
                description=(f"Additional support in {skill.lower()} to test assumptions about "
                             f"{project['technical_challenge']} and interpret the comparison with the internal control."),
                priority=rng.choice(['High', 'High', 'Medium']),
            ))
        needs.append(dict(
            need_id=len(needs) + 1, project_id=pid, category='Equipment', capability_id=None,
            description=f"Scheduled access to {spec['equipment']} for repeat measurements and control runs.",
            priority=rng.choice(['High', 'Medium']),
        ))
        resource_category = rng.choice(['Data', 'Funding', 'Partner'])
        resource_text = {
            'Data': f"A documented dataset describing representative operating conditions in {project['application_context']}.",
            'Funding': f"A small development budget for consumables, repeat trials and independent checking of the {project['approach'].lower()} workflow.",
            'Partner': f"An application partner familiar with {project['application_context']} to review practical constraints and future validation needs.",
        }
        needs.append(dict(need_id=len(needs) + 1, project_id=pid, category=resource_category,
                          capability_id=None, description=resource_text[resource_category], priority=rng.choice(['High', 'Medium', 'Low'])))
        target = rng.choice([10, 12, 15, 18, 20, 25, 30])
        article = 'an' if target == 18 else 'a'
        horizon = {'Concept': 24, 'Lab study': 18, 'Prototype': 12, 'Pilot': 9}[project['stage']]
        outcomes.append(dict(
            outcome_id=len(outcomes) + 1, project_id=pid,
            description=f"Demonstrate {article} {target}% {spec['metric'].lower()} relative to the study's predefined internal control.",
            metric=spec['metric'], target_value=target, unit='percent',
            comparison_basis='Relative change from a predefined nonzero internal control under matched conditions; fictional target, not an observed result.',
            horizon_months=horizon,
        ))
        replicates = rng.choice([3, 4, 5, 6])
        outcomes.append(dict(
            outcome_id=len(outcomes) + 1, project_id=pid,
            description=f"Complete {replicates} independent validation runs and release a documented protocol with uncertainty estimates.",
            metric='Independent validation runs completed', target_value=replicates, unit='runs',
            comparison_basis='Absolute number of planned independent runs, each including candidate and control measurements.',
            horizon_months=horizon,
        ))
    return needs, outcomes


def build_person_details(rng, people, projects, person_projects, skill_ids, project_outcomes):
    offers, needs, outcomes = [], [], []
    first_project_outcome = {o['project_id']: o for o in reversed(project_outcomes)}
    for person in people:
        rid = person['researcher_id']
        assigned = [projects[pid - 1] for pid in sorted(person_projects[rid])]
        topic_skills = sorted({skill for p in assigned for skill in TOPICS[p['topic_id'] - 1]['skills']})
        pool = sorted(set(topic_skills + COMMON_SKILLS))
        # Always retain complementary expertise for at least one explicit gap.
        offered = rng.sample(pool, min(rng.randint(3, 6), len(pool) - 2))
        if not set(offered).intersection(topic_skills):
            offered[0] = rng.choice(topic_skills)
        for skill in sorted(offered):
            level_weights = {'PI': [1, 5, 4], 'Post-doc': [2, 6, 2], 'PhD': [6, 3, 1]}[person['role']]
            proficiency = rng.choices([3, 4, 5], level_weights)[0]
            verb = 'contribute practical work in' if proficiency == 3 else 'offer specialist support in'
            offers.append(dict(researcher_id=rid, capability_id=skill_ids[skill], proficiency=proficiency,
                               offer_description=f"I can {verb} {skill.lower()}, including protocol review and interpretation of results."))

        # One or two expertise gaps, each attached to an actual project membership.
        missing_used = set()
        for project in rng.sample(assigned, min(len(assigned), rng.randint(1, 2))):
            spec = TOPICS[project['topic_id'] - 1]
            missing = sorted(set(spec['skills'] + COMMON_SKILLS) - set(offered) - missing_used)
            skill = rng.choice(missing)
            missing_used.add(skill)
            wording = rng.choice([
                "I lack hands-on depth in {skill} and would benefit from a collaborator to help interpret {challenge}.",
                "I could benefit from specialist input in {skill} before deciding which design to develop for {context}.",
                "I need complementary expertise in {skill} to make the comparison protocol more convincing for {context}.",
            ])
            needs.append(dict(
                need_id=len(needs) + 1, researcher_id=rid, related_project_id=project['project_id'],
                category='Expertise', capability_id=skill_ids[skill],
                description=wording.format(skill=skill.lower(), challenge=project['technical_challenge'], context=project['application_context']),
                priority=rng.choice(['High', 'High', 'Medium']),
            ))
        project = rng.choice(assigned)
        spec = TOPICS[project['topic_id'] - 1]
        resource_categories = rng.sample(['Equipment', 'Data', 'Funding', 'Partner', 'Training'], rng.randint(1, 2))
        resource_text = {
            'Equipment': f"I need reliable booking time on {spec['equipment']} so that I can finish repeat measurements.",
            'Data': f"I am missing representative operating data from {project['application_context']}; annotated measurements would help me test generalizability.",
            'Funding': f"I need a modest consumables and validation budget to compare alternatives for {project['technical_challenge']}.",
            'Partner': f"I would benefit from an application partner working with {project['application_context']} who can explain deployment constraints.",
            'Training': f"I would benefit from focused training in uncertainty estimation and reproducible reporting for the {project['approach'].lower()} study.",
        }
        for category in resource_categories:
            needs.append(dict(need_id=len(needs) + 1, researcher_id=rid, related_project_id=project['project_id'],
                              category=category, capability_id=None, description=resource_text[category],
                              priority=rng.choice(['High', 'Medium', 'Medium', 'Low'])))

        project = rng.choice(assigned)
        target = first_project_outcome[project['project_id']]
        outcomes.append(dict(
            outcome_id=len(outcomes) + 1, researcher_id=rid, related_project_id=project['project_id'], category='Research',
            description=f"I want to {target['description'][0].lower() + target['description'][1:]}",
            horizon_months=target['horizon_months'],
        ))
        development = {
            'PI': ["I want to assemble a complementary team and write a follow-on research proposal grounded in the validation results.",
                   "I want to establish a reusable comparison protocol that junior researchers can apply across related projects.",
                   "I want to build an application partnership that can test whether the lab findings remain useful under realistic constraints."],
            'Post-doc': ["I want to publish a reproducible methods study and develop an independent research direction from the results.",
                         "I want to lead a cross-area experiment and share a reusable analysis workflow with the team.",
                         "I want to turn the method into a validated protocol and use it as the basis of an independent funding application."],
            'PhD': ["I want to complete a thesis chapter supported by repeatable measurements and a clearly documented dataset.",
                    "I want to gain independence in experimental design and produce a reusable analysis notebook for this study.",
                    "I want to present the results at a research meeting and prepare a manuscript with a transparent methods section."],
        }
        outcomes.append(dict(outcome_id=len(outcomes) + 1, researcher_id=rid, related_project_id=project['project_id'],
                             category='Development', description=rng.choice(development[person['role']]), horizon_months=rng.choice([12, 18, 24])))
        if rng.random() < 0.45:
            outcomes.append(dict(
                outcome_id=len(outcomes) + 1, researcher_id=rid, related_project_id=project['project_id'], category='Impact',
                description=f"I want to document the resource-use trade-offs and practical limitations of {project['approach'].lower()} for {project['application_context']}.",
                horizon_months=rng.choice([18, 24, 30]),
            ))
    return offers, needs, outcomes


def export_profiles(db, destination):
    db.row_factory = sqlite3.Row
    projects = {}
    for row in db.execute('SELECT p.*, t.name AS topic, a.name AS research_area FROM projects p JOIN topics t USING(topic_id) JOIN research_areas a USING(area_id) ORDER BY project_id'):
        project = dict(row)
        pid = project['project_id']
        project['needs'] = [dict(n) for n in db.execute('SELECT n.*, c.name AS capability FROM project_needs n LEFT JOIN capabilities c USING(capability_id) WHERE project_id=? ORDER BY need_id', (pid,))]
        project['desired_outcomes'] = [dict(o) for o in db.execute('SELECT * FROM project_outcomes WHERE project_id=? ORDER BY outcome_id', (pid,))]
        projects[pid] = project
    sample, sample_roles = [], Counter()
    with (destination / 'researcher_profiles.jsonl').open('w', encoding='utf-8') as handle:
        for row in db.execute('SELECT r.*, a.name AS primary_area FROM researchers r JOIN research_areas a ON a.area_id=r.primary_area_id ORDER BY researcher_id'):
            person = dict(row)
            rid = person['researcher_id']
            person['can_offer'] = [dict(o) for o in db.execute('SELECT c.name AS capability, rc.proficiency, rc.offer_description FROM researcher_capabilities rc JOIN capabilities c USING(capability_id) WHERE researcher_id=? ORDER BY c.name', (rid,))]
            person['lacking_or_could_benefit_from'] = [dict(n) for n in db.execute('SELECT n.*, c.name AS capability FROM researcher_needs n LEFT JOIN capabilities c USING(capability_id) WHERE researcher_id=? ORDER BY need_id', (rid,))]
            person['desired_outcomes'] = [dict(o) for o in db.execute('SELECT * FROM researcher_outcomes WHERE researcher_id=? ORDER BY outcome_id', (rid,))]
            person['projects'] = [dict(projects[m['project_id']], personal_contribution=m['contribution']) for m in db.execute('SELECT * FROM researcher_projects WHERE researcher_id=? ORDER BY project_id', (rid,))]
            handle.write(json.dumps(person, ensure_ascii=False) + '\n')
            key = (person['primary_area_id'], person['role'])
            if sample_roles[key] == 0:
                sample.append(person)
                sample_roles[key] += 1
    (destination / 'sample_profiles.json').write_text(json.dumps({
        'notice': 'Entirely fictional. One example of each role in each area. Targets are aspirations, not measured results.',
        'researchers': sample,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = [
        'SYNTHETIC SUSTECH RESEARCHER PROFILES',
        '12 examples: one PI, post-doc and PhD researcher from each area.',
        'All people, projects and statements are fictional. Numerical outcomes are future targets.',
        '',
    ]
    for person in sample:
        lines.extend([
            '=' * 80,
            f"{person['researcher_code']} | {person['full_name']} | {person['role']}",
            f"Primary area: {person['primary_area']}", '', person['summary'], '',
            'CAN OFFER',
        ])
        lines.extend(f"- {offer['capability']} (proficiency {offer['proficiency']}/5)" for offer in person['can_offer'])
        lines.extend(['', 'PROJECTS'])
        for project in person['projects']:
            lines.extend([
                f"- {project['project_code']}: {project['title']}",
                f"  Area: {project['research_area']} | Stage: {project['stage']}",
                f"  Summary: {project['summary']}",
                f"  Personal contribution: {project['personal_contribution']}",
            ])
        lines.extend(['', 'LACKING OR COULD BENEFIT FROM'])
        for need in person['lacking_or_could_benefit_from']:
            lines.append(f"- [{need['priority']}; {need['category']}; SYN-P{need['related_project_id']:04d}] {need['description']}")
        lines.extend(['', 'DESIRED OUTCOMES'])
        for outcome in person['desired_outcomes']:
            lines.append(f"- [{outcome['category']}; {outcome['horizon_months']} months; SYN-P{outcome['related_project_id']:04d}] {outcome['description']}")
        lines.append('')
    (destination / 'sample_profiles.txt').write_text('\n'.join(lines), encoding='utf-8')


def generate(destination, seed, force):
    destination.mkdir(parents=True, exist_ok=True)
    artifact_names = ['sustech_synthetic.sqlite', 'researcher_profiles.jsonl', 'sample_profiles.json', 'sample_profiles.txt', 'validation_report.json']
    existing = [str(destination / name) for name in artifact_names if (destination / name).exists()]
    if existing and not force:
        raise SystemExit('Refusing to overwrite existing dataset files. Use --force or --output with a new directory:\n' + '\n'.join(existing))
    rng = random.Random(seed)
    skill_names = sorted(set(COMMON_SKILLS).union(*(spec['skills'] for spec in TOPICS)))
    skill_ids = {name: index for index, name in enumerate(skill_names, 1)}
    projects = build_projects(rng)
    people, memberships, person_projects = build_people_and_memberships(rng, projects)
    project_needs, project_outcomes = build_project_details(rng, projects, skill_ids)
    offers, person_needs, person_outcomes = build_person_details(rng, people, projects, person_projects, skill_ids, project_outcomes)
    with tempfile.TemporaryDirectory(prefix='.sustech-build-', dir=destination) as temporary:
        staged = Path(temporary)
        db_path = staged / artifact_names[0]
        with sqlite3.connect(db_path) as db:
            db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
            metadata = {
                'dataset_name': 'Synthetic SUSTech collaboration sandbox', 'schema_version': '1.0',
                'seed': str(seed), 'scenario_date': '2026-11-26',
                'synthetic_notice': 'All people, projects, needs, capabilities and outcomes are invented. No actual affiliation, competence, or opinion is asserted.',
                'scope': '1000 fictional researchers; 1500 unique projects; 3000 memberships; 1-5 projects per person.',
                'source_context': 'User-provided research themes and https://sustech.iit.it/research (area names only; accessed 2026-11-26).',
                'generation_method': 'Seeded, hand-authored scenario combinations and rule-based relational assignment; not representative of IIT.',
                'outcomes_notice': 'All numerical values are hypothetical future targets, never experimental results or performance claims.',
                'proficiency_scale': '1 introductory; 2 assisted; 3 independent practitioner; 4 advanced; 5 specialist. Generated offers use 3-5.',
                'assignment_rule': 'Exactly 200 people at each project count 1-5; each area has 250 people and 375 projects; project teams contain 1-8 people.',
            }
            insert_rows(db, 'metadata', [dict(key=k, value=v) for k, v in metadata.items()])
            insert_rows(db, 'research_areas', [dict(area_id=aid, name=name, description=description) for aid, name, description in AREAS])
            insert_rows(db, 'topics', [dict(topic_id=tid, area_id=spec['area_id'], name=spec['name']) for tid, spec in enumerate(TOPICS, 1)])
            insert_rows(db, 'capabilities', [dict(capability_id=cid, name=name, description=f'Research support in {name.lower()}.') for name, cid in skill_ids.items()])
            insert_rows(db, 'researchers', people)
            insert_rows(db, 'projects', projects)
            insert_rows(db, 'researcher_projects', memberships)
            insert_rows(db, 'researcher_capabilities', offers)
            insert_rows(db, 'researcher_needs', person_needs)
            insert_rows(db, 'researcher_outcomes', person_outcomes)
            insert_rows(db, 'project_needs', project_needs)
            insert_rows(db, 'project_outcomes', project_outcomes)
            db.commit()
            export_profiles(db, staged)
        db.close()
        report = validate(db_path, staged / 'researcher_profiles.jsonl', staged / 'sample_profiles.json')
        (staged / 'validation_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        if not report['passed']:
            raise RuntimeError(json.dumps(report, indent=2))
        for name in artifact_names:
            (staged / name).replace(destination / name)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f'Wrote dataset to {destination.resolve()}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
    parser.add_argument('--output', type=Path, default=ROOT / 'data')
    parser.add_argument('--force', action='store_true', help='Replace the five generated dataset files.')
    args = parser.parse_args()
    generate(args.output.resolve(), args.seed, args.force)
