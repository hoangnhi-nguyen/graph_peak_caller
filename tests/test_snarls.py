import unittest

from graph_peak_caller.snarls import SnarlGraph
from offsetbasedgraph import Block

snarl_graph1 = SnarlGraph(
    {12: Block(20), 13: Block(21)},
    {11: [12, 13], 12: [14], 13: [14]},
    11, 14)

snarl_graph2 = SnarlGraph(
    {2: snarl_graph1, 5: Block(10), 3: Block(20)},
    {1: [3, 5], 5: [2], 2: [4], 3: [4]},
    1, 4)


class TestSnarlGraph(unittest.TestCase):
    def test_simple_length(self):
        length = snarl_graph1.length()
        self.assertEqual(length, 21)

    def test_nested_length(self):
        length = snarl_graph2.length()
        self.assertEqual(length, 31)

    def test_get_distance_dicts(self):
        starts_dict, ends_dict = snarl_graph2.get_distance_dicts()
        true_starts = {12: 10, 13: 10, 5: 0, 3: 0}
        true_ends = {12: 0, 13: 0, 5: 21, 3: 0}
        self.assertEqual(starts_dict, true_starts)
        self.assertEqual(ends_dict, true_ends)


if __name__ == "__main__":
    unittest.main()
