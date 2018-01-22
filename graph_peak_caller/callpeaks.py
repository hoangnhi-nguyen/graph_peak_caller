import logging
import numpy as np
import pickle
from offsetbasedgraph import IntervalCollection, DirectedInterval
import pyvg as vg
import offsetbasedgraph
from graph_peak_caller import get_shift_size_on_offset_based_graph
#from .sparsepileupv2 import SparseControlSample
#from .sparsepileupv2 import SparsePileup
from .densepileup import DensePileup, DenseControlSample, QValuesFinder

from .extender import Extender
from .areas import ValuedAreas, BinaryContinousAreas, BCACollection
from .peakscores import ScoredPeak
from .peakcollection import PeakCollection
from . import linearsnarls
IntervalCollection.interval_class = DirectedInterval
from .subgraphcollection import SubgraphCollectionPartiallyOrderedGraph
from .peakcollection import Peak
from memory_profiler import profile

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
                file.writelines(("%s\n" % interval.to_file_line()
                                 for interval in interval_list))

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

    def to_file(self, file_name):
        with open("%s" % file_name, "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def from_file(cls, file_name):
        with open("%s" % file_name, "rb") as f:
            data = pickle.loads(f.read())
            return data


class CallPeaksFromQvalues(object):
    def __init__(self, graph, q_values_sparse_pileup,
                 experiment_info, out_file_base_name="",
                 cutoff=0.1, raw_pileup=None, touched_nodes=None,
                 graph_is_partially_ordered=False,
                 save_tmp_results_to_file=True):
        self.graph = graph
        self.q_values = q_values_sparse_pileup
        self.info = experiment_info
        self.out_file_base_name = out_file_base_name
        self.cutoff = cutoff
        self.raw_pileup = raw_pileup
        #self.graph.assert_correct_edge_dicts()
        self.touched_nodes = touched_nodes
        self.graph_is_partially_ordered = graph_is_partially_ordered
        self.save_tmp_results_to_file = save_tmp_results_to_file

        self.info.to_file(self.out_file_base_name + "experiment_info.pickle")

    def __threshold(self):
        threshold = -np.log10(self.cutoff)
        logging.info("Thresholding peaks on q value %.4f" % threshold)
        self.pre_processed_peaks = self.q_values.threshold_copy(threshold)

        if self.save_tmp_results_to_file:
            self.pre_processed_peaks.to_bed_file(
                self.out_file_base_name + "pre_postprocess.bed")

    def __postprocess(self):
        logging.info("Filling small Holes")

        if isinstance(self.pre_processed_peaks, DensePileup):
            self.pre_processed_peaks.fill_small_wholes_on_dag(
                                    self.info.read_length)
        else:
            self.pre_processed_peaks.fill_small_wholes(
                                    self.info.read_length,
                                    self.out_file_base_name + "_holes.intervals",
                                    touched_nodes=self.touched_nodes)

        logging.info("Removing small peaks")

        # This is slow:
        #self.pre_processed_peaks.to_bed_file(
        #    self.out_file_base_name + "_before_small_peaks_removal.bed")
        #logging.info("Preprocessed peaks written to bed file")


        if isinstance(self.pre_processed_peaks, DensePileup):
            # If dense pileup, we are filtering small peaks while trimming later
            self.filtered_peaks = self.pre_processed_peaks
        else:
            self.filtered_peaks = self.pre_processed_peaks.remove_small_peaks(
                self.info.fragment_length)
        logging.info("Small peaks removed")

    def trim_max_path_intervals(self, intervals, end_to_trim=-1):
        # Right trim max path intervals, remove right end where q values are 0
        # If last base pair in interval has 0 in p-value, remove hole size
        logging.info("Trimming max path intervals. End: %d" % end_to_trim)
        new_intervals = []
        n_intervals_trimmed = 0
        for interval in intervals:
            if np.all([rp < 0 for rp in interval.region_paths]):
                use_interval = interval.get_reverse()
                use_interval.score = interval.score
            else:
                use_interval = interval
                assert np.all([rp > 0 for rp in interval.region_paths]), \
                "This method only supports intervals with single rp direction"

            pileup_values = self.q_values.data.get_interval_values(use_interval)
            assert len(pileup_values) == use_interval.length()

            if end_to_trim == 1:
                pileup_values = pileup_values[::-1]

            cumsum = np.cumsum(pileup_values)
            n_zeros_beginning = np.sum(cumsum == 0)

            if end_to_trim == -1:
                new_interval = use_interval.get_subinterval(n_zeros_beginning, use_interval.length())
            else:
                new_interval = use_interval.get_subinterval(0, use_interval.length() - n_zeros_beginning)

            if new_interval.length() != use_interval.length():
                n_intervals_trimmed += 1
                #print("Trimmed interval into: ")
                #print("   %s" % interval)
                #print("   %s" % new_interval)

            new_interval.score = use_interval.score

            if new_interval.length() < self.info.fragment_length:
                #print("Not keeping too short interval: %s" % new_interval)
                continue
            new_interval = Peak(new_interval.start_position,
                                new_interval.end_position,
                                new_interval.region_paths,
                                new_interval.graph,
                                score=use_interval.score)

            new_intervals.append(new_interval)

        logging.info("Trimmed in total %d intervals" % n_intervals_trimmed)
        logging.info("N intervals left: %d" % len(new_intervals))
        return new_intervals

    def __get_max_paths(self):
        logging.info("Getting maxpaths")
        _pileup = self.raw_pileup if self.raw_pileup is not None else self.q_values
        scored_peaks = (ScoredPeak.from_peak_and_numpy_pileup(peak, _pileup)
                        for peak in self.binary_peaks)
        max_paths = [peak.get_max_path() for peak in scored_peaks]

        max_paths.sort(key=lambda p: p.score, reverse=True)

        if isinstance(self.q_values, DensePileup):
            max_paths = self.trim_max_path_intervals(max_paths, end_to_trim=-1)
            max_paths = self.trim_max_path_intervals(max_paths, end_to_trim=1)


        PeakCollection(max_paths).to_file(
            self.out_file_base_name + "max_paths.intervalcollection",
            text_file=True)
        logging.info("Wrote max paths to file")

        self.max_paths = max_paths

    def __get_subgraphs(self):

        if not self.graph_is_partially_ordered:
            logging.info("Creating subgraphs from peak regions")
            peaks_as_subgraphs = self.filtered_peaks.to_subgraphs()
            logging.info("Writing subgraphs to file")
            peaks_as_subgraphs.to_file(self.out_file_base_name + "peaks.subgraphs")

            logging.info("Found %d subgraphs" % len(peaks_as_subgraphs.subgraphs))
            binary_peaks = [BinaryContinousAreas.from_old_areas(peak) for peak in
                            peaks_as_subgraphs]
            logging.info("Finding max path through subgraphs")
            BCACollection(binary_peaks).to_file(
                self.out_file_base_name + "bcapeaks.subgraphs")
            self.binary_peaks = binary_peaks
        else:
            logging.info("Assuming graph is partially ordered!")
            logging.info("Creating subgraphs from peak regions")
            peaks_as_subgraphs = \
                SubgraphCollectionPartiallyOrderedGraph.create_from_pileup(self.graph, self.filtered_peaks)
            #logging.info("Writing subgraphs to file")
            #peaks_as_subgraphs.to_file(self.out_file_base_name + "peaks.subgraphs")

            logging.info("Found %d subgraphs" % len(peaks_as_subgraphs))
            binary_peaks = peaks_as_subgraphs

            if self.save_tmp_results_to_file:
                logging.info("Writing binary continous peaks to file")
                BCACollection(binary_peaks).to_file(
                    self.out_file_base_name + "bcapeaks.subgraphs")
            self.binary_peaks = binary_peaks

    def callpeaks(self):
        logging.info("Calling peaks")
        self.__threshold()
        self.__postprocess()
        self.__get_subgraphs()
        self.filtered_peaks.to_bed_file(
            self.out_file_base_name + "final_peaks.bed")
        self.__get_max_paths()

    def save_max_path_sequences_to_fasta_file(self, file_name, sequence_retriever):
        assert self.max_paths is not None, \
                "Max paths has not been found. Run peak calling first."
        assert sequence_retriever is not None
        # assert isinstance(sequence_retriever, vg.sequences.SequenceRetriever)
        f = open(self.out_file_base_name + file_name, "w")
        i = 0
        for max_path in self.max_paths:
            seq = sequence_retriever.get_interval_sequence(max_path)
            f.write(">peak" + str(i) + " " +
                    max_path.to_file_line() + "\n" + seq + "\n")
            i += 1
        f.close()
        logging.info("Wrote max path sequences to fasta file: %s" % (self.out_file_base_name + file_name))

    @staticmethod
    def intervals_to_fasta_file(interval_collection, out_fasta_file_name, sequence_retriever):
        f = open(out_fasta_file_name, "w")
        i = 0
        for max_path in interval_collection.intervals:
            seq = sequence_retriever.get_interval_sequence(max_path)
            f.write(">peak" + str(i) + " " +
                    max_path.to_file_line() + "\n" + seq + "\n")
            i += 1
            if i % 100 == 0:
                logging.info("Writing sequence # %d" % i)
        f.close()


class CallPeaks(object):
    def __init__(self, graph, sample_intervals,
                 control_intervals=None, experiment_info=None,
                 verbose=False, out_file_base_name="", has_control=True,
                 linear_map=None, skip_filter_duplicates=False,
                 graph_is_partially_ordered=False,
                 skip_read_validation=False,
                 save_tmp_results_to_file=True):
        """
        :param sample_intervals: Either an interval collection or file name
        :param control_intervals: Either an interval collection or a file name
        """

        assert linear_map is not None, "LinearMap cannot be None"
        assert isinstance(linear_map, str), "Must be file name"

        assert isinstance(sample_intervals, IntervalCollection) \
               or isinstance(sample_intervals, str), \
                "Samples intervals must be either interval collection or a file name"

        assert isinstance(control_intervals, IntervalCollection) \
               or isinstance(control_intervals, str), \
                "control_intervals must be either interval collection or a file name"

        if not has_control:
            logging.info("Running without control")
        else:
            logging.info("Running with control")

        self.graph = graph

        self.sample_intervals = sample_intervals
        self.control_intervals = control_intervals
        self.has_control = has_control
        self.linear_map = linear_map

        self._p_value_track = "p_value_track"
        self._q_value_track = "q_value_track"
        self.info = experiment_info
        self.verbose = verbose
        self._control_pileup = None
        self._sample_pileup = None
        self.out_file_base_name = out_file_base_name
        self.cutoff = 0.05
        self.pre_processed_peaks = None
        self.filtered_peaks = None
        self.skip_filter_duplicates = skip_filter_duplicates
        self.skip_read_validation = skip_read_validation
        self.save_tmp_results_to_file = save_tmp_results_to_file

        self.max_paths = None
        self.peaks_as_subgraphs = None

        if self.skip_filter_duplicates:
            logging.info("Not removing duplicates")

        self.create_graph()
        self.touched_nodes = None  # Nodes touched by sample pileup
        self.graph_is_partially_ordered = graph_is_partially_ordered

    def set_cutoff(self, value):
        self.cutoff = value

    def run(self, out_file="final_peaks.bed"):
        self.run_pre_call_peaks_steps()
        self.call_peaks()

    def run_pre_call_peaks_steps(self):
        self.preprocess()
        if self.info is None:
            self.info = ExperimentInfo.find_info(
                self.ob_graph, self.sample_intervals, self.control_intervals)
        self.create_sample_pileup()

        self.create_control()
        self.scale_tracks()
        self.get_score()

    def preprocess(self):
        self.info.n_control_reads = 0
        self.info.n_sample_reads = 0

        if not self.skip_read_validation:
            self.sample_intervals = self.remove_alignments_not_in_graph(
                                        self.sample_intervals)
        else:
            logging.warning("Skipping validation of reads. Not checking whether reads are valid"
                            " or inside the graph.")

        self.sample_intervals = self.filter_duplicates_and_count_intervals(
                                    self.sample_intervals, is_control=False)

        if not self.skip_read_validation:
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
            if not self.skip_filter_duplicates:
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

    def _assert_interval_is_valid(self, interval):
        #print("Checking that %s is valid" % interval)
        # Checks that the interval (read) is a valid connected interval
        direction = None
        for i, rp in enumerate(interval.region_paths[:-1]):
            next_rp = interval.region_paths[i+1]
            if next_rp in self.ob_graph.adj_list[rp]:
                new_dir = 1
            elif next_rp in self.ob_graph.reverse_adj_list[rp]:
                new_dir = -1
            else:
                logging.error("Invalid interval: Rp %d of interval %s is not "
                              "connected in graph to rp %d, which is the next rp"
                              % (rp, interval, next_rp))
                raise Exception("Invalid interval")

            if direction is None:
                direction = new_dir
            else:
                if new_dir != direction:
                    logging.error("Invalid read: Interval %s is going edges in multiple directions.")
                    raise Exception("Invalid interval")

            #print("  Dir: %d " % direction)
        return True

    def _get_intervals_in_ob_graph(self, intervals):
        # Returns only those intervals that exist in graph
        for interval in intervals:
            self._assert_interval_is_valid(interval)
            if interval.region_paths[0] in self.ob_graph.blocks:
                yield interval
            else:
                logging.warning("Interval: %s" % interval)
                raise Exception("Interval not in graph")

    def scale_tracks(self, update_saved_files=False):
        logging.info("Scaling tracks to ratio: %d / %d" % (self.info.n_sample_reads,
                                                    self.info.n_control_reads))
        ratio = self.info.n_sample_reads/self.info.n_control_reads

        if self.info.n_sample_reads == self.info.n_control_reads:
            logging.info("Not scaling any tracks because of same amount of reads")
            self._control_pileup.to_bed_graph(
                self.out_file_base_name + "scaled_control.bdg")
            return

        if ratio > 1:
            logging.warning("More reads in sample than in control")
            self._sample_pileup.scale(1/ratio)
            self._sample_pileup.to_bed_graph(
                self.out_file_base_name + "scaled_treat.bdg")
            if update_saved_files:
                self._sample_pileup.to_bed_graph(self._sample_track)
        else:
            logging.info("Scaling control pileup down using ration %.3f" % ratio)
            self._control_pileup.scale(ratio)
            self._control_pileup.to_bed_graph(
                self.out_file_base_name + "scaled_control.bdg")
            if update_saved_files:
                self._control_pileup.to_bed_graph(self._control_track)

    def find_info(self):
        sizes = (block.length() for block in self.ob_graph.blocks.values())

        self.genome_size = sum(sizes)
        self.n_reads = sum(1 for line in open(self.control_file_name))

    def create_graph(self):
        logging.info("Creating graph")
        if isinstance(self.graph, str):
            self.ob_graph = offsetbasedgraph.Graph.from_file(self.graph)
        else:
            self.ob_graph = self.graph
            logging.info("Graph already created")

    def create_control(self):
        logging.info("Creating control track using linear map %s" % self.linear_map)
        extensions = [self.info.fragment_length, 1000, 10000] if self.has_control else [10000]
        control_pileup = linearsnarls.create_control(
            self.linear_map,  self.control_intervals,
            extensions, self.info.fragment_length,
            ob_graph=self.graph,
            touched_nodes=self.touched_nodes
        )

        # Delete linear map
        self.linear_map = None

        control_pileup.graph = self.ob_graph
        logging.info("Number of control reads: %d" % self.info.n_control_reads)

        if self.save_tmp_results_to_file:
            self._control_track = self.out_file_base_name + "control_track.bdg"
            control_pileup.to_bed_graph(self._control_track)
            logging.info("Saved control pileup to " + self._control_track)

        self._control_pileup = control_pileup

        # Delete control pileup
        self.control_intervals = None

    def get_score(self):
        logging.info("Getting scores. Creating sparse array from sparse control and sample")
        #q_values_pileup = DenseControlSample.from_sparse_control_and_sample(
        #    self._control_pileup, self._sample_pileup)

        q_values_finder = QValuesFinder(self._sample_pileup, self._control_pileup)
        q_values_pileup = q_values_finder.get_q_values_pileup()


        # Delete sample and control pileups
        self._control_pileup = None
        self._sample_pileup = None

        #logging.info("Computing q values")
        #q_values_pileup.get_scores()
        self.q_values = q_values_pileup

        if self.save_tmp_results_to_file:
            q_val_file_name = self.out_file_base_name + "q_values.bdg"
            logging.info("Writing q values to file")
            self.q_values.to_bed_graph(q_val_file_name)
            logging.info("Writing q values to pickle")
            self.q_values.to_pickle(self.out_file_base_name + "q_values.pickle")

    def call_peaks(self):
        self.q_value_peak_caller = CallPeaksFromQvalues(
            self.graph,
            self.q_values,
            self.info,
            self.out_file_base_name,
            self.cutoff,
            touched_nodes=self.touched_nodes,
            graph_is_partially_ordered=self.graph_is_partially_ordered,
            save_tmp_results_to_file=self.save_tmp_results_to_file
        )
        self.q_value_peak_caller.callpeaks()

    def save_max_path_sequences_to_fasta_file(self, file_name, retriever):
        self.q_value_peak_caller.\
            save_max_path_sequences_to_fasta_file(file_name, retriever)

    #@profile
    def create_sample_pileup(self):
        logging.debug("In sample pileup")
        logging.info("Creating sample pileup")
        alignments = self.sample_intervals
        logging.info(self.sample_intervals)
        extender = Extender(self.ob_graph, self.info.fragment_length)
        valued_areas = ValuedAreas(self.ob_graph)
        logging.info("Extending sample reads")
        areas_list = (extender.extend_interval(interval)
                      for interval in alignments)
        i = 0
        logging.info("Processing areas")

        #touched_nodes = set()  # Speedup thing, keep track of nodes where areas are on
        pileup = DensePileup.create_from_binary_continous_areas(
                    self.ob_graph, areas_list)
        touched_nodes = pileup.data._touched_nodes
        self.touched_nodes = touched_nodes



        self._sample_track = self.out_file_base_name + "sample_track.bdg"
        if self.save_tmp_results_to_file:
            logging.info("Saving sample pileup to file")
            pileup.to_bed_graph(self._sample_track)
            logging.info("Saved sample pileup to " + self._sample_track)

            logging.info("Writing touched nodes to file")
            with open(self.out_file_base_name + "touched_nodes.pickle", "wb") as f:
                pickle.dump(touched_nodes, f)

            logging.info("N touched nodes: %d" % len(touched_nodes))

        self._sample_pileup = pileup

        # Delete sample intervals
        self.sample_intervals = None

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
