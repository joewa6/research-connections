#!/usr/bin/env python3
"""A local search interface for the synthetic SUSTech SQLite database."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import sqlite3
import time
import webbrowser
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / 'data' / 'sustech_synthetic.sqlite'
STATIC = Path(__file__).resolve().parent / 'static'
PAGE_SIZE = 15


def connect():
    connection = sqlite3.connect(DATABASE.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    deadline = time.monotonic() + 8
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    return connection


def rows(connection, sql, parameters=()):
    return [dict(row) for row in connection.execute(sql, parameters)]


def parse_search(query):
    """Return OR groups of AND terms. Double quotes keep a phrase together."""
    query = query.strip().replace('“', '"').replace('”', '"')
    if len(query) > 200:
        raise ValueError('Keep your search under 200 characters.')
    if not query:
        return []
    if query.count('"') % 2:
        raise ValueError('Add a closing quote to finish the phrase.')
    tokens = re.findall(r'"([^"]*)"|([^\s"]+)', query)
    groups, group, expect_term = [], [], True
    for phrase, word in tokens:
        operator = word.upper() if word else None
        if operator in ('OR', 'AND'):
            if expect_term:
                raise ValueError(f'Add a word or phrase before {operator}.')
            if operator == 'OR':
                groups.append(group)
                group = []
            expect_term = True
        else:
            term = ' '.join((phrase or word).split())
            if not term:
                raise ValueError('Add some text inside the quotes.')
            group.append(term)
            expect_term = False
    if expect_term:
        raise ValueError('Add a word or phrase after OR or AND.')
    groups.append(group)
    if sum(map(len, groups)) > 12:
        raise ValueError('Use at most 12 search words or phrases.')
    return groups


def like_pattern(term):
    return '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


# Each document retains its source so results can explain a match.
# Matching documents are grouped by owner, so people are never duplicated.
PERSON_DOCUMENTS = """
    SELECT researcher_id AS owner_id, 'name' AS field, researcher_id AS source_id,
           full_name AS text, 0 AS importance FROM researchers
    UNION ALL
    SELECT researcher_id, 'research', researcher_id, summary, 1 FROM researchers
    UNION ALL
    SELECT rc.researcher_id, 'expertise', rc.capability_id,
           c.name || '. ' || rc.offer_description, 2
      FROM researcher_capabilities rc JOIN capabilities c USING(capability_id)
    UNION ALL
    SELECT researcher_id, 'needs', related_project_id, description, 4 FROM researcher_needs
    UNION ALL
    SELECT researcher_id, 'outcomes', related_project_id, description, 5 FROM researcher_outcomes
    UNION ALL
    SELECT rp.researcher_id, 'project', p.project_id,
           p.title || '. ' || p.summary, 3
      FROM researcher_projects rp JOIN projects p USING(project_id)
    UNION ALL
    SELECT rp.researcher_id, 'project_needs', n.project_id, n.description, 6
      FROM researcher_projects rp JOIN project_needs n USING(project_id)
    UNION ALL
    SELECT rp.researcher_id, 'project_outcomes', o.project_id, o.description, 7
      FROM researcher_projects rp JOIN project_outcomes o USING(project_id)
"""

PROJECT_DOCUMENTS = """
    SELECT project_id AS owner_id, 'name' AS field, project_id AS source_id,
           title AS text, 0 AS importance FROM projects
    UNION ALL
    SELECT project_id, 'research', project_id, summary, 1 FROM projects
    UNION ALL
    SELECT n.project_id, 'expertise', n.project_id,
           c.name || '. ' || n.description, 2
      FROM project_needs n JOIN capabilities c USING(capability_id)
    UNION ALL
    SELECT project_id, 'needs', project_id, description, 3 FROM project_needs
    UNION ALL
    SELECT project_id, 'outcomes', project_id, description, 4 FROM project_outcomes
