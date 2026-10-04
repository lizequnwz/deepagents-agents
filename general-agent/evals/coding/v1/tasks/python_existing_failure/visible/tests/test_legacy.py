import unittest
class Legacy(unittest.TestCase):
    def test_known_failure(self):
        self.assertEqual(1, 2, "documented unrelated failure")
