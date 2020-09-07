"""Verifies that the endpoints endpoints largely work as expected"""
import unittest
import requests
import os
import psycopg2
from pypika import PostgreSQLQuery as Query, Table, Parameter


HOST = os.environ['TEST_WEB_HOST']
endpoints = Table('endpoints')
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
        self.assertEqual(body['markdown_description'], 'foobar')
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

        r = requests.get(HOST + 'endpoints/foobar/params/body?path=bar.baz&name=foo')
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
