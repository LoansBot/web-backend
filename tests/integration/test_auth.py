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
                .columns(
                    claim_tokens.user_id,
                    claim_tokens.token,
                    claim_tokens.expires_at
                )
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
                    'captcha_token': 'notoken'
                }
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

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
                    'captcha_token': 'notoken'
                }
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertIsInstance(body.get('user_id'), int)
            self.assertIsInstance(body.get('token'), str)
            self.assertIsInstance(body.get('expires_at_utc'), float)
            self.assertEqual(body['user_id'], user_id)
            self.assertGreaterEqual(body['expires_at_utc'], time.time())
            self.assertEqual(3, len(body))

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
                    authtokens.user_id, authtokens.token, authtokens.expires_at,
                    authtokens.source_type, authtokens.source_id
                ).insert(
                    Parameter('%s'), Parameter('%s'), Now() + Interval(hours=1),
                    Parameter('%s'), Parameter('%s')
                )
                .get_sql(),
                (user_id, 'testtoken', 'other', 1)
            )
            self.conn.commit()

            r = requests.get(
                f'{HOST}/users/{user_id}/me',
                headers={'Authorization': 'bearer testtoken'}
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertIsInstance(body.get('username'), str)
            self.assertEqual(len(body), 1)
            self.assertEqual(body['username'], 'testuser')

            # headers
            self.assertIsInstance(r.headers.get('cache-control'), str)
            cc = r.headers.get('cache-control')
            self.assertIn('private', cc)
            self.assertIn('max-age', cc)
            self.assertIn('stale-while-revalidate', cc)
            self.assertIn('stale-if-error', cc)

            split_cache_control = cc.split(', ')
            split_cache_control.remove('private')
            cc_args = dict([itm.split('=') for itm in split_cache_control])
            for key in list(cc_args.keys()):
                cc_args[key] = int(cc_args[key])
            self.assertGreater(cc_args['max-age'], 0)
            self.assertGreater(cc_args['stale-while-revalidate'], 0)
            self.assertGreater(cc_args['stale-if-error'], 0)

    def test_failed_claim_token(self):
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
                    'claim_token': 'testtoken2',
                    'password': 'testpass',
                    'captcha_token': 'notoken'
                }
            )
            self.assertNotEqual(200, r.status_code)
            self.assertLess(r.status_code, 500)
            pauths = Table('password_authentications')
            self.cursor.execute(
                Query.from_(pauths).select(
                    pauths.user_id, pauths.human, pauths.hash_name,
                    pauths.hash, pauths.salt, pauths.iterations
                ).get_sql()
            )
            row = self.cursor.fetchone()
            self.assertIsNone(row)

    def test_failed_passwd_auth(self):
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
                    'password': 'testpass2',
                    'captcha_token': 'notoken'
                }
            )
            self.assertNotEqual(r.status_code, 200)
            self.assertLess(r.status_code, 500)

    def test_login_passwd_long(self):
        # It should not attempt to service this request as it would be
        # computationally very expensive to hash a password this long
        # (256 chars)
        with helper.clear_tables(self.conn, self.cursor, ['users']):
            r = requests.post(
                f'{HOST}/users/login',
                json={
                    'user_id': 1,
                    'username': 'testuser',
                    'password': 'test' * (256 // 4),
                    'captcha_token': 'notoken'
                }
            )
            self.assertEqual(r.status_code, 400)

    def test_me_no_token(self):
        r = requests.get(f'{HOST}/users/1/me')
        self.assertEqual(r.status_code, 403)

    def test_me_single_string_token(self):
        r = requests.get(
            f'{HOST}/users/1/me',
            headers={'Authorization': 'token'}
        )
        self.assertEqual(r.status_code, 403)

    def test_me_bad_token(self):
        r = requests.get(
            f'{HOST}/users/1/me',
            headers={'Authorization': 'bearer token'}
        )
        self.assertEqual(r.status_code, 403)

    def test_me_token_spaces(self):
        r = requests.get(
            f'{HOST}/users/1/me',
            headers={'Authorization': 'bearer token token'}
        )
        self.assertEqual(r.status_code, 403)


if __name__ == '__main__':
    unittest.main()
