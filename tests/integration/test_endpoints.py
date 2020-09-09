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
endpoint_alts = Table('endpoint_alternatives')


class TrustsTests(unittest.TestCase):
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
            self.assertIsNotNone(self.cursor.fetchone())

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
                .where(ep_history.old_deprecated_on == Parameter('%s'))
                .where(ep_history.new_deprecated_on == Parameter('%s'))
                .where(ep_history.old_sunsets_on == Parameter('%s'))
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
                    None,
                    date(2020, 9, 9),
                    None,
                    date(2021, 3, 9),
                    True,
                    True,
                    'GET',
                    'GET'
                )
            )
            self.assertIsNotNone(self.cursor.fetchone())

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
                'foobar'
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
                .where(ep_history.old_deprecation_reason_markdown == Parameter('%s'))
                .where(ep_history.new_deprecation_reason_markdown == Parameter('%s'))
                .where(ep_history.old_deprecated_on == Parameter('%s'))
                .where(ep_history.new_deprecated_on == Parameter('%s'))
                .where(ep_history.old_sunsets_on == Parameter('%s'))
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
                    'description\n',
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    True,
                    False,
                    'GET',
                    'GET'
                )
            )
            self.assertIsNotNone(self.cursor.fetchone())

    def test_create_endpoint_param_200(self):
        pass

    def test_update_endpoint_param_200(self):
        pass

    def test_delete_endpoint_param_200(self):
        pass

    def test_create_endpoint_alt_200(self):
        pass

    def test_update_endpoint_alt_200(self):
        pass

    def test_delete_endpoint_alt_200(self):
        pass
