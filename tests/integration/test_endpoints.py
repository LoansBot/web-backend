"""Verifies that the endpoints endpoints largely work as expected"""
import unittest
import requests
import os
import psycopg2
import helper
from datetime import date
from pypika import PostgreSQLQuery as Query, Table, Parameter


HOST = os.environ['TEST_WEB_HOST']
endpoints = Table('endpoints')
ep_history = Table('endpoint_history')
endpoint_params = Table('endpoint_params')
ep_param_history = Table('endpoint_param_history')
endpoint_alts = Table('endpoint_alternatives')
ep_alt_history = Table('endpoint_alternative_history')


class EndpointsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = psycopg2.connect('')
        cls.cursor = cls.conn.cursor()

        cls.cursor.execute('TRUNCATE users CASCADE')
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def tearDown(self):
        self.cursor.execute('TRUNCATE users CASCADE')
        self.cursor.execute('TRUNCATE endpoints CASCADE')
        self.cursor.execute('TRUNCATE endpoint_history CASCADE')
        self.cursor.execute('TRUNCATE endpoint_param_history CASCADE')
        self.cursor.execute('TRUNCATE endpoint_alternative_history CASCADE')
        self.conn.commit()

    def test_blank_index_200(self):
        r = requests.get(HOST + '/endpoints')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)

        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['endpoint_slugs'], [])
        self.assertIsNone(body['after_slug'], None)
        self.assertIsNone(body['before_slug'], None)

    def test_single_index_200(self):
        self.cursor.execute(
            Query.into(endpoints).columns(
                endpoints.slug,
                endpoints.path,
                endpoints.description_markdown
            ).insert(*[Parameter('%s') for _ in range(3)])
            .get_sql(),
            ('foobar', 'foobar', 'foobar')
        )
        self.conn.commit()

        r = requests.get(HOST + '/endpoints')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['endpoint_slugs'], ['foobar'])
        self.assertIsNone(body['before_slug'])
        self.assertIsNone(body['after_slug'])

    def test_index_ordering_and_limit(self):
        self.cursor.execute(
            Query.into(endpoints).columns(
                endpoints.slug,
                endpoints.path,
                endpoints.description_markdown
            ).insert(*[Parameter('%s') for _ in range(3)])
            .get_sql(),
            ('foobar1', 'foobar1', 'foobar')
        )
        self.cursor.execute(
            Query.into(endpoints).columns(
                endpoints.slug,
                endpoints.path,
                endpoints.description_markdown
            ).insert(*[Parameter('%s') for _ in range(3)])
            .get_sql(),
            ('foobar2', 'foobar2', 'foobar2')
        )
        self.conn.commit()

        r = requests.get(HOST + '/endpoints')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['endpoint_slugs'], ['foobar1', 'foobar2'])
        self.assertIsNone(body['before_slug'])
        self.assertIsNone(body['after_slug'])

        r = requests.get(HOST + '/endpoints?order=desc')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['endpoint_slugs'], ['foobar2', 'foobar1'])
        self.assertIsNone(body['before_slug'])
        self.assertIsNone(body['after_slug'])

        r = requests.get(HOST + '/endpoints?limit=1')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['endpoint_slugs'], ['foobar1'])
        self.assertIsNone(body['before_slug'])
        self.assertEqual(body['after_slug'], 'foobar1')

        r = requests.get(HOST + '/endpoints?order=desc&limit=1')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['endpoint_slugs'], ['foobar2'])
        self.assertEqual(body['before_slug'], 'foobar2')
        self.assertIsNone(body['after_slug'])

        r = requests.get(HOST + '/endpoints?after_slug=foobar1')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['endpoint_slugs'], ['foobar2'])
        self.assertIsNone(body['before_slug'])
        self.assertIsNone(body['after_slug'])

        r = requests.get(HOST + '/endpoints?order=desc&before_slug=foobar2')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['endpoint_slugs'], ['foobar1'])
        self.assertIsNone(body['before_slug'])
        self.assertIsNone(body['after_slug'])

    def test_suggest_blank(self):
        r = requests.get(HOST + '/endpoints/suggest')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)

        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['suggestions'], [])

    def test_suggest_good(self):
        self.cursor.execute(
            Query.into(endpoints).columns(
                endpoints.slug,
                endpoints.path,
                endpoints.description_markdown
            ).insert(*[Parameter('%s') for _ in range(3)])
            .get_sql(),
            ('foobar', 'foobar', 'foobar')
        )
        self.conn.commit()

        r = requests.get(HOST + '/endpoints/suggest?q=oob')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)

        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['suggestions'], ['foobar'])

    def test_suggest_bad(self):
        self.cursor.execute(
            Query.into(endpoints).columns(
                endpoints.slug,
                endpoints.path,
                endpoints.description_markdown
            ).insert(*[Parameter('%s') for _ in range(3)])
            .get_sql(),
            ('foobar', 'foobar', 'foobar')
        )
        self.conn.commit()

        r = requests.get(HOST + '/endpoints/suggest?q=noob')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)

        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['suggestions'], [])

    def test_suggest_limit(self):
        self.cursor.execute(
            Query.into(endpoints).columns(
                endpoints.slug,
                endpoints.path,
                endpoints.description_markdown
            ).insert(*[Parameter('%s') for _ in range(3)])
            .get_sql(),
            ('foobar1', 'foobar1', 'foobar')
        )
        self.cursor.execute(
            Query.into(endpoints).columns(
                endpoints.slug,
                endpoints.path,
                endpoints.description_markdown
            ).insert(*[Parameter('%s') for _ in range(3)])
            .get_sql(),
            ('foobar2', 'foobar2', 'foobar')
        )
        self.conn.commit()

        r = requests.get(HOST + '/endpoints/suggest?q=oob&limit=1')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)

        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(len(body['suggestions']), 1)
        if body['suggestions'] != ['foobar1']:
            self.assertEqual(body['suggestions'], ['foobar2'])

    def test_show_endpoint_404(self):
        r = requests.get(HOST + '/endpoints/foobar')
        self.assertEqual(r.status_code, 404)

    def test_show_endpoint_200(self):
        self.cursor.execute(
            Query.into(endpoints).columns(
                endpoints.slug,
                endpoints.path,
                endpoints.verb,
                endpoints.description_markdown
            ).insert(*[Parameter('%s') for _ in range(4)])
            .returning(endpoints.id)
            .get_sql(),
            ('foobar1', '/foobar1', 'GET', 'foobar')
        )
        (endpoint_id,) = self.cursor.fetchone()
        self.cursor.execute(
            Query.into(endpoints).columns(
                endpoints.slug,
                endpoints.path,
                endpoints.verb,
                endpoints.description_markdown
            ).insert(*[Parameter('%s') for _ in range(4)])
            .returning(endpoints.id)
            .get_sql(),
            ('foobar2', '/foobar2', 'POST', 'foobar')
        )
        (new_endpoint_id,) = self.cursor.fetchone()
        self.cursor.execute(
            Query.into(endpoint_params).columns(
                endpoint_params.endpoint_id,
                endpoint_params.location,
                endpoint_params.path,
                endpoint_params.name,
                endpoint_params.var_type,
                endpoint_params.description_markdown
            ).insert(*[Parameter('%s') for _ in range(6)])
            .get_sql(),
            (
                endpoint_id,
                'body',
                'bar.baz',
                'foo',
                'str',
                'The foo for the baz within the bar'
            )
        )
        self.cursor.execute(
            Query.into(endpoint_alts).columns(
                endpoint_alts.old_endpoint_id,
                endpoint_alts.new_endpoint_id,
                endpoint_alts.explanation_markdown
            ).insert(*[Parameter('%s') for _ in range(3)])
            .get_sql(),
            (
                endpoint_id,
                new_endpoint_id,
                'To migrate foo the bar'
            )
        )
        self.conn.commit()

        r = requests.get(HOST + '/endpoints/foobar1')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)

        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['slug'], 'foobar1')
        self.assertEqual(body['path'], '/foobar1')
        self.assertEqual(body['verb'], 'GET')
        self.assertEqual(body['description_markdown'], 'foobar')
        self.assertIsInstance(body['params'], list)
        self.assertEqual(len(body['params']), 1)
        param = body['params'][0]
        self.assertIsInstance(param, dict)
        self.assertEqual(param['location'], 'body')
        self.assertEqual(param['path'], ['bar', 'baz'])
        self.assertEqual(param['name'], 'foo')
        self.assertEqual(param['var_type'], 'str')
        self.assertIsNone(param.get('description_markdown'))
        self.assertIsInstance(param['added_date'], str)
        self.assertEqual(body['alternatives'], ['foobar2'])
        self.assertIsNone(body.get('deprecation_reason_markdown'))
        self.assertIsNone(body.get('deprecated_on'))
        self.assertIsNone(body.get('sunsets_on'))
        self.assertIsInstance(body['created_at'], float)
        self.assertIsInstance(body['updated_at'], float)

    def test_show_deprecated_endpoint_200(self):
        self.cursor.execute(
            Query.into(endpoints).columns(
                endpoints.slug,
                endpoints.path,
                endpoints.verb,
                endpoints.description_markdown,
                endpoints.deprecation_reason_markdown,
                endpoints.deprecated_on,
                endpoints.sunsets_on
            ).insert(*[Parameter('%s') for _ in range(7)])
            .returning(endpoints.id)
            .get_sql(),
            (
                'foobar1', '/foobar1', 'GET', 'foobar',
                'deprecated', date(2020, 9, 12),
                date(2021, 3, 12)
            )
        )
        self.conn.commit()

        r = requests.get(f'{HOST}/endpoints/foobar1')
        self.assertEqual(r.status_code, 200)

        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['slug'], 'foobar1')
        self.assertEqual(body['path'], '/foobar1')
        self.assertEqual(body['verb'], 'GET')
        self.assertEqual(body['description_markdown'], 'foobar')
        self.assertEqual(body['params'], [])
        self.assertEqual(body['alternatives'], [])
        self.assertEqual(body.get('deprecation_reason_markdown'), 'deprecated\n')
        self.assertEqual(body.get('deprecated_on'), '2020-09-12')
        self.assertEqual(body.get('sunsets_on'), '2021-03-12')
        self.assertIsInstance(body['created_at'], float)
        self.assertIsInstance(body['updated_at'], float)

    def test_show_param_404(self):
        r = requests.get(HOST + '/endpoints/foobar/params/query')
        self.assertEqual(r.status_code, 404)

    def test_show_param_200(self):
        self.cursor.execute(
            Query.into(endpoints).columns(
                endpoints.slug,
                endpoints.path,
                endpoints.description_markdown
            ).insert(*[Parameter('%s') for _ in range(3)])
            .returning(endpoints.id)
            .get_sql(),
            ('foobar', '/foobar', 'foobar')
        )
        (endpoint_id,) = self.cursor.fetchone()
        self.cursor.execute(
            Query.into(endpoint_params).columns(
                endpoint_params.endpoint_id,
                endpoint_params.location,
                endpoint_params.path,
                endpoint_params.name,
                endpoint_params.var_type,
                endpoint_params.description_markdown
            ).insert(*[Parameter('%s') for _ in range(6)])
            .get_sql(),
            (
                endpoint_id,
                'body',
                'bar.baz',
                'foo',
                'str',
                'The foo for the baz within the bar'
            )
        )
        self.conn.commit()

        r = requests.get(HOST + '/endpoints/foobar/params/body?path=bar.baz&name=foo')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)

        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['location'], 'body')
        self.assertEqual(body['path'], ['bar', 'baz'])
        self.assertEqual(body['name'], 'foo')
        self.assertEqual(body['var_type'], 'str')
        self.assertEqual(body['description_markdown'], 'The foo for the baz within the bar')
        self.assertIsInstance(body['added_date'], str)

    def test_show_alt_404(self):
        r = requests.get(HOST + '/endpoints/migrate/foobar1/foobar2')
        self.assertEqual(r.status_code, 404)

    def test_show_alt_200(self):
        self.cursor.execute(
            Query.into(endpoints).columns(
                endpoints.slug,
                endpoints.path,
                endpoints.description_markdown
            ).insert(*[Parameter('%s') for _ in range(3)])
            .returning(endpoints.id)
            .get_sql(),
            ('foobar1', '/foobar1', 'foobar')
        )
        (endpoint_id,) = self.cursor.fetchone()
        self.cursor.execute(
            Query.into(endpoints).columns(
                endpoints.slug,
                endpoints.path,
                endpoints.description_markdown
            ).insert(*[Parameter('%s') for _ in range(3)])
            .returning(endpoints.id)
            .get_sql(),
            ('foobar2', '/foobar2', 'foobar')
        )
        (new_endpoint_id,) = self.cursor.fetchone()
        self.cursor.execute(
            Query.into(endpoint_alts).columns(
                endpoint_alts.old_endpoint_id,
                endpoint_alts.new_endpoint_id,
                endpoint_alts.explanation_markdown
            ).insert(*[Parameter('%s') for _ in range(3)])
            .get_sql(),
            (
                endpoint_id,
                new_endpoint_id,
                'To migrate foo the bar'
            )
        )
        self.conn.commit()

        r = requests.get(HOST + '/endpoints/migrate/foobar1/foobar2')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)

        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(body['explanation_markdown'], 'To migrate foo the bar')
        self.assertIsInstance(body['created_at'], float)
        self.assertIsInstance(body['updated_at'], float)

    def test_create_endpoint_200(self):
        with helper.user_with_token(
                self.conn, self.cursor, add_perms=['create-endpoint']) as (user_id, token):
            r = requests.put(
                HOST + '/endpoints/foobar',
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'bearer {token}'
                },
                json={
                    'path': '/foobar',
                    'verb': 'GET',
                    'description_markdown': 'some text'
                }
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            self.cursor.execute(
                Query.from_(endpoints)
                .select(1)
                .where(endpoints.slug == Parameter('%s'))
                .where(endpoints.path == Parameter('%s'))
                .where(endpoints.verb == Parameter('%s'))
                .where(endpoints.description_markdown == Parameter('%s'))
                .where(endpoints.deprecation_reason_markdown.isnull())
                .where(endpoints.deprecated_on.isnull())
                .where(endpoints.sunsets_on.isnull())
                .get_sql(),
                ('foobar', '/foobar', 'GET', 'some text\n')
            )
            self.assertIsNotNone(self.cursor.fetchone())

            self.cursor.execute(
                Query.from_(ep_history)
                .select(1)
                .where(ep_history.user_id == Parameter('%s'))
                .where(ep_history.slug == Parameter('%s'))
                .where(ep_history.old_path.isnull())
                .where(ep_history.new_path == Parameter('%s'))
                .where(ep_history.old_verb.isnull())
                .where(ep_history.new_verb == Parameter('%s'))
                .where(ep_history.old_description_markdown.isnull())
                .where(ep_history.new_description_markdown == Parameter('%s'))
                .where(ep_history.old_deprecation_reason_markdown.isnull())
                .where(ep_history.new_deprecation_reason_markdown.isnull())
                .where(ep_history.old_deprecated_on.isnull())
                .where(ep_history.new_deprecated_on.isnull())
                .where(ep_history.old_sunsets_on.isnull())
                .where(ep_history.new_sunsets_on.isnull())
                .where(ep_history.old_in_endpoints.eq(False))
                .where(ep_history.new_in_endpoints.eq(True))
                .get_sql(),
                (
                    user_id,
                    'foobar',
                    '/foobar',
                    'GET',
                    'some text\n'
                )
            )
            self.assertIsNotNone(
                self.cursor.fetchone(),
                helper.TableContents(self.cursor, 'endpoint_history')
            )

    def test_update_endpoint_200(self):
        with helper.user_with_token(
                self.conn, self.cursor, add_perms=['update-endpoint']) as (user_id, token):
            self.cursor.execute(
                Query.into(endpoints)
                .columns(
                    endpoints.slug,
                    endpoints.path,
                    endpoints.description_markdown,
                )
                .insert(*[Parameter('%s') for _ in range(3)])
                .get_sql(),
                (
                    'foobar',
                    '/foobar',
                    'description\n'
                )
            )
            self.conn.commit()

            r = requests.put(
                HOST + '/endpoints/foobar',
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'bearer {token}'
                },
                json={
                    'path': '/foobar',
                    'verb': 'GET',
                    'description_markdown': 'desc2',
                    'deprecation_reason_markdown': 'deprecation reason',
                    'deprecated_on': '2020-09-09',
                    'sunsets_on': '2021-03-09'
                }
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            self.cursor.execute(
                Query.from_(endpoints)
                .select(1)
                .where(endpoints.slug == Parameter('%s'))
                .where(endpoints.path == Parameter('%s'))
                .where(endpoints.description_markdown == Parameter('%s'))
                .where(endpoints.deprecation_reason_markdown == Parameter('%s'))
                .where(endpoints.deprecated_on == Parameter('%s'))
                .where(endpoints.sunsets_on == Parameter('%s'))
                .get_sql(),
                (
                    'foobar',
                    '/foobar',
                    'desc2\n',
                    'deprecation reason\n',
                    date.fromisoformat('2020-09-09'),
                    date.fromisoformat('2021-03-09')
                )
            )
            self.assertIsNotNone(self.cursor.fetchone())

            self.cursor.execute(
                Query.from_(ep_history)
                .select(1)
                .where(ep_history.user_id == Parameter('%s'))
                .where(ep_history.slug == Parameter('%s'))
                .where(ep_history.old_path == Parameter('%s'))
                .where(ep_history.new_path == Parameter('%s'))
                .where(ep_history.old_description_markdown == Parameter('%s'))
                .where(ep_history.new_description_markdown == Parameter('%s'))
                .where(ep_history.old_deprecation_reason_markdown.isnull())
                .where(ep_history.new_deprecation_reason_markdown == Parameter('%s'))
                .where(ep_history.old_deprecated_on.isnull())
                .where(ep_history.new_deprecated_on == Parameter('%s'))
                .where(ep_history.old_sunsets_on.isnull())
                .where(ep_history.new_sunsets_on == Parameter('%s'))
                .where(ep_history.old_in_endpoints == Parameter('%s'))
                .where(ep_history.new_in_endpoints == Parameter('%s'))
                .where(ep_history.old_verb == Parameter('%s'))
                .where(ep_history.new_verb == Parameter('%s'))
                .get_sql(),
                (
                    user_id,
                    'foobar',
                    '/foobar',
                    '/foobar',
                    'description\n',
                    'desc2\n',
                    'deprecation reason\n',
                    date(2020, 9, 9),
                    date(2021, 3, 9),
                    True,
                    True,
                    'GET',
                    'GET'
                )
            )
            self.assertIsNotNone(
                self.cursor.fetchone(),
                helper.TableContents(self.cursor, 'endpoint_history')
            )

    def test_delete_endpoint_200(self):
        with helper.user_with_token(
                self.conn, self.cursor, add_perms=['delete-endpoint']) as (user_id, token):
            self.cursor.execute(
                Query.into(endpoints)
                .columns(
                    endpoints.slug,
                    endpoints.path,
                    endpoints.description_markdown,
                )
                .insert(*[Parameter('%s') for _ in range(3)])
                .get_sql(),
                (
                    'foobar',
                    '/foobar',
                    'description\n'
                )
            )
            self.conn.commit()

            r = requests.delete(
                f'{HOST}/endpoints/foobar',
                headers={
                    'Authorization': f'bearer {token}'
                }
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            self.cursor.execute(
                Query.from_(endpoints)
                .select(1)
                .where(endpoints.slug == Parameter('%s'))
                .get_sql(),
                ('foobar',)
            )
            self.assertIsNone(self.cursor.fetchone())

            self.cursor.execute(
                Query.from_(ep_history)
                .select(1)
                .where(ep_history.user_id == Parameter('%s'))
                .where(ep_history.slug == Parameter('%s'))
                .where(ep_history.old_path == Parameter('%s'))
                .where(ep_history.new_path == Parameter('%s'))
                .where(ep_history.old_description_markdown == Parameter('%s'))
                .where(ep_history.new_description_markdown == Parameter('%s'))
                .where(ep_history.old_deprecation_reason_markdown.isnull())
                .where(ep_history.new_deprecation_reason_markdown.isnull())
                .where(ep_history.old_deprecated_on.isnull())
                .where(ep_history.new_deprecated_on.isnull())
                .where(ep_history.old_sunsets_on.isnull())
                .where(ep_history.new_sunsets_on.isnull())
                .where(ep_history.old_in_endpoints == Parameter('%s'))
                .where(ep_history.new_in_endpoints == Parameter('%s'))
                .where(ep_history.old_verb == Parameter('%s'))
                .where(ep_history.new_verb == Parameter('%s'))
                .get_sql(),
                (
                    user_id,
                    'foobar',
                    '/foobar',
                    '/foobar',
                    'description\n',
                    'description\n',
                    True,
                    False,
                    'GET',
                    'GET'
                )
            )
            self.assertIsNotNone(
                self.cursor.fetchone(),
                helper.TableContents(self.cursor, 'endpoint_history')
            )

    def test_create_endpoint_param_200(self):
        with helper.user_with_token(
                self.conn, self.cursor, add_perms=['update-endpoint']) as (user_id, token):
            self.cursor.execute(
                Query.into(endpoints)
                .columns(
                    endpoints.slug,
                    endpoints.path,
                    endpoints.description_markdown,
                )
                .insert(*[Parameter('%s') for _ in range(3)])
                .returning(endpoints.id)
                .get_sql(),
                (
                    'foobar',
                    '/foobar',
                    'description\n'
                )
            )
            (endpoint_id,) = self.cursor.fetchone()
            self.conn.commit()

            r = requests.put(
                f'{HOST}/endpoints/foobar/params/query',
                params={
                    'name': 'baz'
                },
                headers={
                    'Authorization': f'bearer {token}',
                    'Content-Type': 'application/json'
                },
                json={
                    'var_type': 'str',
                    'description_markdown': 'Baz the str'
                }
            )
            self.assertEqual(r.status_code, 200, r.content.decode('utf-8'))

            self.cursor.execute(
                Query.from_(endpoint_params)
                .select(1)
                .where(endpoint_params.endpoint_id == Parameter('%s'))
                .where(endpoint_params.location == Parameter('%s'))
                .where(endpoint_params.path == Parameter('%s'))
                .where(endpoint_params.name == Parameter('%s'))
                .where(endpoint_params.var_type == Parameter('%s'))
                .where(endpoint_params.description_markdown == Parameter('%s'))
                .get_sql(),
                (
                    endpoint_id,
                    'query',
                    '',
                    'baz',
                    'str',
                    'Baz the str\n'
                )
            )
            self.assertIsNotNone(self.cursor.fetchone())

            self.cursor.execute(
                Query.from_(ep_param_history)
                .select(1)
                .where(ep_param_history.user_id == Parameter('%s'))
                .where(ep_param_history.endpoint_slug == Parameter('%s'))
                .where(ep_param_history.location == Parameter('%s'))
                .where(ep_param_history.path == Parameter('%s'))
                .where(ep_param_history.name == Parameter('%s'))
                .where(ep_param_history.old_var_type.isnull())
                .where(ep_param_history.new_var_type == Parameter('%s'))
                .where(ep_param_history.old_description_markdown.isnull())
                .where(ep_param_history.new_description_markdown == Parameter('%s'))
                .where(ep_param_history.old_in_endpoint_params == Parameter('%s'))
                .where(ep_param_history.new_in_endpoint_params == Parameter('%s'))
                .get_sql(),
                (
                    user_id,
                    'foobar',
                    'query',
                    '',
                    'baz',
                    'str',
                    'Baz the str\n',
                    False,
                    True
                )
            )
            self.assertIsNotNone(
                self.cursor.fetchone(),
                helper.TableContents(
                    self.cursor, 'endpoint_param_history',
                    (
                        'expected [(any, {user_id}, \'foobar\', \'query\', \'\', '
                        '\'baz\', None, \'str\', None, \'Baz the str\\n\', False, True, any)]'
                        '; got {table_contents}'
                    ),
                    user_id=user_id
                )
            )

    def test_update_endpoint_param_200(self):
        with helper.user_with_token(
                self.conn, self.cursor, add_perms=['update-endpoint']) as (user_id, token):
            self.cursor.execute(
                Query.into(endpoints)
                .columns(
                    endpoints.slug,
                    endpoints.path,
                    endpoints.verb,
                    endpoints.description_markdown,
                )
                .insert(*[Parameter('%s') for _ in range(4)])
                .returning(endpoints.id)
                .get_sql(),
                (
                    'foobar',
                    '/foobar',
                    'PUT',
                    'description\n'
                )
            )
            (endpoint_id,) = self.cursor.fetchone()

            self.cursor.execute(
                Query.into(endpoint_params)
                .columns(
                    endpoint_params.endpoint_id,
                    endpoint_params.location,
                    endpoint_params.path,
                    endpoint_params.name,
                    endpoint_params.var_type,
                    endpoint_params.description_markdown
                )
                .insert(*[Parameter('%s') for _ in range(6)])
                .get_sql(),
                (
                    endpoint_id,
                    'body',
                    'joe.doe',
                    'smith',
                    'str, None',
                    'Smith for the doe within the joe\n'
                )
            )
            self.conn.commit()

            r = requests.put(
                f'{HOST}/endpoints/foobar/params/body',
                params={
                    'path': 'joe.doe',
                    'name': 'smith'
                },
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'bearer {token}'
                },
                json={
                    'var_type': 'str',
                    'description_markdown': 'description'
                }
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            self.cursor.execute(
                Query.from_(endpoint_params)
                .select(1)
                .where(endpoint_params.endpoint_id == Parameter('%s'))
                .where(endpoint_params.location == Parameter('%s'))
                .where(endpoint_params.path == Parameter('%s'))
                .where(endpoint_params.name == Parameter('%s'))
                .where(endpoint_params.var_type == Parameter('%s'))
                .where(endpoint_params.description_markdown == Parameter('%s'))
                .get_sql(),
                (
                    endpoint_id,
                    'body',
                    'joe.doe',
                    'smith',
                    'str',
                    'description\n'
                )
            )
            self.assertIsNotNone(self.cursor.fetchone())

            self.cursor.execute(
                Query.from_(ep_param_history)
                .select(1)
                .where(ep_param_history.user_id == Parameter('%s'))
                .where(ep_param_history.endpoint_slug == Parameter('%s'))
                .where(ep_param_history.location == Parameter('%s'))
                .where(ep_param_history.path == Parameter('%s'))
                .where(ep_param_history.name == Parameter('%s'))
                .where(ep_param_history.old_var_type == Parameter('%s'))
                .where(ep_param_history.new_var_type == Parameter('%s'))
                .where(ep_param_history.old_description_markdown == Parameter('%s'))
                .where(ep_param_history.new_description_markdown == Parameter('%s'))
                .where(ep_param_history.old_in_endpoint_params == Parameter('%s'))
                .where(ep_param_history.new_in_endpoint_params == Parameter('%s'))
                .get_sql(),
                (
                    user_id,
                    'foobar',
                    'body',
                    'joe.doe',
                    'smith',
                    'str, None',
                    'str',
                    'Smith for the doe within the joe\n',
                    'description\n',
                    True,
                    True
                )
            )
            self.assertIsNotNone(
                self.cursor.fetchone(),
                helper.TableContents(self.cursor, 'endpoint_param_history')
            )

    def test_delete_endpoint_param_200(self):
        with helper.user_with_token(
                self.conn, self.cursor, add_perms=['update-endpoint']) as (user_id, token):
            self.cursor.execute(
                Query.into(endpoints)
                .columns(
                    endpoints.slug,
                    endpoints.path,
                    endpoints.description_markdown,
                )
                .insert(*[Parameter('%s') for _ in range(3)])
                .returning(endpoints.id)
                .get_sql(),
                (
                    'foobar',
                    '/foobar',
                    'description\n'
                )
            )
            (endpoint_id,) = self.cursor.fetchone()

            self.cursor.execute(
                Query.into(endpoint_params)
                .columns(
                    endpoint_params.endpoint_id,
                    endpoint_params.location,
                    endpoint_params.path,
                    endpoint_params.name,
                    endpoint_params.var_type,
                    endpoint_params.description_markdown
                )
                .insert(*[Parameter('%s') for _ in range(6)])
                .get_sql(),
                (
                    endpoint_id,
                    'header',
                    '',
                    'baz',
                    'str, None',
                    'The baz if buzz\n'
                )
            )
            self.conn.commit()

            r = requests.delete(
                f'{HOST}/endpoints/foobar/params/header',
                params={
                    'name': 'baz'
                },
                headers={
                    'Authorization': f'bearer {token}'
                }
            )
            self.assertEqual(r.status_code, 200, r.content.decode('utf-8'))

            self.cursor.execute(
                Query.from_(endpoint_params)
                .select(1)
                .where(endpoint_params.endpoint_id == Parameter('%s'))
                .where(endpoint_params.location == Parameter('%s'))
                .where(endpoint_params.path == Parameter('%s'))
                .where(endpoint_params.name == Parameter('%s'))
                .get_sql(),
                (
                    endpoint_id,
                    'header',
                    '',
                    'baz'
                )
            )
            self.assertIsNone(self.cursor.fetchone())

            self.cursor.execute(
                Query.from_(ep_param_history)
                .select(1)
                .where(ep_param_history.user_id == Parameter('%s'))
                .where(ep_param_history.endpoint_slug == Parameter('%s'))
                .where(ep_param_history.location == Parameter('%s'))
                .where(ep_param_history.path == Parameter('%s'))
                .where(ep_param_history.name == Parameter('%s'))
                .where(ep_param_history.old_var_type == Parameter('%s'))
                .where(ep_param_history.new_var_type == Parameter('%s'))
                .where(ep_param_history.old_description_markdown == Parameter('%s'))
                .where(ep_param_history.new_description_markdown == Parameter('%s'))
                .where(ep_param_history.old_in_endpoint_params == Parameter('%s'))
                .where(ep_param_history.new_in_endpoint_params == Parameter('%s'))
                .get_sql(),
                (
                    user_id,
                    'foobar',
                    'header',
                    '',
                    'baz',
                    'str, None',
                    'str, None',
                    'The baz if buzz\n',
                    'The baz if buzz\n',
                    True,
                    False
                )
            )
            self.assertIsNotNone(
                self.cursor.fetchone(),
                helper.TableContents(self.cursor, 'endpoint_param_history')
            )

    def test_create_endpoint_alt_200(self):
        with helper.user_with_token(
                self.conn, self.cursor, add_perms=['update-endpoint']) as (user_id, token):
            self.cursor.execute(
                Query.into(endpoints)
                .columns(
                    endpoints.slug,
                    endpoints.path,
                    endpoints.description_markdown,
                )
                .insert(*[Parameter('%s') for _ in range(3)])
                .returning(endpoints.id)
                .get_sql(),
                (
                    'endpoint1',
                    '/one',
                    'description\n'
                )
            )
            (endpoint_one_id,) = self.cursor.fetchone()
            self.cursor.execute(
                Query.into(endpoints)
                .columns(
                    endpoints.slug,
                    endpoints.path,
                    endpoints.description_markdown,
                )
                .insert(*[Parameter('%s') for _ in range(3)])
                .returning(endpoints.id)
                .get_sql(),
                (
                    'endpoint2',
                    '/two',
                    'description\n'
                )
            )
            (endpoint_two_id,) = self.cursor.fetchone()
            self.conn.commit()

            r = requests.put(
                f'{HOST}/endpoints/migrate/endpoint1/endpoint2',
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'bearer {token}'
                },
                json={
                    'explanation_markdown': 'elephant'
                }
            )
            self.assertEqual(r.status_code, 200, r.content)

            self.cursor.execute(
                Query.from_(endpoint_alts)
                .select(1)
                .where(endpoint_alts.old_endpoint_id == Parameter('%s'))
                .where(endpoint_alts.new_endpoint_id == Parameter('%s'))
                .where(endpoint_alts.explanation_markdown == Parameter('%s'))
                .get_sql(),
                (
                    endpoint_one_id,
                    endpoint_two_id,
                    'elephant\n'
                )
            )
            self.assertIsNotNone(
                self.cursor.fetchone(),
                helper.TableContents(
                    self.cursor,
                    'endpoint_alternatives',
                    (
                        'expected [(any, {endpoint_one_id}, {endpoint_two_id}, '
                        '\'elephant\\n\', any, any)]; got {table_contents}'
                    ),
                    endpoint_one_id=endpoint_one_id,
                    endpoint_two_id=endpoint_two_id
                )
            )

            self.cursor.execute(
                Query.from_(ep_alt_history)
                .select(1)
                .where(ep_alt_history.user_id == Parameter('%s'))
                .where(ep_alt_history.old_endpoint_slug == Parameter('%s'))
                .where(ep_alt_history.new_endpoint_slug == Parameter('%s'))
                .where(ep_alt_history.old_explanation_markdown.isnull())
                .where(ep_alt_history.new_explanation_markdown == Parameter('%s'))
                .where(ep_alt_history.old_in_endpoint_alternatives == Parameter('%s'))
                .where(ep_alt_history.new_in_endpoint_alternatives == Parameter('%s'))
                .get_sql(),
                (
                    user_id,
                    'endpoint1',
                    'endpoint2',
                    'elephant\n',
                    False,
                    True
                )
            )
            self.assertIsNotNone(
                self.cursor.fetchone(),
                helper.TableContents(
                    self.cursor,
                    'endpoint_alternative_history',
                    (
                        'expected [(any, {user_id}, \'endpoint1\', \'endpoint2\', '
                        'None, \'elephant\\n\', False, True, any)]; got {table_contents}'
                    ),
                    user_id=user_id
                )
            )

    def test_update_endpoint_alt_200(self):
        with helper.user_with_token(
                self.conn, self.cursor, add_perms=['update-endpoint']) as (user_id, token):
            self.cursor.execute(
                Query.into(endpoints)
                .columns(
                    endpoints.slug,
                    endpoints.path,
                    endpoints.description_markdown,
                )
                .insert(*[Parameter('%s') for _ in range(3)])
                .returning(endpoints.id)
                .get_sql(),
                (
                    'endpoint1',
                    '/one',
                    'description\n'
                )
            )
            (endpoint_one_id,) = self.cursor.fetchone()
            self.cursor.execute(
                Query.into(endpoints)
                .columns(
                    endpoints.slug,
                    endpoints.path,
                    endpoints.description_markdown,
                )
                .insert(*[Parameter('%s') for _ in range(3)])
                .returning(endpoints.id)
                .get_sql(),
                (
                    'endpoint2',
                    '/two',
                    'description\n'
                )
            )
            (endpoint_two_id,) = self.cursor.fetchone()
            self.cursor.execute(
                Query.into(endpoint_alts)
                .columns(
                    endpoint_alts.old_endpoint_id,
                    endpoint_alts.new_endpoint_id,
                    endpoint_alts.explanation_markdown
                )
                .insert(*[Parameter('%s') for _ in range(3)])
                .get_sql(),
                (
                    endpoint_one_id,
                    endpoint_two_id,
                    'freezer\n'
                )
            )
            self.conn.commit()

            r = requests.put(
                f'{HOST}/endpoints/migrate/endpoint1/endpoint2',
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'bearer {token}'
                },
                json={
                    'explanation_markdown': 'elephant'
                }
            )
            self.assertEqual(r.status_code, 200, r.content)

            self.cursor.execute(
                Query.from_(endpoint_alts)
                .select(1)
                .where(endpoint_alts.old_endpoint_id == Parameter('%s'))
                .where(endpoint_alts.new_endpoint_id == Parameter('%s'))
                .where(endpoint_alts.explanation_markdown == Parameter('%s'))
                .get_sql(),
                (
                    endpoint_one_id,
                    endpoint_two_id,
                    'elephant\n'
                )
            )
            self.assertIsNotNone(
                self.cursor.fetchone(),
                helper.TableContents(
                    self.cursor,
                    'endpoint_alternatives',
                    (
                        'expected [(any, {endpoint_one_id}, {endpoint_two_id}, '
                        '\'elephant\\n\', any, any)]; got {table_contents}'
                    ),
                    endpoint_one_id=endpoint_one_id,
                    endpoint_two_id=endpoint_two_id
                )
            )

            self.cursor.execute(
                Query.from_(ep_alt_history)
                .select(1)
                .where(ep_alt_history.user_id == Parameter('%s'))
                .where(ep_alt_history.old_endpoint_slug == Parameter('%s'))
                .where(ep_alt_history.new_endpoint_slug == Parameter('%s'))
                .where(ep_alt_history.old_explanation_markdown == Parameter('%s'))
                .where(ep_alt_history.new_explanation_markdown == Parameter('%s'))
                .where(ep_alt_history.old_in_endpoint_alternatives == Parameter('%s'))
                .where(ep_alt_history.new_in_endpoint_alternatives == Parameter('%s'))
                .get_sql(),
                (
                    user_id,
                    'endpoint1',
                    'endpoint2',
                    'freezer\n',
                    'elephant\n',
                    True,
                    True
                )
            )
            self.assertIsNotNone(
                self.cursor.fetchone(),
                helper.TableContents(
                    self.cursor,
                    'endpoint_alternative_history',
                    (
                        'expected [(any, {user_id}, \'endpoint1\', \'endpoint2\', '
                        '\'freezer\\n\', \'elephant\\n\', True, True, any)]; got {table_contents}'
                    ),
                    user_id=user_id
                )
            )

    def test_delete_endpoint_alt_200(self):
        with helper.user_with_token(
                self.conn, self.cursor, add_perms=['update-endpoint']) as (user_id, token):
            self.cursor.execute(
                Query.into(endpoints)
                .columns(
                    endpoints.slug,
                    endpoints.path,
                    endpoints.description_markdown,
                )
                .insert(*[Parameter('%s') for _ in range(3)])
                .returning(endpoints.id)
                .get_sql(),
                (
                    'endpoint1',
                    '/one',
                    'description\n'
                )
            )
            (endpoint_one_id,) = self.cursor.fetchone()
            self.cursor.execute(
                Query.into(endpoints)
                .columns(
                    endpoints.slug,
                    endpoints.path,
                    endpoints.description_markdown,
                )
                .insert(*[Parameter('%s') for _ in range(3)])
                .returning(endpoints.id)
                .get_sql(),
                (
                    'endpoint2',
                    '/two',
                    'description\n'
                )
            )
            (endpoint_two_id,) = self.cursor.fetchone()
            self.cursor.execute(
                Query.into(endpoint_alts)
                .columns(
                    endpoint_alts.old_endpoint_id,
                    endpoint_alts.new_endpoint_id,
                    endpoint_alts.explanation_markdown
                )
                .insert(*[Parameter('%s') for _ in range(3)])
                .get_sql(),
                (
                    endpoint_one_id,
                    endpoint_two_id,
                    'freezer\n'
                )
            )
            self.conn.commit()

            r = requests.delete(
                f'{HOST}/endpoints/migrate/endpoint1/endpoint2',
                headers={
                    'Authorization': f'bearer {token}'
                }
            )
            self.assertEqual(r.status_code, 200, r.content)

            self.cursor.execute(
                Query.from_(endpoint_alts)
                .select(1)
                .where(endpoint_alts.old_endpoint_id == Parameter('%s'))
                .where(endpoint_alts.new_endpoint_id == Parameter('%s'))
                .get_sql(),
                (
                    endpoint_one_id,
                    endpoint_two_id
                )
            )
            self.assertIsNone(
                self.cursor.fetchone(),
                helper.TableContents(self.cursor, 'endpoint_alternatives')
            )

            self.cursor.execute(
                Query.from_(ep_alt_history)
                .select(1)
                .where(ep_alt_history.user_id == Parameter('%s'))
                .where(ep_alt_history.old_endpoint_slug == Parameter('%s'))
                .where(ep_alt_history.new_endpoint_slug == Parameter('%s'))
                .where(ep_alt_history.old_explanation_markdown == Parameter('%s'))
                .where(ep_alt_history.new_explanation_markdown == Parameter('%s'))
                .where(ep_alt_history.old_in_endpoint_alternatives == Parameter('%s'))
                .where(ep_alt_history.new_in_endpoint_alternatives == Parameter('%s'))
                .get_sql(),
                (
                    user_id,
                    'endpoint1',
                    'endpoint2',
                    'freezer\n',
                    'freezer\n',
                    True,
                    False
                )
            )
            self.assertIsNotNone(
                self.cursor.fetchone(),
                helper.TableContents(
                    self.cursor,
                    'endpoint_alternative_history',
                    (
                        'expected [(any, {user_id}, \'endpoint1\', \'endpoint2\', '
                        '\'freezer\\n\', \'freezer\\n\', True, False, any)]; got {table_contents}'
                    ),
                    user_id=user_id
                )
            )


if __name__ == '__main__':
    unittest.main()
