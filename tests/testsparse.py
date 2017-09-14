import unittest
import numpy as np
from graph_peak_caller.sparsepileup import \
        ValuedIndexes, \
        SparsePileup, \
        SparseControlSample, \
        starts_and_ends_to_sparse_pileup, \
        intervals_to_start_and_ends, \
        filter_pileup_duplicated_position

from examples import *
from scipy.stats import poisson
import offsetbasedgraph as obg


def valued_indexes():
    return ValuedIndexes(np.array([10, 15], dtype="int"),
                         np.array([100, 200]),
                         50,
                         20)


def valued_indexes2():
    return ValuedIndexes(np.array([5, 15, 17], dtype="int"),
                         np.array([60, 210, 190]),
                         40,
                         20)


class TestValuedIndexes(unittest.TestCase):

    def test_max(self):
        vi1 = valued_indexes()
        vi2 = valued_indexes2()
        max_vi = ValuedIndexes.max(vi1, vi2)
        true_max = ValuedIndexes(np.array([5, 10, 15, 17], dtype="int"),
                                 np.array([60, 100, 210, 200]),
                                 50,
                                 20)
        # print(true_max)
        # print(max_vi)
        self.assertEqual(max_vi, true_max)

    def test_threshold(self):
        true_indexes = ValuedIndexes(np.array([15], dtype="int"),
                                     np.array([True], dtype="bool"),
                                     False,
                                     20)
        vi = valued_indexes()
        vi.threshold(150)
        vi.sanitize()
        self.assertEqual(vi, true_indexes)

    def test_set_interval_value_mid(self):
        vi = valued_indexes()
        vi.set_interval_value(10, 15, 150)
        true_vi = valued_indexes()
        true_vi.values[0] = 150
        self.assertEqual(vi, true_vi)

    def test_set_interval_value_start(self):
        vi = valued_indexes()
        vi.set_interval_value(0, 10, 150)
        true_vi = valued_indexes()
        true_vi.start_value = 150
        self.assertEqual(vi, true_vi)

    def test_set_interval_value_end(self):
        vi = valued_indexes()
        vi.set_interval_value(15, 20, 150)
        true_vi = valued_indexes()
        true_vi.values[1] = 150
        self.assertEqual(vi, true_vi)


class TestSparsePileup(unittest.TestCase):
    pass


class TestSparseControlSample(unittest.TestCase):
    def setUp(self):
        control = pileup1_one_block
        sample = pileup2_one_block
        a = control.get_count_array(1)
        a[0] = 3
        self.sparse = SparseControlSample.from_control_and_sample(
            control, sample)

    def test_from_control_and_sample(self):
        true_vi = ValuedIndexes(np.array([1, 5]),
                                np.array([[2., 1.],
                                          [1., 0.]]),
                                np.array([3., 1.]),
                                10)
        self.assertEqual(self.sparse.data[1], true_vi)

    def _test_get_p_dict(self):
        self.sparse.get_p_dict()
        keys = [(2., 1.), (1., 0.), (3., 1.)]
        s_keys = [str(np.array(k)) for k in keys]
        p_values = [-np.log10(1-poisson.cdf(k[1], k[0])) for k in keys]
        true_dict = dict(zip(s_keys, p_values))
        self.assertEqual(self.sparse.p_value_dict,
                         true_dict)

        lens = [4, 5, 1]
        count_dict = dict(zip(p_values, lens))
        self.assertEqual(self.sparse.count_dict,
                         count_dict)

        self.sparse.get_p_to_q_values()
        print("#", self.sparse.p_to_q_values)
        self.sparse.get_q_values()

    def test_starts_and_values_to_sparse_pileup(self):
        starts = np.array([1, 3])
        ends = np.array([5, 10])

        positions, values = starts_and_ends_to_sparse_pileup(starts, ends)

        correct_positions = [1, 3, 5, 10]
        correct_values = [1, 2, 1, 0]

        self.assertTrue(np.all(positions == correct_positions))
        self.assertTrue(np.all(values == correct_values))

    def test_from_intervals(self):
        graph = obg.Graph({1: obg.Block(10), 2: obg.Block(10)}, {1: [2]})
        intervals = [
            obg.Interval(1, 5, [1]),
            obg.Interval(3, 7, [1]),
            obg.Interval(5, 3, [1, 2]),
            obg.Interval(5, 6, [2])
        ]
        pileup = SparsePileup.from_intervals(graph, intervals)
        data = pileup.data
        self.assertEqual(data[1].start_value, False)
        self.assertEqual(data[2].start_value, 1)
        self.assertTrue(np.all([1, 3, 5, 7] == data[1].indexes))
        self.assertTrue(np.all([3, 5, 6] == data[2].indexes))
        self.assertTrue(np.all([1, 2, 2, 1] == data[1].values))
        self.assertTrue(np.all([0, 1, 0] == data[2].values))

    def test_from_intervals2(self):
        graph = obg.Graph({1: obg.Block(10), 2: obg.Block(10), 3: obg.Block(10)}, {1: [2], 2: [3]})
        intervals = [
            obg.Interval(1, 5, [1]),
            obg.Interval(3, 7, [1]),
            obg.Interval(5, 3, [1, 2]),
            obg.Interval(5, 6, [2]),
            obg.Interval(8, 8, [1, 2, 3])
        ]

        pileup = SparsePileup.from_intervals(graph, intervals)
        data = pileup.data
        self.assertEqual(data[1].start_value, False)
        self.assertEqual(data[2].start_value, 2)
        self.assertEqual(data[3].start_value, 1)

        self.assertTrue(np.all([1, 3, 5, 7, 8] == data[1].indexes))
        #print("data 1 values")
        #print(data[2].values)
        self.assertTrue(np.all([1, 2, 2, 1, 2] == data[1].values))

        self.assertTrue(np.all([3, 5, 6] == data[2].indexes))
        self.assertTrue(np.all([1, 2, 1] == data[2].values))

        self.assertTrue(np.all([8] == data[3].indexes))
        self.assertTrue(np.all([0] == data[3].values))


    def test_intervals_to_start_and_ends(self):
        graph = obg.Graph({1: obg.Block(10), 2: obg.Block(10)}, {1: [2]})
        intervals = [
            obg.Interval(1, 5, [1]),
            obg.Interval(3, 7, [1]),
            obg.Interval(5, 3, [1, 2]),
            obg.Interval(5, 6, [2])
        ]

        correct_starts = {1: [1, 3, 5],
                          2: [0, 5]}
        correct_ends = {1: [5, 7, 10], 2: [3, 6]}

        starts, ends = intervals_to_start_and_ends(graph, intervals)
        #print("Starts")
        #print(starts)
        #print("Ends")
        #print(ends)

        for rp in graph.blocks:
            self.assertTrue(np.all(correct_starts[rp] == starts[rp]))
            self.assertTrue(np.all(correct_ends[rp] == ends[rp]))

    def test_filter_pileup_duplicated_position(self):
        positions = np.array([1, 5, 5, 8])
        values = np.array([2, 1, 2, 1])

        filtered_pos, filtered_vals = filter_pileup_duplicated_position(positions, values)

        self.assertTrue(np.all(filtered_pos == np.array([1, 5, 8])))
        self.assertTrue(np.all(filtered_vals == np.array([2, 2, 1])))


if __name__ == "__main__":
    unittest.main()
