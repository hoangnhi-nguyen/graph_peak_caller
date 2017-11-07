from collections import deque, defaultdict
import offsetbasedgraph as obg
import numpy as np


class ScoredPeak(object):
    def __init__(self, peak, scores):
        self._peak = peak
        self._scores = scores
        self._graph = peak.graph

    def __eq__(self, other):
        if self._peak != other._peak:
            return False
        if self._scores == other._scores:
            return True
        return False

    @staticmethod
    def _from_valued_indexes(valued_indexes, start, end):
        return valued_indexes.get_subset(start, end)

    @classmethod
    def from_peak_and_pileup(cls, peak, pileup):
        scores = {}
        for node_id in peak.full_areas:
            valued_indexes = pileup.data[node_id]
            node_scores = cls._from_valued_indexes(
                valued_indexes, 0, valued_indexes.length)
            scores[node_id] = node_scores

        for node_id, start in peak.starts.items():
            valued_indexes = pileup.data[abs(node_id)]
            if node_id < 0:
                length = valued_indexes.length
                node_scores = cls._from_valued_indexes(
                    valued_indexes, length-start, length)
            else:
                node_scores = cls._from_valued_indexes(
                    valued_indexes, 0, start)
            scores[node_id] = node_scores

        for node_id, startend in peak.internal_intervals.items():
            valued_indexes = pileup.data[abs(node_id)]
            node_scores = cls._from_valued_indexes(
                valued_indexes, startend[0], startend[1])
            scores[node_id] = node_scores
        return cls(peak, scores)

    def __str__(self):
        return "\n".join("%s: %s" % (node_id, vi) for
                         node_id, vi in self._scores.items())
        return str(self._scores)

    __repr__ = __str__

    def _get_adj_list(self):
        starts = self._peak.starts.keys()
        ends = [-node_id for node_id in self._peak.starts.keys()]
        fulls = list(self._peak.full_areas.keys())
        adj_list = {node_id:
                    [next_node for next_node in self._graph.adj_list[node_id]
                     if abs(next_node) in fulls or next_node in starts]
                    for node_id in ends+fulls+[-n for n in fulls]}
        d_adj_list = defaultdict(list)
        d_adj_list.update(adj_list)
        return d_adj_list

    @staticmethod
    def __clean_sums(sums):
        values = [s for s in sums.values() if s != np.inf]
        if len(values) > 0:
            max_finite_value = max(values)
        else:
            max_finite_value = 100

        for node_id, sum_value in sums.items():
            if sum_value == np.inf:
                sums[node_id] = max_finite_value+1

    def get_max_path(self):
        # Handle peaks that are on one node
        if len(self._peak.internal_intervals) > 0:
            node, start_end = list(self._peak.internal_intervals.items())[0]
            return obg.DirectedInterval(start_end[0], start_end[1],
                                        [node], graph=self._graph)

        sums = {node_id: float(vi.sum()) for node_id, vi
                in self._scores.items()}

        self.__clean_sums(sums)
        for key in list(sums.keys()):
            if key in self._peak.full_areas:
                sums[-key] = sums[key]

        adj_list = self._get_adj_list()
        ends = [-node_id for node_id in self._peak.starts.keys()]
        start_values = [sums[-node_id] for node_id in ends]
        ends.extend(self._peak.full_areas.keys())
        start_values.extend(sums[abs(node_id)] for
                            node_id in self._peak.full_areas.keys())
        ends.extend(-node_id for node_id in self._peak.full_areas.keys())
        start_values.extend(sums[abs(node_id)] for
                            node_id in self._peak.full_areas.keys())

        memo = defaultdict(int)
        stack = deque(zip([[e] for e in ends], start_values))
        assert stack, str(self._peak)
        global_max = 0
        global_max_path = None
        while stack:
            node_ids, value = stack.popleft()
            if memo[node_ids[-1]] >= value:
                continue
            if value > global_max:
                global_max_path = node_ids
                global_max = value

            memo[node_ids[-1]] = value
            nexts = adj_list[node_ids[-1]]
            new_items = [(node_ids+[next_node], value+sums[next_node])
                         for next_node in nexts
                         if next_node not in node_ids[1:] and next_node in sums]
            stack.extend(new_items)

        start_node = global_max_path[0]
        start_offset = int(self._graph.node_size(start_node) -
                           self._peak.starts[-start_node])
        end_offset = self._peak.starts[global_max_path[-1]]
        return obg.DirectedInterval(
            int(start_offset), int(end_offset),
            global_max_path, graph=self._graph)
