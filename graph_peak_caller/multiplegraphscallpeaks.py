import numpy as np
import logging
import offsetbasedgraph as obg
from pyvg.conversion import vg_json_file_to_interval_collection
from . import CallPeaks, Configuration
from .sparsepvalues import PToQValuesMapper
from .sparsediffs import SparseValues
from .intervals import Intervals

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s, %(levelname)s: %(message)s")


class MultipleGraphsCallpeaks:

    def __init__(self, graph_names, graph_file_names,
                 samples,
                 controls, linear_maps,
                 config, reporter,
                 sequence_retrievers=None,
                 save_tmp_results_to_file=False,
                 stop_after_p_values=False,
                 ):
        self._config = config
        self._reporter = reporter
        self.names = graph_names
        self.graph_file_names = graph_file_names
        self.linear_maps = linear_maps
        self.sequence_retrievers = sequence_retrievers
        self.samples = samples
        self.controls = controls
        self.stop_after_p_values = stop_after_p_values
        if self.stop_after_p_values:
            logging.info("Will only run until p-values have been computed.")

    @classmethod
    def count_number_of_unique_reads(cls, sample_reads):
        n_unique = 0
        for reads in sample_reads:
            logging.info("Processing sample")

            interval_hashes = set()
            n_duplicates = 0
            i = 0
            for interval in reads.intervals:
                if i % 20000 == 0:
                    logging.info("%d reads processed" % i)
                i += 1
                hash = interval.hash(ignore_end_pos=True)
                if hash in interval_hashes:
                    n_duplicates += 1
                else:
                    n_unique += 1
                interval_hashes.add(hash)

            print("Found %d duplicates" % n_duplicates)

        logging.info("In total %d unique reads" % n_unique)
        return n_unique

    @classmethod
    def from_file_base_names(cls):
        # Create lists of names, graphs, sample, control linear maps
        pass

    def run(self):
        self.run_to_p_values()
        if self.stop_after_p_values:
            logging.info("Stopping, as planned, after p-values")
            return
        self.create_joined_q_value_mapping()
        self.run_from_p_values()

    def run_to_p_values(self):
        for name, graph_file_name, sample, control, lin_map in \
            zip(self.names, self.graph_file_names,
                self.samples, self.controls, self.linear_maps):
            logging.info("Running %s" % name)
            ob_graph = obg.GraphWithReversals.from_unknown_file_format(
                graph_file_name)
            if isinstance(sample, obg.IntervalCollection) or isinstance(sample, Intervals):
                logging.info("Sample is already intervalcollection.")
            elif sample.endswith(".intervalcollection"):
                sample = obg.IntervalCollection.create_generator_from_file(
                    sample, graph=ob_graph)
                control = obg.IntervalCollection.create_generator_from_file(
                    control, graph=ob_graph)
            else:
                logging.info("Creating interval collections from files")
                sample = vg_json_file_to_interval_collection(sample, ob_graph)
                control = vg_json_file_to_interval_collection(control, ob_graph)

            config = self._config.copy()
            config.linear_map_name = lin_map
            caller = CallPeaks(ob_graph, config,
                               self._reporter.get_sub_reporter(name))
            caller.run_to_p_values(sample, control)
            logging.info("Done until p values.")

    def create_joined_q_value_mapping(self):
        mapper = PToQValuesMapper.from_files(self._reporter._base_name)
        self._q_value_mapping = mapper.get_p_to_q_values()

    def run_from_p_values(self, only_chromosome=None):
        for i, name in enumerate(self.names):
            if only_chromosome is not None:
                if only_chromosome != name:
                    logging.info("Skipping %s" % str(name))
                    continue
            graph_file_name = self.graph_file_names[i]
            ob_graph = obg.GraphWithReversals.from_unknown_file_format(
                graph_file_name)
            assert ob_graph is not None
            caller = CallPeaks(ob_graph, self._config,
                               self._reporter.get_sub_reporter(name))
            caller.p_to_q_values_mapping = self._q_value_mapping
            caller.p_values_pileup = SparseValues.from_sparse_files(
                self._reporter._base_name + name + "_" + "pvalues")
            caller.touched_nodes = set(np.load(
                self._reporter._base_name + name + "_" + "touched_nodes.npy"))
            caller.get_q_values()
            caller.call_peaks_from_q_values()
            if self.sequence_retrievers is not None:
                caller.save_max_path_sequences_to_fasta_file(
                    "sequences.fasta", self.sequence_retrievers.__next__())
