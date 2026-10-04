import unittest
from increment import increment
class Tests(unittest.TestCase):
    def test_increment(self):
        self.assertEqual(increment(1), 3)
