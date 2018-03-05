import unittest
from graph_peak_caller.peakcollection import Peak, PeakCollection
from graph_peak_caller.nongraphpeaks import NonGraphPeak, NonGraphPeakCollection
from offsetbasedgraph import GraphWithReversals as Graph, Block, DirectedInterval as Interval
from graph_peak_caller.analyse_peaks import LinearRegion


class TestPeakCollection(unittest.TestCase):

    def test_approx_contains(self):

        peaks = PeakCollection(
            [
                Peak(3, 3, [1, 2, 3, 4]),
                Peak(3, 3, [-10, 11])
            ]
        )
        peaks.create_node_index()

        self.assertTrue(peaks.approx_contains_part_of_interval(
            Peak(1, 2, [1])
        ))

        self.assertTrue(peaks.approx_contains_part_of_interval(
            Peak(1, 2, [10])
        ))

        self.assertFalse(peaks.approx_contains_part_of_interval(
            Peak(1, 2, [100])
        ))

    def test_create_from_nongraphpeakcollection(self):

        graph = Graph(
            {1: Block(10), 2: Block(10), 3: Block(10)},
            {1: [2], 2:[3]}
        )
        graph.convert_to_numpy_backend()
        linear_path = Interval(0, 10, [1, 2, 3], graph)
        linear_path = linear_path.to_numpy_indexed_interval()

        nongraph_peaks = NonGraphPeakCollection(
            [
                NonGraphPeak("chr1", 3, 10, 5),
                NonGraphPeak("chr1", 13, 15, 7),
            ]
        )

        peaks = PeakCollection.create_from_nongraph_peak_collection(
            graph, nongraph_peaks, linear_path, None
        )

        self.assertEqual(
            peaks.intervals[0], Interval(3, 10, [1])
        )
        self.assertEqual(
            peaks.intervals[1], Interval(3, 5, [2])
        )

        peaks = PeakCollection.create_from_nongraph_peak_collection(
            graph, nongraph_peaks, linear_path, LinearRegion("chr1", 3, 20)
        )
        self.assertEqual(
            peaks.intervals[0], Interval(0, 7, [1])
        )
        self.assertEqual(
            peaks.intervals[1], Interval(0, 2, [2])
        )

    def test_convert_to_approx_linear_peaks(self):
        graph = Graph({i: Block(3) for i in range(1, 10)},
                      {1: [2],
                       2: [3],
                       3: [4],
                       4: [5],
                       5: [6],
                       6: [7, 8],
                       7: [9],
                       9: [9]})
        graph.convert_to_numpy_backend()
        linear_interval = Interval(0, 3, [2, 4, 8, 9], graph)
        linear_interval = linear_interval.to_numpy_indexed_interval()

        peaks = PeakCollection(
            [
                Peak(2, 2, [2, 3, 4]),
                Peak(1, 1, [3, 4, 5])
            ]
        )
        linear_peaks = peaks.to_approx_linear_peaks(linear_interval, "chr4")
        linear_peaks = linear_peaks.peaks
        print(linear_peaks)

        self.assertEqual(linear_peaks[0], NonGraphPeak("chr4", 2, 5))
        self.assertEqual(linear_peaks[1], NonGraphPeak("chr4", 3, 3))



if __name__ == "__main__":
    unittest.main()