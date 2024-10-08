import unittest
from offsetbasedgraph import GraphWithReversals as Graph, Block, \
    DirectedInterval as Interval
from graph_peak_caller import Configuration
from graph_peak_caller.sample import get_fragment_pileup
from graph_peak_caller.intervals import Intervals
from util import from_intervals


class Tester(unittest.TestCase):

    def _create_reads(self):
        self.sample_reads = []
        for fragment in self.fragments:
            fragment.graph = self.graph
            left_sub = fragment.get_subinterval(0, self.read_length())
            self.sample_reads.append(left_sub)
            right_sub = fragment.get_subinterval(
                self.fragment_length() - self.read_length(),
                self.fragment_length())
            right_sub_reverse = right_sub.get_reverse()
            self.sample_reads.append(right_sub_reverse)

    def assert_final_pileup_equals_correct_pileup(self):
        found_pileup = self.fragment_pileup.get_sparse_values()
        correct_pileup = self.correct_pileup.get_sparse_values()
        print("Found pileup")
        print(found_pileup)
        print("Correct pileup")
        print(correct_pileup)
        self.assertTrue(found_pileup == correct_pileup)

    def setUp(self):
        self.set_graph()

    def run_callpeaks(self):
        self._create_reads()
        for read in self.sample_reads:
            print(read)

        self.graph_size = sum(block.length() for block in
                              self.graph.blocks.values())
        config = Configuration()
        config.fragment_length = self.fragment_length()
        config.read_length = self.read_length()
        self.fragment_pileup = get_fragment_pileup(
            self.graph, Intervals(self.sample_reads),
            config)

    def do_asserts(self):
        self.run_callpeaks()
        self.assert_final_pileup_equals_correct_pileup()


class TestCase(Tester):
    def set_graph(self):
        raise NotImplementedError()

    def get_correct_extended_pileup(self):
        raise NotImplementedError()

    def fragment_length(self):
        raise NotImplementedError()

    def read_length(self):
        raise NotImplementedError()


class TestLinearGraph(TestCase):
    def read_length(self):
        return 2

    def fragment_length(self):
        return 5

    def set_graph(self):
        self.graph = Graph({1: Block(5), 2: Block(5)}, {1: [2]})

    def test_single_fragment(self):
        self.correct_pileup = from_intervals(self.graph,
            [
                Interval(3, 3, [1, 2]),
                Interval(3, 3, [1, 2])
            ]
        )
        self.fragments = [Interval(3, 3, [1, 2])]
        self.do_asserts()

    def test_two_fragments(self):
        self.correct_pileup = from_intervals(self.graph,
            [
                Interval(3, 3, [1, 2]),
                Interval(3, 3, [1, 2]),
                Interval(0, 5, [1]),
                Interval(0, 5, [1]),
            ]
        )
        self.fragments = [
            Interval(0, 5, [1]),
            Interval(3, 3, [1, 2])
        ]
        self.do_asserts()


class TestLinearGraphFullNodeCovered(TestCase):
    def read_length(self):
        return 5

    def fragment_length(self):
        return 15

    def set_graph(self):
        self.graph = Graph({1: Block(5), 2: Block(5), 3: Block(5)}, {1: [2], 2: [3]})

    def test_single_fragment(self):

        self.correct_pileup = from_intervals(self.graph,
            [
                Interval(0, 5, [1, 2, 3]),
                Interval(0, 5, [1, 2, 3])
            ]
        )
        self.fragments = [Interval(0, 5, [1, 2, 3])]
        self.do_asserts()


class TestSplitGraph(TestCase):
    def read_length(self):
        return 5

    def fragment_length(self):
        return 15

    def set_graph(self):
        self.graph = Graph({1: Block(5), 2: Block(5), 3: Block(5), 4: Block(5)},
                           {1: [2, 3], 2: [4], 3: [4]})

    def test_single_fragment(self):
        self.correct_pileup = from_intervals(self.graph,
            [
                Interval(0, 5, [1, 2, 4]),
                Interval(0, 5, [1, 2, 4]),
                Interval(0, 5, [3]),
                Interval(0, 5, [3])
            ]
        )
        self.fragments = [Interval(0, 5, [1, 2, 4])]
        self.do_asserts()


class TestSplitGraph2(TestCase):
    def read_length(self):
        return 6

    def fragment_length(self):
        return 15

    def set_graph(self):
        self.graph = Graph(
            {1: Block(5), 2: Block(5), 3: Block(5), 4: Block(5)},
            {1: [2, 3], 2: [4], 3: [4]})

    def test_single_fragment(self):

        self.correct_pileup = from_intervals(self.graph,
            [
                Interval(0, 5, [1, 2, 4]),
                Interval(0, 5, [1, 2, 4]),
            ]
        )
        self.fragments = [Interval(0, 5, [1, 2, 4])]
        self.do_asserts()


if __name__ == "__main__":
    unittest.main()