"""

SCOPES = {
    'all': None,
    'research': ('research', 'project'),
    'expertise': ('expertise',),
    'needs': ('needs', 'project_needs'),
    'outcomes': ('outcomes', 'project_outcomes'),
}


def overview():
    connection = connect()
    try:
        return {
            'counts': {table: connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                       for table in ['researchers', 'projects', 'researcher_projects']},
            'areas': rows(connection, 'SELECT * FROM research_areas ORDER BY area_id'),
            'roles': ['PI', 'Post-doc', 'PhD'],
        }
    finally:
        connection.close()


def search(kind, parameters):
    if kind not in ('researchers', 'projects'):
        raise ValueError('Choose people or projects.')
    query = parameters.get('q', [''])[0].strip()
    groups = parse_search(query)
    scope = parameters.get('scope', ['all'])[0]
    if scope not in SCOPES:
        raise ValueError('Choose a valid search field.')
    area = parameters.get('area', [''])[0]
    if area and area not in {'1', '2', '3', '4'}:
        raise ValueError('Choose a valid research area.')
    role = parameters.get('role', [''])[0]
    if role and role not in ('PI', 'Post-doc', 'PhD'):
        raise ValueError('Choose a valid researcher role.')
    offset = max(0, min(int(parameters.get('offset', ['0'])[0]), 100000))
    people = kind == 'researchers'
    connection = connect()
    try:
        table = 'researchers r JOIN research_areas a ON a.area_id=r.primary_area_id' if people else 'projects p JOIN topics t USING(topic_id) JOIN research_areas a USING(area_id)'
        identifier = 'r.researcher_id' if people else 'p.project_id'
        columns = ('r.researcher_id, r.researcher_code, r.full_name, r.role, r.summary, a.name AS research_area, '
                   '(SELECT count(*) FROM researcher_projects rp WHERE rp.researcher_id=r.researcher_id) AS project_count') if people else (
                       'p.project_id, p.project_code, p.title, p.summary, p.stage, t.name AS topic, a.name AS research_area, '
                       '(SELECT count(*) FROM researcher_projects rp WHERE rp.project_id=p.project_id) AS researcher_count')
        predicates, filters = [], []
        if area:
            predicates.append('a.area_id=?')
            filters.append(int(area))
        if people and role:
            predicates.append('r.role=?')
            filters.append(role)
        where = ' WHERE ' + ' AND '.join(predicates) if predicates else ''
        terms = list(dict.fromkeys(term for group in groups for term in group))
        cte, values, match_join = '', [], ''
        order = 'r.full_name, r.researcher_id' if people else 'p.title, p.project_id'
        if groups:
            documents = PERSON_DOCUMENTS if people else PROJECT_DOCUMENTS
            source_scope = ''
            scope_values = list(SCOPES[scope] or [])
            if not people and scope == 'research':
                scope_values.append('name')
            if scope_values:
                source_scope = ' WHERE field IN (' + ','.join('?' for _ in scope_values) + ')'
            cases = ', '.join(f"MAX(CASE WHEN text LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END) AS term_{i}" for i in range(len(terms)))
            any_term = ' OR '.join("text LIKE ? ESCAPE '\\'" for _ in terms)
            groups_sql = ' OR '.join('(' + ' AND '.join(f'term_{terms.index(term)}=1' for term in group) + ')' for group in groups)
            cte = f'''WITH documents AS ({documents}),
                scoped AS (SELECT * FROM documents{source_scope}),
                hits AS (SELECT owner_id, {cases}, MIN(importance) AS relevance
                         FROM scoped WHERE {any_term} GROUP BY owner_id
                         HAVING {groups_sql}) '''
            patterns = [like_pattern(term) for term in terms]
            values = scope_values + patterns + patterns
            match_join = f' JOIN hits ON hits.owner_id={identifier}'
            order = 'hits.relevance, ' + order
        total = connection.execute(cte + f'SELECT count(*) FROM {table}{match_join}{where}', values + filters).fetchone()[0]
        if total and offset >= total:
            offset = ((total - 1) // PAGE_SIZE) * PAGE_SIZE
        result = rows(connection, cte + f'SELECT {columns} FROM {table}{match_join}{where} ORDER BY {order} LIMIT ? OFFSET ?', values + filters + [PAGE_SIZE, offset])
        if groups and result:
            owner_key = 'researcher_id' if people else 'project_id'
            ids = [item[owner_key] for item in result]
            placeholders = ','.join('?' for _ in ids)
            excerpts = rows(connection, f'''WITH documents AS ({documents})
                SELECT * FROM documents WHERE owner_id IN ({placeholders})
                {' AND field IN (' + ','.join('?' for _ in scope_values) + ')' if scope_values else ''}
                AND ({any_term}) ORDER BY importance, source_id, text''', ids + scope_values + patterns)
            first_match = {}
            for excerpt in excerpts:
                first_match.setdefault(excerpt['owner_id'], excerpt)
            for item in result:
                item['match'] = first_match.get(item[owner_key])
        return {'rows': result, 'total': total, 'offset': offset, 'page_size': PAGE_SIZE,
                'terms': terms, 'query': query, 'kind': kind}
    finally:
        connection.close()


def detail(kind, identifier):
    connection = connect()
    try:
        if kind == 'researchers':
            person = connection.execute('SELECT r.*, a.name AS primary_area FROM researchers r JOIN research_areas a ON a.area_id=r.primary_area_id WHERE researcher_id=?', (identifier,)).fetchone()
            if person is None:
                return None
            result = dict(person)
            result['projects'] = rows(connection, 'SELECT p.project_id, p.project_code, p.title, p.summary, rp.contribution FROM researcher_projects rp JOIN projects p USING(project_id) WHERE rp.researcher_id=? ORDER BY p.project_id', (identifier,))
            result['capabilities'] = rows(connection, 'SELECT c.name, rc.proficiency, rc.offer_description FROM researcher_capabilities rc JOIN capabilities c USING(capability_id) WHERE researcher_id=? ORDER BY c.name', (identifier,))
            result['needs'] = rows(connection, 'SELECT n.*, c.name AS capability FROM researcher_needs n LEFT JOIN capabilities c USING(capability_id) WHERE researcher_id=? ORDER BY need_id', (identifier,))
            result['outcomes'] = rows(connection, 'SELECT * FROM researcher_outcomes WHERE researcher_id=? ORDER BY outcome_id', (identifier,))
        else:
            project = connection.execute('SELECT p.*, t.name AS topic, a.name AS research_area FROM projects p JOIN topics t USING(topic_id) JOIN research_areas a USING(area_id) WHERE project_id=?', (identifier,)).fetchone()
            if project is None:
                return None
            result = dict(project)
            result['researchers'] = rows(connection, 'SELECT r.researcher_id, r.full_name, r.role, rp.contribution FROM researcher_projects rp JOIN researchers r USING(researcher_id) WHERE project_id=? ORDER BY r.full_name', (identifier,))
            result['needs'] = rows(connection, 'SELECT n.*, c.name AS capability FROM project_needs n LEFT JOIN capabilities c USING(capability_id) WHERE project_id=? ORDER BY need_id', (identifier,))
            result['outcomes'] = rows(connection, 'SELECT * FROM project_outcomes WHERE project_id=? ORDER BY outcome_id', (identifier,))
        return result
    finally:
        connection.close()


def collaborators(identifier):
    connection = connect()
    try:
        return rows(connection, '''SELECT provider_id, provider_name, provider_role,
            matching_capability, need, proficiency, cross_area
            FROM v_potential_collaborators WHERE seeker_id=?
            ORDER BY cross_area DESC, proficiency DESC, provider_name LIMIT 12''', (identifier,))
    finally:
        connection.close()


class Handler(BaseHTTPRequestHandler):
    server_version = 'ResearchConnections/2.0'

    def respond(self, status, payload, content_type='application/json; charset=utf-8'):
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() if content_type.startswith('application/json') else payload
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        try:
            if path == '/api/overview':
                return self.respond(200, overview())
            parts = path.strip('/').split('/')
            if len(parts) in (2, 3, 4) and parts[0] == 'api' and parts[1] in ('researchers', 'projects'):
                if len(parts) == 2:
                    return self.respond(200, search(parts[1], parse_qs(parsed.query)))
                identifier = int(parts[2])
                if len(parts) == 4:
                    if parts[1] == 'researchers' and parts[3] == 'collaborators':
                        if detail('researchers', identifier) is None:
                            return self.respond(404, {'error': 'That person does not exist.'})
                        return self.respond(200, {'rows': collaborators(identifier)})
                    return self.respond(404, {'error': 'Not found.'})
                result = detail(parts[1], identifier)
                return self.respond(200 if result else 404, result or {'error': 'That record does not exist.'})
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/styles.css': ('styles.css', 'text/css; charset=utf-8'),
                     '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
            if path in files:
                filename, content_type = files[path]
                return self.respond(200, (STATIC / filename).read_bytes(), content_type)
            self.respond(404, {'error': 'Not found.'})
        except ValueError as error:
            self.respond(400, {'error': str(error)})
        except sqlite3.Error as error:
            message = 'That search took too long. Try a more specific word or phrase.' if str(error) == 'interrupted' else 'The database could not complete the search.'
            self.respond(503, {'error': message})

    def do_POST(self):
        self.respond(405, {'error': 'This directory supports read-only search.'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open-browser', action='store_true', help='Open the directory in your default browser.')
    args = parser.parse_args()
    if not DATABASE.is_file():
        raise SystemExit(f'Database missing: {DATABASE}. Run scripts/generate_dataset.py first.')
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError as error:
        raise SystemExit(f'Could not start on port {args.port}: {error}. If the directory is already running, open http://127.0.0.1:{args.port}; otherwise choose --port 8766.') from error
    print(f'Research Connections — http://127.0.0.1:{server.server_port}', flush=True)
    print('Press Ctrl+C to stop.', flush=True)
    if args.open_browser:
        webbrowser.open_new_tab(f'http://127.0.0.1:{server.server_port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
