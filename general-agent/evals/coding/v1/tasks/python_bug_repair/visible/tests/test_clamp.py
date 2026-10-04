import unittest
from clamp import clamp
class Tests(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 3), 3)
    def test_bounds(self):
        with self.assertRaises(ValueError): clamp(1, 3, 0)
