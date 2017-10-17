import logging
import numpy as np

from offsetbasedgraph import IntervalCollection, DirectedInterval
import pyvg as vg
import offsetbasedgraph
from graph_peak_caller import get_shift_size_on_offset_based_graph
from .control import ControlTrack
from .sparsepileup import SparseControlSample, SparsePileup
from .bdgcmp import *
from .extender import Extender
from .areas import ValuedAreas, BinaryContinousAreas
from .peakscores import ScoredPeak
IntervalCollection.interval_class = DirectedInterval


def enable_filewrite(func):
    def wrapper(*args, **kwargs):
        intervals = args[1]
        if isinstance(intervals, str):
            intervals = IntervalCollection.from_file(intervals)

        write_to_file = kwargs.pop("write_to_file", False)
        interval_list = func(args[0], intervals, **kwargs)

        if write_to_file:
            interval_collection = IntervalCollection(interval_list)
            interval_collection.to_file(write_to_file)
            return write_to_file

            with open(write_to_file, "w") as file:
                print("Wrote results to " + str(write_to_file))
                file.writelines(("%s\n" % interval.to_file_line() for interval in interval_list))

            return write_to_file
        else:
            return interval_list

    return wrapper


class ExperimentInfo(object):
    def __init__(self, genome_size, fragment_length, read_length):
        self.genome_size = genome_size
        self.n_sample_reads = 0  # Counters will be modified by Callpeaks
        self.n_control_reads = 0
        self.fragment_length = fragment_length
        self.read_length = read_length

    @classmethod
    def find_info(cls, graph, sample_file_name, control_file_name=None):
        sizes = (block.length() for block in graph.blocks.values())
        genome_size = sum(sizes)

        try:
            print("Finding shift")
            fragment_length, read_length = get_shift_size_on_offset_based_graph(
                graph, sample_file_name)
            print("Found fragment length=%d, read length=%d" % (fragment_length, read_length))
        except RuntimeError:
            print("WARNING: To liptle data to compute shift. Setting to default.")
            fragment_length = 125
            read_length = 20
        return cls(genome_size,
                   fragment_length, read_length)


