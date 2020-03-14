"""Tests the authentication flows (except for the actual generation of claim
tokens)."""
import unittest
import requests
import os
from pypika import PostgreSQLQuery as Query, Table, Parameter, Interval
from pypika.functions import Now
import psycopg2
import helper
from hashlib import pbkdf2_hmac
from base64 import b64encode
import time


HOST = os.environ['TEST_WEB_HOST']


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = psycopg2.connect('')
        cls.cursor = cls.conn.cursor()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_claim_token_to_passwd_auth(self):
        # users will cascade to everything
        with helper.clear_tables(self.conn, self.cursor, ['users']):
            users = Table('users')
            self.cursor.execute(
                Query.into(users).columns(users.username)
                .insert(Parameter('%s'))
                .returning(users.id).get_sql(),
                ('testuser',)
            )
            (user_id,) = self.cursor.fetchone()
            claim_tokens = Table('claim_tokens')
            self.cursor.execute(
                Query.into(claim_tokens)
                .columns(claim_tokens.user_id, claim_tokens.token, claim_tokens.expires_at)
                .insert(Parameter('%s'), Parameter('%s'), Now())
                .get_sql(),
                (user_id, 'testtoken')
            )
            self.conn.commit()

            r = requests.post(
                f'{HOST}/users/claim',
                json={
                    'user_id': user_id,
                    'claim_token': 'testtoken',
                    'password': 'testpass',
                    'recaptcha_token': 'notoken'
                }
            )
            r.raise_for_status()
            self.assertEquals(r.status_code, 200)

            pauths = Table('password_authentications')
            self.cursor.execute(
                Query.from_(pauths).select(
                    pauths.user_id, pauths.human, pauths.hash_name,
                    pauths.hash, pauths.salt, pauths.iterations
                ).get_sql()
            )
            row = self.cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertIsNone(self.cursor.fetchone())
            self.assertEqual(row[0], user_id)
            self.assertTrue(row[1])

            exp_hash = b64encode(
                pbkdf2_hmac(
                    row[2],
                    'testpass'.encode('utf-8'),
                    row[4].encode('utf-8'),
                    row[5]
                )
            ).decode('ascii')
            self.assertEqual(row[3], exp_hash)

    def test_passwd_auth_to_authtoken(self):
        with helper.clear_tables(self.conn, self.cursor, ['users']):
            users = Table('users')
            self.cursor.execute(
                Query.into(users).columns(users.username)
                .insert(Parameter('%s'))
                .returning(users.id).get_sql(),
                ('testuser',)
            )
            (user_id,) = self.cursor.fetchone()
            passwd_hsh = b64encode(
                pbkdf2_hmac(
                    'sha256',
                    'testpass'.encode('utf-8'),
                    'salt'.encode('utf-8'),
                    10
                )
            ).decode('ascii')
            pauths = Table('password_authentications')
            self.cursor.execute(
                Query.into(pauths).columns(
                    pauths.user_id, pauths.human, pauths.hash_name,
                    pauths.hash, pauths.salt, pauths.iterations
                ).insert(
                    Parameter('%s'), True, Parameter('%s'),
                    Parameter('%s'), Parameter('%s'), Parameter('%s')
                ).get_sql(),
                (user_id, 'sha256', passwd_hsh, 'salt', 10)
            )
            self.conn.commit()
            r = requests.post(
                f'{HOST}/users/login',
                json={
                    'user_id': user_id,
                    'username': 'testuser',
                    'password': 'testpass',
                    'recaptcha_token': 'notoken'
                }
            )
            r.raise_for_status()
            self.assertEquals(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertIsInstance(body.get('token'), str)
            self.assertIsInstance(body.get('expires_at_utc'), float)
            self.assertGreaterEqual(body['expires_at_utc'], time.time())
            self.assertEqual(2, len(body))

            token = body['token']
            authtokens = Table('authtokens')
            self.cursor.execute(
                Query.from_(authtokens).select(authtokens.user_id)
                .where(authtokens.token == Parameter('%s')).get_sql(),
                (token,)
            )
            row = self.cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(user_id, row[0])

    def test_authtoken_to_users_me(self):
        with helper.clear_tables(self.conn, self.cursor, ['users']):
            users = Table('users')
            self.cursor.execute(
                Query.into(users).columns(users.username)
                .insert(Parameter('%s'))
                .returning(users.id).get_sql(),
                ('testuser',)
            )
            (user_id,) = self.cursor.fetchone()
            authtokens = Table('authtokens')
            self.cursor.execute(
                Query.into(authtokens).columns(
                    authtokens.user_id, authtokens.token, authtokens.expires_at
                ).insert(Parameter('%s'), Parameter('%s'), Now() + Interval(hours=1))
                .get_sql(),
                (user_id, 'testtoken')
            )
            self.conn.commit()

            r = requests.get(
                f'{HOST}/users/{user_id}/me',
                cookies={'authtoken': 'testtoken'}
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.body()
            self.assertIsInstance(body, dict)
            self.assertIsInstance(body.get('username'), str)
            self.assertEqual(len(body), 1)
            self.assertEqual(body['username'], 'testuser')


if __name__ == '__main__':
    unittest.main()
