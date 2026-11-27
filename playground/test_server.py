"""Run with: conda run -n base python -m unittest discover -s playground -v."""

import hashlib
import sqlite3
import unittest

import server


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_hash = hashlib.sha256(server.DATABASE.read_bytes()).digest()

    @classmethod
    def tearDownClass(cls):
        assert hashlib.sha256(server.DATABASE.read_bytes()).digest() == cls.original_hash

    def all_results(self, query, kind='researchers', **filters):
        parameters = {'q':[query], **{key:[str(value)] for key,value in filters.items()}}
        first = server.search(kind, parameters)
        result = first['rows'][:]
        for offset in range(first['page_size'], first['total'], first['page_size']):
            result.extend(server.search(kind, {**parameters, 'offset':[str(offset)]})['rows'])
        return result

    def ids(self, query, kind='researchers', **filters):
        key = 'researcher_id' if kind == 'researchers' else 'project_id'
        return {row[key] for row in self.all_results(query, kind, **filters)}

    def test_boolean_parser_and_phrases(self):
        self.assertEqual(server.parse_search('cellulose OR "carbon dioxide"'), [['cellulose'], ['carbon dioxide']])
        self.assertEqual(server.parse_search('carbon capture'), [['carbon', 'capture']])
        self.assertEqual(server.parse_search('carbon AND capture or water'), [['carbon','capture'],['water']])
        self.assertEqual(server.parse_search('"OR"'), [['OR']])
        self.assertEqual(server.parse_search('“carbon dioxide”'), [['carbon dioxide']])
        self.assertEqual(server.parse_search(''), [])
        for query in ['"unfinished', 'OR cellulose', 'carbon OR', 'carbon AND OR water', '""', 'x'*201]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                server.parse_search(query)

    def test_cellulose_finds_people_through_actual_projects(self):
        connection = server.connect()
        expected = {row[0] for row in connection.execute("""
            SELECT DISTINCT rp.researcher_id FROM researcher_projects rp
            JOIN projects p USING(project_id)
            WHERE p.summary LIKE '%cellulose%' OR p.title LIKE '%cellulose%'
        """)}
        own_summaries = connection.execute("SELECT count(*) FROM researchers WHERE summary LIKE '%cellulose%'").fetchone()[0]
        connection.close()
        actual = self.ids('cellulose', scope='research')
        self.assertEqual(own_summaries, 0)
        self.assertGreater(len(expected), 0)
        self.assertEqual(actual, expected)

    def test_or_is_union_and_words_are_intersection(self):
        cellulose = self.ids('cellulose', scope='research')
        carbon = self.ids('carbon', scope='research')
        self.assertEqual(self.ids('cellulose OR carbon', scope='research'), cellulose | carbon)
        self.assertEqual(self.ids('cellulose carbon', scope='research'), cellulose & carbon)

    def test_quoted_phrase_and_case(self):
        connection = server.connect()
        expected = {row[0] for row in connection.execute("""
            SELECT project_id FROM projects
            WHERE title LIKE '%carbon dioxide%' OR summary LIKE '%carbon dioxide%'
        """)}
        connection.close()
        self.assertEqual(self.ids('"carbon dioxide"', 'projects', scope='research'), expected)
        self.assertEqual(self.ids('"CARBON DIOXIDE"', 'projects', scope='research'), expected)

    def test_project_titles_are_in_research_scope(self):
        result = server.search('projects', {'q':['biocomposites'], 'scope':['research']})
        self.assertGreater(result['total'], 0)
        self.assertTrue(all('biocomposites' in row['title'].lower() for row in result['rows']))

    def test_role_and_area_filter_all_or_branches(self):
        result = self.all_results('cellulose OR carbon', area=4, role='PhD')
        self.assertGreater(len(result), 0)
        self.assertTrue(all(row['role']=='PhD' and row['research_area']=='Water for Life' for row in result))

    def test_excerpts_are_real_matching_sources(self):
        result = server.search('researchers', {'q':['cellulose'], 'scope':['research']})
        connection = server.connect()
        for row in result['rows']:
            match = row['match']
            self.assertEqual(match['field'], 'project')
            self.assertIn('cellulose', match['text'].lower())
            membership = connection.execute('SELECT 1 FROM researcher_projects WHERE researcher_id=? AND project_id=?', (row['researcher_id'], match['source_id'])).fetchone()
            self.assertIsNotNone(membership)
        connection.close()

    def test_needs_expertise_and_outcomes_scopes(self):
        for scope, query, fields in [
            ('needs', 'equipment', {'needs','project_needs'}),
            ('expertise', 'electrochemistry', {'expertise'}),
            ('outcomes', '"thesis chapter"', {'outcomes','project_outcomes'}),
        ]:
            with self.subTest(scope=scope):
                result = server.search('researchers', {'q':[query], 'scope':[scope]})
                self.assertGreater(result['total'], 0)
                self.assertTrue(all(row['match']['field'] in fields for row in result['rows']))

    def test_literal_special_characters_and_no_sql_injection(self):
        for query in ['%', '_', '\\', "x' UNION SELECT 1--"]:
            with self.subTest(query=query):
                result = server.search('researchers', {'q':[query]})
                if query != '%':
                    self.assertEqual(result['total'], 0)
                else:
                    self.assertTrue(all('%' in row['match']['text'] for row in result['rows']))

    def test_pagination_has_no_repeated_people(self):
        first = server.search('researchers', {})
        second = server.search('researchers', {'offset':[str(server.PAGE_SIZE)]})
        self.assertEqual(first['total'], 1000)
        self.assertEqual(len(first['rows']), server.PAGE_SIZE)
        self.assertFalse({r['researcher_id'] for r in first['rows']} & {r['researcher_id'] for r in second['rows']})
        last = server.search('researchers', {'offset':['99999']})
        self.assertEqual(last['offset'], 990)
        self.assertEqual(len(last['rows']), 10)

    def test_profiles_and_collaborator_relationships(self):
        person = server.detail('researchers', 1)
        self.assertEqual(person['full_name'], 'Esra DeSantis')
        for project in person['projects']:
            detail = server.detail('projects', project['project_id'])
            self.assertIn(1, [row['researcher_id'] for row in detail['researchers']])
        self.assertIsNone(server.detail('researchers', -1))
        matches = server.collaborators(1)
        self.assertTrue(matches)
        self.assertTrue(all(row['provider_id'] != 1 and row['proficiency'] >= 4 for row in matches))
        connection = server.connect()
        for match in matches:
            shared = connection.execute('SELECT 1 FROM researcher_projects a JOIN researcher_projects b USING(project_id) WHERE a.researcher_id=1 AND b.researcher_id=?', (match['provider_id'],)).fetchone()
            self.assertIsNone(shared)
        connection.close()

    def test_connection_cannot_change_dataset(self):
        connection = server.connect()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE researchers SET summary='changed'")
        finally:
            connection.close()

    def test_invalid_filters_fail_clearly(self):
        for parameters in [{'area':['99']}, {'scope':['sql']}, {'role':['Professor']}, {'offset':['invalid']}]:
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                server.search('researchers', parameters)

    def test_counts(self):
        self.assertEqual(server.overview()['counts'], {'researchers':1000,'projects':1500,'researcher_projects':3000})

    def test_network_has_exact_shared_project_relationships(self):
        graph = server.network()
        self.assertEqual(len(graph['nodes']), 1000)
        self.assertEqual(len(graph['links']), 2237)
        self.assertEqual(len({node['id'] for node in graph['nodes']}), 1000)
        self.assertEqual(sum(node['degree'] for node in graph['nodes']), 2 * len(graph['links']))
        connection = server.connect()
        memberships = {}
        for person, project in connection.execute('SELECT researcher_id,project_id FROM researcher_projects'):
            memberships.setdefault(person, set()).add(project)
        connection.close()
        expected = {(a,b):len(memberships[a] & memberships[b]) for a in memberships for b in memberships if a < b and memberships[a] & memberships[b]}
        actual = {(edge['source'],edge['target']):edge['shared_projects'] for edge in graph['links']}
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
