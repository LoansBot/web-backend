"""Tests the authentication flows (except for the actual generation of claim
tokens)."""
import unittest
import requests
import os
from pypika import PostgreSQLQuery as Query, Table, Parameter
from pypika.functions import Now
import psycopg2
import helper
from hashlib import pbkdf2_hmac
from base64 import b64encode


HOST = os.environ['TEST_WEB_HOST']


class AuthTests(unittest.TestCase):
    @classmethod
    def setupClass(cls):
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
                Query.into(users).columns(users.username).values('testuser')
                .returning(users.id).get_sql()
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
                '/claim',
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

    # TODO: test login with passwd auth
    # TODO: test /users/{user_id}/me with token auth


if __name__ == '__main__':
    unittest.main()
