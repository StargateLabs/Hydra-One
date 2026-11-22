import unittest
from serve.visual_python_update import next_previous


class PreviousSelection(unittest.TestCase):
    def test_first_activation_keeps_the_active_runtime(self):
        original = {'plan_directory': 'ml'}
        candidate = {'plan_directory': 'candidate'}
        self.assertEqual(next_previous({'active': original, 'previous': None}, candidate), original)

    def test_repeated_activation_keeps_the_original_previous(self):
        original = {'plan_directory': 'ml'}
        candidate = {'plan_directory': 'candidate'}
        self.assertEqual(next_previous({'active': candidate, 'previous': original}, candidate), original)


if __name__ == '__main__':
    unittest.main()
