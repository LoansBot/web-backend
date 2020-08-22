"""Contains basic tests for the /log endpoints."""
import unittest
import requests
import os
import helper
import psycopg2


HOST = os.environ['TEST_WEB_HOST']


class LogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = psycopg2.connect('')
        cls.cursor = cls.conn.cursor()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_logs(self):
        # Test log isn't the best name for an endpoint which does this but it
        # avoids coupling this test with where logs are stored in the backend
        r = requests.get(HOST + '/test_log')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)

        with helper.user_with_token(self.conn, self.cursor, ['logs']) as (user_id, token):
            r = requests.get(
                HOST + '/logs',
                headers={'Authorization': f'bearer {token}'}
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict, f'body={body}')
            self.assertIsInstance(body.get('logs'), list, f'body={body}')
            for event in body['logs']:
                self.assertIsInstance(event, dict, f'event={event}')
                self.assertIsInstance(event.get('id'), int, f'event={event}')
                self.assertIsInstance(event.get('app_id'), int, f'event={event}')
                self.assertIsInstance(event.get('identifier'), str, f'event={event}')
                self.assertIsInstance(event.get('level'), int, f'event={event}')
                self.assertIsInstance(event.get('message'), str, f'event={event}')
                self.assertIsInstance(event.get('created_at'), int, f'created_at={event}')

    def test_logs_search(self):
        r = requests.get(HOST + '/test_log')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)

        with helper.user_with_token(self.conn, self.cursor, ['logs']) as (user_id, token):
            r = requests.get(
                HOST + '/logs',
                headers={'Authorization': f'bearer {token}'},
                params={'search': '%test%'}
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict, f'body={body}')
            self.assertIsInstance(body.get('logs'), list, f'body={body}')
            for event in body['logs']:
                self.assertIsInstance(event, dict, f'event={event}')
                self.assertIsInstance(event.get('id'), int, f'event={event}')
                self.assertIsInstance(event.get('app_id'), int, f'event={event}')
                self.assertIsInstance(event.get('identifier'), str, f'event={event}')
                self.assertIsInstance(event.get('level'), int, f'event={event}')
                self.assertIsInstance(event.get('message'), str, f'event={event}')
                self.assertIsInstance(event.get('created_at'), int, f'created_at={event}')

    def test_logs_no_auth(self):
        r = requests.get(HOST + '/logs')
        self.assertEqual(r.status_code, 403)

    def test_logs_valid_auth_but_no_perm(self):
        with helper.user_with_token(self.conn, self.cursor) as (user_id, token):
            r = requests.get(
                HOST + '/logs',
                headers={'Authorization': f'bearer {token}'}
            )
            self.assertEqual(r.status_code, 403)

    def test_logs_valid_auth_but_wrong_perm(self):
        with helper.user_with_token(self.conn, self.cursor, ['wrong']) as (user_id, token):
            r = requests.get(
                HOST + '/logs',
                headers={'Authorization': f'bearer {token}'}
            )
            self.assertEqual(r.status_code, 403)

    def test_applications(self):
        r = requests.get(HOST + '/test_log')
        r.raise_for_status()
        self.assertEqual(r.status_code, 200)

        with helper.user_with_token(self.conn, self.cursor, ['logs']) as (user_id, token):
            r = requests.get(
                HOST + '/logs/applications',
                headers={'Authorization': f'bearer {token}'}
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertIsInstance(body.get('applications'), dict, f'body={body}')
            self.assertGreaterEqual(len(body), 1)

            for k, v in body['applications'].items():
                self.assertIsInstance(k, str)
                try:
                    int(k)
                except ValueError:
                    self.assertFalse(True, f'key is not a str\'d int: {k} (body={body})')
                self.assertIsInstance(v, dict)
                self.assertIsInstance(v.get('name'), str)


if __name__ == '__main__':
    unittest.main()
