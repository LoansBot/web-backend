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
        with helper.clear_tables(self.conn, self.cursor, 'responses'):
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
        with helper.clear_tables(self.conn, self.cursor, 'responses'):
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
                self.assertEqual(r.status_code, 403)


if __name__ == '__main__':
    unittest.main()