class CallPeaks(object):
    def __init__(self, graph, sample_intervals,
                 control_intervals=None, experiment_info=None, \
                 verbose=False, out_file_base_name="", has_control=True):
        """
        :param sample_intervals: Either an interval collection or file name
        :param control_intervals: Either an interval collection or a file name
        """

        assert isinstance(sample_intervals, IntervalCollection) \
               or isinstance(sample_intervals, str), \
                "Samples intervals must be either interval collection or a file name"

        assert isinstance(control_intervals, IntervalCollection) \
               or isinstance(control_intervals, str), \
                "control_intervals must be either interval collection or a file name"

        self.graph = graph

        self.sample_intervals = sample_intervals
        self.control_intervals = control_intervals
        self.has_control = has_control

        self._p_value_track = "p_value_track"
        self._q_value_track = "q_value_track"
        self.info = experiment_info
        self.verbose = verbose
        self._control_pileup = None
        self._sample_pileup = None
        self.out_file_base_name = out_file_base_name

    def run(self, out_file="final_peaks"):
        self.create_graph()
        self.preprocess()
        if self.info is None:
            self.info = ExperimentInfo.find_info(
                self.ob_graph, self.sample_intervals, self.control_intervals)
        self.create_control(True)
        self.create_sample_pileup()
        self.scale_tracks()
        self.get_score()
        # self.get_p_values()
        # self.get_q_values()
        self.call_peaks(out_file)

    def preprocess(self):
        self.sample_intervals = self.remove_alignments_not_in_graph(
                                    self.sample_intervals)
        self.sample_intervals = self.filter_duplicates_and_count_intervals(
                                    self.sample_intervals, is_control=False)

        self.control_intervals = self.remove_alignments_not_in_graph(
                                    self.control_intervals, is_control=True)
        self.control_intervals = self.filter_duplicates_and_count_intervals(
                                    self.control_intervals, is_control=True)

    @enable_filewrite
    def remove_alignments_not_in_graph(self, intervals, is_control=False):
        for interval in self._get_intervals_in_ob_graph(intervals):
            if interval is not False:
                yield interval

    @enable_filewrite
    def filter_duplicates_and_count_intervals(self, intervals, is_control=False):
        interval_hashes = {}
        n_duplicates = 0
        n_reads_left = 0
        for interval in intervals:
            hash = interval.hash()
            if hash in interval_hashes:
                n_duplicates += 1
                continue

            interval_hashes[hash] = True
            if is_control:
                self.info.n_control_reads += 1
            else:
                self.info.n_sample_reads += 1

            yield interval

    def _get_intervals_in_ob_graph(self, intervals):
        # Returns only those intervals that exist in graph
        for interval in intervals:
            if interval.region_paths[0] in self.ob_graph.blocks:
                yield interval
            else:
                yield False

    def scale_tracks(self, update_saved_files=False):
        print("Scaling tracks to ratio: %d / %d" % (self.info.n_sample_reads, self.info.n_control_reads))
        ratio = self.info.n_sample_reads/self.info.n_control_reads

        if self.info.n_sample_reads == self.info.n_control_reads:
            return

        if ratio > 1:
            self._sample_pileup.scale(1/ratio)
            if update_saved_files:
                self._sample_pileup.to_bed_graph(self._sample_track)
        else:
            self._control_pileup.scale(ratio)
            if update_saved_files:
                self._control_pileup.to_bed_graph(self._control_track)

    def find_info(self):
        genome_size = 0
        sizes = (block.length() for block in self.ob_graph.blocks.values())

        self.genome_size = sum(sizes)
        self.n_reads = sum(1 for line in open(self.control_file_name))

    def create_graph(self):
        if self.verbose:
            print("Creating graph")
        if isinstance(self.graph, str):
            self.ob_graph = offsetbasedgraph.Graph.from_file(self.graph)
        else:
            self.ob_graph = self.graph
            if self.verbose:
                print("Graph already created")

    def create_control(self, save_to_file=True):
        if self.verbose:
            print("Creating control")
        extensions = [self.info.fragment_length, 2500, 5000] if self.has_control else [5000]

        control_track = ControlTrack(
            self.ob_graph, self.control_intervals,
            self.info.fragment_length, extensions)

        print("N control reads: %d" % self.info.n_control_reads)

        tracks = control_track.generate_background_tracks()
        background_value = self.info.n_control_reads*self.info.fragment_length/self.info.genome_size
        logging.warning(background_value)
        pileup = control_track.combine_backgrounds(tracks, background_value)

        if save_to_file:
            self._control_track = self.out_file_base_name + "control_track.bdg"
            pileup.to_bed_graph(self._control_track)
            print("Saved control pileup to " + self._control_track)

        self._control_pileup = pileup

    def get_q_values(self):
        get_q_values_track_from_p_values(self.p_values)

    def get_score(self):
        sparse_pileup = SparseControlSample.from_sparse_control_and_sample(
            self._control_pileup, self._sample_pileup)
        sparse_pileup.get_scores()
        self.p_values = sparse_pileup
        self.q_values = sparse_pileup
        self.q_values.to_bed_graph(self.out_file_base_name + "q_values.bdg")

    def get_p_values(self):
        print("Get p-values")
        self.p_values = get_p_value_track_from_pileups(
            self.ob_graph, self._control_pileup, self._sample_pileup)

    def call_peaks(self, out_file="final_peaks.bed", cutoff=0.05):
        print("Calling peaks")
        self.peaks = self.p_values.threshold_copy(-np.log10(cutoff))
        # self.p_values.threshold(-np.log10(cutoff))
        self.peaks.to_bed_file("pre_postprocess.bed")
        self.peaks.fill_small_wholes(self.info.read_length)
        self.final_track = self.peaks.remove_small_peaks(
            self.info.fragment_length)
        print("Final track")
        peaks_as_subgraphs = self.final_track.to_subgraphs()
        peaks_as_subgraphs.to_file(
            self.out_file_base_name + "peaks_as_subgraphs")

        binary_peaks = (BinaryContinousAreas.from_old_areas(peak) for peak in
                        peaks_as_subgraphs)
        scored_peaks = (ScoredPeak.from_peak_and_pileup(peak, self.p_values)
                        for peak in binary_peaks)
        max_paths = [scored_peak.get_max_path() for
                     scored_peak in scored_peaks]
        IntervalCollection(max_paths).to_text_file(
            self.out_file_base_name + "max_paths")
        self.max_paths = max_paths
        print("Number of subgraphs: %d" % len(peaks_as_subgraphs.subgraphs))
        self.final_track.to_bed_file(self.out_file_base_name + out_file)

    def create_sample_pileup(self, save_to_file=True):
        logging.debug("In sample pileup")
        if self.verbose:
            print("Create sample pileup")
        alignments = self.sample_intervals
        logging.debug(self.sample_intervals)
        extender = Extender(self.ob_graph, self.info.fragment_length)
        valued_areas = ValuedAreas(self.ob_graph)
        areas_list = (extender.extend_interval(interval)
                      for interval in alignments)
        for area in areas_list:
            valued_areas.add_binary_areas(area)
        pileup = SparsePileup.from_valued_areas(
            self.ob_graph, valued_areas)
        self._sample_track = self.out_file_base_name + "sample_track.bdg"
        if save_to_file:
            pileup.to_bed_graph(self._sample_track)
            print("Saved sample pileup to " + self._sample_track)

        self._sample_pileup = pileup

    def _write_vg_alignments_as_intervals_to_bed_file(self):
        pass


if __name__ == "__main__":
    chromosome = "chr2R"
    vg_graph = vg.Graph.create_from_file(
        "dm_test_data/x_%s.json" % chromosome, 30000, chromosome)
    ofbg = vg_graph.get_offset_based_graph()
    interval_file = vg.util.vg_mapping_file_to_interval_file(
        "intervals_reads3_chr2R", vg_graph,
        "dm_test_data/reads3_small.json", ofbg)
    ofbg.to_file("graph.tmp")

    caller = CallPeaks("graph.tmp", interval_file)
    caller.create_graph()
    caller.find_info()
    caller.determine_shift()
    caller.sample_file_name = caller.remove_alignments_not_in_graph(
        caller.sample_file_name)
    caller.sample_file_name = caller.filter_duplicates(caller.sample_file_name)
