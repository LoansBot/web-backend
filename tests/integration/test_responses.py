"""Contains basic tests for the /log endpoints."""
import unittest
import requests
import os
import helper
import psycopg2
from pypika import PostgreSQLQuery as Query, Table, Parameter


HOST = os.environ['TEST_WEB_HOST']


class BasicResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = psycopg2.connect('')
        cls.cursor = cls.conn.cursor()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_index(self):
        with helper.clear_tables(self.conn, self.cursor, ['responses']):
            responses = Table('responses')
            self.cursor.execute(
                Query.into(responses).columns(
                    responses.name,
                    responses.response_body,
                    responses.description
                ).insert(
                    *[Parameter('%s') for _ in range(3)]
                ).get_sql(),
                (
                    'foobar',
                    'body',
                    'desc'
                )
            )

            with helper.user_with_token(self.conn, self.cursor, ['responses']) as (user_id, token):
                r = requests.get(
                    HOST + '/responses',
                    headers={'Authorization': f'bearer {token}'}
                )
                r.raise_for_status()
                self.assertEqual(r.status_code, 200)

                body = r.json()
                self.assertIsInstance(body, dict)
                self.assertIsInstance(body.get('responses'), list)
                self.assertEqual(len(body), 1)

                res_arr = body['responses']
                self.assertEqual(len(res_arr), 1)
                self.assertIsInstance(res_arr[0], str)
                self.assertEqual(res_arr[0], 'foobar')

    def test_index_no_perm(self):
        with helper.clear_tables(self.conn, self.cursor, ['responses']):
            responses = Table('responses')
            self.cursor.execute(
                Query.into(responses).columns(
                    responses.name,
                    responses.response_body,
                    responses.description
                ).insert(
                    *[Parameter('%s') for _ in range(3)]
                ).get_sql(),
                (
                    'foobar',
                    'body',
                    'desc'
                )
            )

            with helper.user_with_token(self.conn, self.cursor, []) as (user_id, token):
                r = requests.get(
                    HOST + '/responses',
                    headers={'Authorization': f'bearer {token}'}
                )
                self.assertEqual(r.status_code, 403)

    def test_show(self):
        with helper.clear_tables(self.conn, self.cursor, ['responses']):
            responses = Table('responses')
            self.cursor.execute(
                Query.into(responses).columns(
                    responses.name,
                    responses.response_body,
                    responses.description
                ).insert(
                    *[Parameter('%s') for _ in range(3)]
                ).get_sql(),
                (
                    'foobar',
                    'body',
                    'desc'
                )
            )

            with helper.user_with_token(self.conn, self.cursor, ['responses']) as (user_id, token):
                r = requests.get(
                    HOST + '/responses/foobar',
                    headers={'Authorization': f'bearer {token}'}
                )
                r.raise_for_status()
                self.assertEqual(r.status_code, 200)

                body = r.json()
                self.assertIsInstance(body, dict)
                self.assertIsInstance(body.get('id'), int)
                self.assertIsInstance(body.get('name'), str)
                self.assertIsInstance(body.get('body'), str)
                self.assertIsInstance(body.get('desc'), str)
                self.assertIsInstance(body.get('created_at'), int)
                self.assertIsInstance(body.get('updated_at'), int)
                self.assertEqual(body['name'], 'foobar')
                self.assertEqual(body['body'], 'body')
                self.assertEqual(body['desc'], 'desc')

    def test_histories(self):
        with helper.clear_tables(self.conn, self.cursor, ['responses', 'response_histories']):
            responses = Table('responses')
            self.cursor.execute(
                Query.into(responses).columns(
                    responses.name,
                    responses.response_body,
                    responses.description
                ).insert(
                    *[Parameter('%s') for _ in range(3)]
                ).returning(responses.id).get_sql(),
                (
                    'foobar',
                    'body',
                    'desc'
                )
            )
            (respid,) = self.cursor.fetchone()

            with helper.user_with_token(self.conn, self.cursor, ['responses']) as (user_id, token):
                resp_hists = Table('response_histories')
                self.cursor.execute(
                    Query.into(resp_hists).columns(
                        resp_hists.response_id,
                        resp_hists.user_id,
                        resp_hists.old_raw,
                        resp_hists.new_raw,
                        resp_hists.reason,
                        resp_hists.old_desc,
                        resp_hists.new_desc
                    ).insert(
                        *[Parameter('%s') for _ in range(7)]
                    ).returning(resp_hists.id).get_sql(),
                    (
                        respid,
                        user_id,
                        'older raw',
                        'body',
                        'testing',
                        'old desc',
                        'desc'
                    )
                )
                (hist_id,) = self.cursor.fetchone()

                r = requests.get(
                    HOST + '/responses/foobar/histories',
                    headers={'Authorization': f'bearer {token}'}
                )
                r.raise_for_status()
                self.assertEqual(r.status_code, 200)

                body = r.json()
                self.assertIsInstance(body, dict)
                self.assertIsInstance(body.get('history'), dict)
                self.assertIsInstance(body.get('number_truncated'), int)
                self.assertEqual(len(body), 2)

                self.assertEqual(body['number_truncated'], 0)

                history = body['history']
                self.assertIsInstance(history.get('items'), list)
                self.assertEqual(len(history), 1)

                items = history['items']
                self.assertEqual(len(items), 1)
                self.assertIsInstance(items[0], dict)

                item = items[0]
                self.assertIsInstance(item.get('id'), int)
                self.assertIsInstance(item.get('edited_by'), dict)
                self.assertIsInstance(item.get('edited_reason'), str)
                self.assertIsInstance(item.get('old_body'), str)
                self.assertIsInstance(item.get('new_body'), str)
                self.assertIsInstance(item.get('old_desc'), str)
                self.assertIsInstance(item.get('new_desc'), str)
                self.assertIsInstance(item.get('edited_at'), int)

                self.assertEqual(item['id'], hist_id)
                self.assertEqual(item['edited_reason'], 'testing')
                self.assertEqual(item['old_body'], 'older raw')
                self.assertEqual(item['new_body'], 'body')
                self.assertEqual(item['old_desc'], 'old desc')
                self.assertEqual(item['new_desc'], 'desc')

                edited_by = item['edited_by']
                self.assertIsInstance(edited_by.get('id'), int)
                self.assertIsInstance(edited_by.get('username'), str)
                self.assertEqual(edited_by['id'], user_id)


if __name__ == '__main__':
    unittest.main()
