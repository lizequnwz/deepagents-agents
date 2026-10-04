import unittest
from selection import first_or_none
class Tests(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(first_or_none([]))
