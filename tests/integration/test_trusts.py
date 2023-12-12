"""Verifies that the trust flows largely work as expected"""
import unittest
import requests
import os
import psycopg2
import helper
import time


HOST = os.environ['TEST_WEB_HOST']


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
        self.cursor.execute('TRUNCATE delayed_queue CASCADE')
        self.conn.commit()

    def test_queue_gives_401(self):
        r = requests.get(HOST + '/trusts/queue')
        self.assertEqual(r.status_code, 401)

    def test_queue_no_perm_gives_403(self):
        with helper.user_with_token(self.conn, self.cursor) as (user_id, token):
            r = requests.get(HOST + '/trusts/queue', headers={'authorization': f'bearer {token}'})
            self.assertEqual(r.status_code, 403)

    def test_empty_queue_with_perm(self):
        with helper.user_with_token(
                self.conn, self.cursor, add_perms=['view-trust-queue']) as (user_id, token):
            r = requests.get(HOST + '/trusts/queue', headers={'authorization': f'bearer {token}'})
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertEqual(body['queue'], [])
            self.assertIsNone(body.get('after_review_at'))
            self.assertIsNone(body.get('before_review_at'))

    def test_paginate_empty_queue_with_perm(self):
        with helper.user_with_token(
                self.conn, self.cursor, add_perms=['view-trust-queue']) as (user_id, token):
            r = requests.get(
                HOST + '/trusts/queue?after_review_at=5',
                headers={'authorization': f'bearer {token}'}
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertEqual(body['queue'], [])
            self.assertIsNone(body.get('after_review_at'))
            self.assertIsNone(body.get('before_review_at'))

            r = requests.get(
                HOST + '/trusts/queue?before_review_at=5.1',
                headers={'authorization': f'bearer {token}'}
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertEqual(body['queue'], [])
            self.assertIsNone(body.get('after_review_at'))
            self.assertIsNone(body.get('before_review_at'))

    def test_add_queue_item_401(self):
        r = requests.post(HOST + '/trusts/queue', json={
            'username': 'tjstretchalot',
            'review_at': time.time()
        })
        self.assertEqual(r.status_code, 401)

    def test_add_queue_item_403(self):
        with helper.user_with_token(self.conn, self.cursor) as (user_id, token):
            r = requests.post(
                HOST + '/trusts/queue',
                json={
                    'username': 'tjstretchalot',
                    'review_at': time.time()
                },
                headers={'authorization': f'bearer {token}'}
            )
            self.assertEqual(r.status_code, 403)

    def test_add_queue_item_new_user_200(self):
        with helper.user_with_token(
                self.conn, self.cursor, add_perms=['add-trust-queue']) as (user_id, token):
            self.cursor.execute('SELECT 1 FROM users WHERE username=%s', ('tjstretchalot',))
            row = self.cursor.fetchone()
            self.assertIsNone(row)

            r = requests.post(
                HOST + '/trusts/queue',
                json={
                    'username': 'tjstretchalot',
                    'review_at': time.time()
                },
                headers={'authorization': f'bearer {token}'}
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            self.cursor.execute('SELECT 1 FROM users WHERE username=%s', ('tjstretchalot',))
            row = self.cursor.fetchone()
            self.assertIsNotNone(row)

    def test_add_queue_item_existing_user_200(self):
        with helper.user_with_token(
                self.conn, self.cursor,
                username='foobar',
                add_perms=['add-trust-queue']) as (user_id, token):
            r = requests.post(
                HOST + '/trusts/queue',
                json={
                    'username': 'Foobar',
                    'review_at': time.time()
                },
                headers={'authorization': f'bearer {token}'}
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            self.cursor.execute('SELECT 1 FROM users WHERE username=%s', ('Foobar',))
            row = self.cursor.fetchone()
            self.assertIsNone(row)

    def test_set_queue_time_401(self):
        r = requests.put(HOST + '/trusts/queue/1', json={
            'review_at': time.time()
        })
        self.assertEqual(r.status_code, 401)

    def test_add_set_delete_queue_item_200(self):
        with helper.user_with_token(
                self.conn, self.cursor,
                username='foo',
                add_perms=[
                    'view-trust-queue',
                    'add-trust-queue',
                    'edit-trust-queue',
                    'remove-trust-queue'
                ]) as (user_id, token):
            headers = {'authorization': f'bearer {token}', 'cache-control': 'no-store'}
            og_review_at = time.time()
            r = requests.post(
                HOST + '/trusts/queue',
                json={
                    'username': 'foo',
                    'review_at': og_review_at
                },
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertEqual(body.get('username'), 'foo')
            self.assertAlmostEqual(body.get('review_at'), og_review_at, delta=1)
            self.assertIsInstance(body.get('uuid'), str)
            uuid = body.get('uuid')

            r = requests.get(
                HOST + '/trusts/queue',
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertIsInstance(body.get('queue'), list)
            self.assertEqual(len(body['queue']), 1)
            self.assertEqual(body['queue'][0]['uuid'], uuid)

            new_review_at = og_review_at + 30
            r = requests.put(
                HOST + f'/trusts/queue/{uuid}',
                json={
                    'review_at': new_review_at
                },
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            r = requests.get(
                HOST + f'/trusts/queue/{uuid}',
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertEqual(body.get('uuid'), uuid)
            self.assertEqual(body.get('username'), 'foo')
            self.assertAlmostEqual(body.get('review_at'), new_review_at, delta=1)

            r = requests.delete(
                HOST + f'/trusts/queue/{uuid}',
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            r = requests.get(
                HOST + f'/trusts/queue/{uuid}',
                headers=headers
            )
            self.assertEqual(r.status_code, 404)

    def test_user_deleted_after_in_queue(self):
        with helper.user_with_token(
            self.conn,
            self.cursor,
            username='foo',
            add_perms=[
                'view-trust-queue',
                'add-trust-queue',
                'edit-trust-queue',
                'remove-trust-queue',
            ],
        ) as (user_id, token):
            self.cursor.execute('SELECT 1 FROM users WHERE username=%s', ('foobar',))
            row = self.cursor.fetchone()
            self.assertIsNone(row)

            headers = {'authorization': f'bearer {token}', 'cache-control': 'no-store'}
            og_review_at = time.time()
            r = requests.post(
                HOST + '/trusts/queue',
                json={'username': 'foobar', 'review_at': og_review_at},
                headers=headers,
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertEqual(body.get('username'), 'foobar')
            self.assertAlmostEqual(body.get('review_at'), og_review_at, delta=1)
            self.assertIsInstance(body.get('uuid'), str)
            uuid = body.get('uuid')

            self.cursor.execute('SELECT 1 FROM users WHERE username=%s', ('foobar',))
            row = self.cursor.fetchone()
            self.assertIsNotNone(row)

            r = requests.get(HOST + '/trusts/queue', headers=headers)
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertIsInstance(body.get('queue'), list)
            self.assertEqual(len(body['queue']), 1)
            self.assertEqual(body['queue'][0]['uuid'], uuid)

            self.cursor.execute('DELETE FROM users WHERE username=%s', ('foobar',))
            self.assertEqual(self.cursor.rowcount, 1)

            r = requests.get(HOST + '/trusts/queue', headers=headers)
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertIsInstance(body.get('queue'), list)
            self.assertEqual(len(body['queue']), 0)

            r = requests.get(HOST + f'/trusts/queue/{uuid}', headers=headers)
            self.assertEqual(r.status_code, 404)

    def test_insert_new_user_loan_delay_200(self):
        with helper.user_with_token(
                self.conn, self.cursor,
                username='foo',
                add_perms=[
                    'add-trust-queue',
                    'edit-trust-queue'
                ]) as (user_id, token):
            headers = {'authorization': f'bearer {token}'}
            r = requests.put(
                HOST + '/trusts/loan_delays',
                json={
                    'username': 'foobar',
                    'loans_completed_as_lender': 14,
                    'review_no_earlier_than': time.time()
                },
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            self.cursor.execute(
                'SELECT 1 FROM users WHERE username=%s',
                ('foobar',)
            )
            row = self.cursor.fetchone()
            self.assertIsNotNone(row)

    def insert_existing_user_loan_delay_200(self):
        with helper.user_with_token(
                self.conn, self.cursor,
                username='foo',
                add_perms=[
                    'add-trust-queue',
                    'edit-trust-queue'
                ]) as (user_id, token):
            headers = {'authorization': f'bearer {token}'}
            r = requests.put(
                HOST + '/trusts/loan_delays',
                json={
                    'username': 'foo',
                    'loans_completed_as_lender': 14,
                    'review_no_earlier_than': time.time()
                },
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

    def update_delete_loan_delay_200(self):
        with helper.user_with_token(
                self.conn, self.cursor,
                username='foo',
                add_perms=[
                    'view-trust-queue',
                    'add-trust-queue',
                    'edit-trust-queue',
                    'remove-trust-queue'
                ]) as (user_id, token):
            headers = {
                'authorization': f'bearer {token}',
                'cache-control': 'no-cache'
            }
            og_loans_completed = 7
            og_review_no_earlier_than = time.time()
            r = requests.put(
                HOST + '/trusts/loan_delays',
                json={
                    'username': 'foo',
                    'loans_completed_as_lender': og_loans_completed,
                    'review_no_earlier_than': og_review_no_earlier_than
                },
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            r = requests.get(
                HOST + f'/trusts/loan_delays/{user_id}',
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertEqual(body.get('loans_completed_as_lender'), og_loans_completed)
            self.assertAlmostEqual(
                body.get('review_no_earlier_than'),
                og_review_no_earlier_than,
                delta=1
            )

            new_loans_completed = og_loans_completed * 2
            new_review_no_earlier_than = og_review_no_earlier_than + 30
            r = requests.put(
                HOST + '/trusts/loan_delays',
                json={
                    'username': 'foo',
                    'loans_completed_as_lender': new_loans_completed,
                    'review_no_earlier_than': new_review_no_earlier_than
                },
                headers=headers
            )

            r = requests.get(
                HOST + f'/trusts/loan_delays/{user_id}',
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertEqual(body.get('loans_completed_as_lender'), new_loans_completed)
            self.assertAlmostEqual(
                body.get('review_no_earlier_than'),
                new_review_no_earlier_than,
                delta=1
            )

            r = requests.delete(
                HOST + f'/trusts/loan_delays/{user_id}',
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            r = requests.get(
                HOST + f'/trusts/loan_delays/{user_id}',
                headers=headers
            )
            self.assertEqual(r.status_code, 404)

    def test_autodelete_loan_delay_on_queue_add(self):
        with helper.user_with_token(
                self.conn, self.cursor,
                username='foo',
                add_perms=[
                    'view-trust-queue',
                    'add-trust-queue',
                    'edit-trust-queue',
                    'remove-trust-queue'
                ]) as (user_id, token):
            headers = {
                'authorization': f'bearer {token}',
                'cache-control': 'no-cache'
            }
            og_loans_completed = 7
            og_review_no_earlier_than = time.time()
            r = requests.put(
                HOST + '/trusts/loan_delays',
                json={
                    'username': 'foo',
                    'loans_completed_as_lender': og_loans_completed,
                    'review_no_earlier_than': og_review_no_earlier_than
                },
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            r = requests.get(
                HOST + f'/trusts/loan_delays/{user_id}',
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertEqual(body.get('loans_completed_as_lender'), og_loans_completed)
            self.assertAlmostEqual(
                body.get('review_no_earlier_than'),
                og_review_no_earlier_than,
                delta=1
            )

            new_review_at = time.time() + 30
            r = requests.post(
                HOST + f'/trusts/queue',
                json={
                    'username': 'foo',
                    'review_at': new_review_at
                },
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            r = requests.get(
                HOST + f'/trusts/loan_delays/{user_id}',
                headers=headers
            )
            self.assertEqual(r.status_code, 404)

    def test_add_edit_index_trust_comment(self):
        with helper.user_with_token(
                self.conn, self.cursor,
                username='foo',
                add_perms=[
                    'view-trust-comments',
                    'create-trust-comments'
                ]) as (user_id, token):
            headers = {
                'authorization': f'bearer {token}',
                'cache-control': 'no-cache'
            }
            r = requests.get(
                HOST + f'/trusts/comments?target_user_id={user_id}',
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertEqual(body.get('comments'), [])
            self.assertIsNone(body.get('after_created_at'))
            self.assertIsNone(body.get('before_created_at'))

            r = requests.post(
                HOST + f'/trusts/comments?target_user_id={user_id}',
                json={
                    'comment': 'test'
                },
                headers=headers
            )
            r.raise_for_status()
            self.assertIn(r.status_code, [200, 201])

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertIsInstance(body.get('id'), int)
            self.assertEqual(body.get('author_id'), user_id)
            self.assertEqual(body.get('target_id'), user_id)
            self.assertEqual(body.get('comment'), 'test')
            self.assertTrue(body.get('editable'))
            self.assertIsInstance(body.get('created_at'), float)
            self.assertIsInstance(body.get('updated_at'), float)
            self.assertAlmostEqual(body['created_at'], body['updated_at'], delta=1)

            comment_id = body['id']

            r = requests.get(
                HOST + f'/trusts/comments?target_user_id={user_id}',
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertEqual(body.get('comments'), [comment_id])
            self.assertIsNone(body.get('after_created_at'))
            self.assertIsNone(body.get('before_created_at'))

            r = requests.get(
                HOST + f'/trusts/comments/{comment_id}',
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body.get('id'), comment_id)
            self.assertEqual(body.get('comment'), 'test')

            r = requests.put(
                HOST + f'/trusts/comments/{comment_id}',
                json={
                    'comment': 'edited'
                },
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body.get('comment'), 'edited')

            r = requests.get(
                HOST + f'/trusts/comments/{comment_id}',
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body.get('id'), comment_id)
            self.assertEqual(body.get('comment'), 'edited')

    def test_show_trust_status_401(self):
        r = requests.get(HOST + '/trusts/1', headers={'cache-control': 'no-cache'})
        self.assertEqual(r.status_code, 401)

    def test_show_trust_status_403(self):
        with helper.user_with_token(
                self.conn, self.cursor,
                username='foo',
                add_perms=[
                ]) as (user_id, token):
            headers = {
                'authorization': f'bearer {token}',
                'cache-control': 'no-cache'
            }
            r = requests.get(f'{HOST}/trusts/{user_id}', headers=headers)
            self.assertEqual(r.status_code, 403)

    def test_show_other_trust_status_403(self):
        with helper.user_with_token(
                self.conn, self.cursor,
                username='foo',
                add_perms=[
                    'view-self-trust'
                ]) as (user_id, token):
            headers = {
                'authorization': f'bearer {token}',
                'cache-control': 'no-cache'
            }
            r = requests.get(f'{HOST}/trusts/{user_id + 1}', headers=headers)
            self.assertEqual(r.status_code, 403)

    def test_show_trust_status_self_unknown_200(self):
        with helper.user_with_token(
                self.conn, self.cursor,
                username='foo',
                add_perms=[
                    'view-self-trust'
                ]) as (user_id, token):
            headers = {
                'authorization': f'bearer {token}',
                'cache-control': 'no-cache'
            }
            r = requests.get(f'{HOST}/trusts/{user_id}', headers=headers)
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertEqual(body.get('user_id'), user_id)
            self.assertEqual(body.get('status'), 'unknown')
            self.assertIsNone(body.get('reason'))

    def test_upsert_trust_status_200(self):
        with helper.user_with_token(
                self.conn, self.cursor,
                username='foo',
                add_perms=[
                    'view-self-trust',
                    'view-others-trust',
                    'upsert-trusts'
                ]) as (user_id, token):
            headers = {
                'authorization': f'bearer {token}',
                'cache-control': 'no-cache',
                'pragma': 'no-cache'
            }

            other_user_id = None
            self.cursor.execute(
                'INSERT INTO users (username) VALUES (%s) RETURNING id',
                ('test_user',)
            )
            (other_user_id,) = self.cursor.fetchone()
            self.conn.commit()

            r = requests.put(
                f'{HOST}/trusts',
                json={
                    'user_id': other_user_id,
                    'status': 'good',
                    'reason': 'test'
                },
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)

            r = requests.get(
                f'{HOST}/trusts/{other_user_id}',
                headers=headers
            )
            r.raise_for_status()
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertIsInstance(body, dict)
            self.assertEqual(body.get('user_id'), other_user_id)
            self.assertEqual(body.get('status'), 'good')
            self.assertIsNone(body.get('reason'))

    def test_upsert_bad_status_422(self):
        with helper.user_with_token(
                self.conn, self.cursor,
                username='foo',
                add_perms=[
                    'view-self-trust',
                    'view-others-trust',
                    'upsert-trusts'
                ]) as (user_id, token):
            headers = {
                'authorization': f'bearer {token}',
                'cache-control': 'no-cache',
                'pragma': 'no-cache'
            }
            r = requests.put(
                f'{HOST}/trusts',
                json={
                    'user_id': user_id,
                    'status': 'weird',
                    'reason': 'test'
                },
                headers=headers
            )
            self.assertEqual(r.status_code, 422)


if __name__ == '__main__':
    unittest.main()
