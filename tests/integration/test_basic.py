"""A sample test that is expected to be removed later"""
import unittest
import requests
import os


HOST = os.environ['TEST_WEB_HOST']


class BasicResponseTests(unittest.TestCase):
    def test_root_gives_200(self):
        r = requests.get(HOST)
        r.raise_for_status()
        self.assertEquals(r.status_code, 200)

    def test_log_gives_200(self):
        r = requests.get(HOST + '/test_log')
        r.raise_for_status()
        self.assertEquals(r.status_code, 200)

    def test_cache_gives_200(self):
        r = requests.get(HOST + '/test_cache')
        r.raise_for_status()
        self.assertEquals(r.status_code, 200)

    def test_amqp_gives_200(self):
        r = requests.get(HOST + '/test_amqp')
        r.raise_for_status()
        self.assertEquals(r.status_code, 200)


if __name__ == '__main__':
    unittest.main()
