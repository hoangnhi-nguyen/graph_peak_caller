from .densepileup import DensePileup
from .samplepileup import PileupCreator, ReversePileupCreator
import numpy as np


class DirectPileup:
    def __init__(self, graph, intervals, pileup):
        self._graph = graph
        self._intervals = intervals
        self._pileup = pileup
        self._pos_ends = {node_id: [] for node_id in self._graph.blocks.keys()}
        self._neg_ends = {-node_id: [] for node_id in self._graph.blocks.keys()}

    def _handle_interval(self, interval):
        self._pileup.add_interval(interval)
        end_pos = interval.end_position
        rp = end_pos.region_path_id
        if rp < 0:
            self._neg_ends[rp].append(end_pos.offset)
        else:
            self._pos_ends[rp].append(end_pos.offset)

    def run(self):
        for interval in self._intervals:
            self._handle_interval(interval)


class Starts:
    def __init__(self, d):
        self._dict = d

    def get_node_starts(self, node_id):
        return np.array(self._dict[node_id])


def main(intervals, graph, extension_size):
    pileup = DensePileup(graph)
    direct_pileup = DirectPileup(graph, intervals, pileup)
    direct_pileup.run()
    print(len(pileup.data._touched_nodes))
    pileup_neg = np.zeros_like(pileup.data._values)
    creator = ReversePileupCreator(
        graph, Starts(direct_pileup._neg_ends),
        pileup_neg, pileup.data._touched_nodes)
    creator._fragment_length = extension_size
    creator.run_linear()
    print(len(pileup.data._touched_nodes))
    pileup.data._values += creator._pileup[::-1]
    del pileup_neg
    extension_pileup = np.zeros_like(pileup.data._values)
    creator = PileupCreator(
        graph, Starts(direct_pileup._pos_ends), extension_pileup,
        pileup.data._touched_nodes)
    creator._fragment_length = extension_size
    creator.run_linear()
    print(len(pileup.data._touched_nodes))
    pileup.data._values += creator._pileup
    # for node_id in graph.get_sorted_node_ids():
    #     if np.sum(pileup.data.values(node_id)):
    #         pileup.data._touched_nodes.add(node_id)
    return pileup
