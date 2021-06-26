import random
import sys
import os
import itertools

import pickle

from qmla.exploration_strategies.nv_centre_spin_characterisation import (
    nv_centre_full_access,
)
import qmla.shared_functionality.qinfer_model_interface
import qmla.shared_functionality.probe_set_generation
import qmla.shared_functionality.experiment_design_heuristics
import qmla.shared_functionality.expectation_value_functions
import qmla.shared_functionality.latex_model_names
from qmla import model_building_utilities


class ExperimentNVCentreNQubits(nv_centre_full_access.FullAccessNVCentre):
    def __init__(self, exploration_rules, **kwargs):
        super().__init__(exploration_rules=exploration_rules, **kwargs)

        self.true_model = qmla.utilities.n_qubit_nv_gali_model(
            n_qubits=2, coupling_terms=["z"]
        )
        self.max_num_qubits = 4

        self.true_model = qmla.model_building_utilities.alph(self.true_model)
        self.initial_models = [
            qmla.utilities.n_qubit_nv_gali_model(n, coupling_terms=["z"])
            for n in range(2, 1 + self.max_num_qubits)
        ]
        self.qhl_models = self.initial_models

        # probes
        self.system_probes_generation_subroutine = (
            qmla.shared_functionality.probe_set_generation.plus_plus_with_phase_difference
        )
        self.simulator_probes_generation_subroutine = (
            self.system_probes_generation_subroutine
        )
        self.shared_probes = False
        self.max_num_probe_qubits = self.max_num_qubits

        # experiment design and running
        self.expectation_value_subroutine = (
            qmla.shared_functionality.expectation_value_functions.n_qubit_hahn_evolution_double_time_reverse
        )
        # self.experimental_dataset = 'NVB_rescale_dataset.p'
        # self.model_heuristic_subroutine = qmla.shared_functionality.experiment_design_heuristics.MultiParticleGuessHeuristic
        self.model_heuristic_subroutine = (
            qmla.shared_functionality.experiment_design_heuristics.MixedMultiParticleLinspaceHeuristic
        )
        # self.model_heuristic_subroutine = qmla.shared_functionality.experiment_design_heuristics.VolumeAdaptiveParticleGuessHeuristic
        self.qinfer_model_subroutine = (
            qmla.shared_functionality.qinfer_model_interface.QInferNVCentreExperiment
        )
        # self.latex_string_map_subroutine = qmla.shared_functionality.latex_model_names.pauli_set_latex_name
        self.max_time_to_consider = 4.24

        # Tree
        self.max_num_parameter_estimate = 9
        self.max_spawn_depth = 8
        self.tree_completed_initially = True

        # parameter learning
        self.gaussian_prior_means_and_widths = {}

        self.max_num_models_by_shape = {1: 0, "other": 1}

        # logistics
        self.timing_insurance_factor = 0.75
        self.num_processes_to_parallelise_over = 6

    def get_true_parameters(
        self,
    ):
        self.fixed_true_terms = True
        self.true_hamiltonian = None
        self.true_params_dict = {}
        self.true_params_list = []

    def get_measurements_by_time(self):
        data_path = os.path.abspath(
            os.path.join(
                os.path.dirname(os.path.realpath(__file__)),
                "data/NVB_rescale_dataset.p",
            )
        )
        self.log_print(["Getting experimental data from {}".format(data_path)])
        self.measurements = pickle.load(open(data_path, "rb"))
        return self.measurements

    def DEPRECATED_latex_name(self, name, **kwargs):
        # print("[latex name fnc] name:", name)
        core_operators = list(
            sorted(qmla.model_building_utilities.core_operator_dict.keys())
        )
        num_sites = qmla.model_building_utilities.get_num_qubits(name)
        p_str = "P" * num_sites
        p_str = "+"
        separate_terms = name.split(p_str)

        site_connections = {}
        # for c in list(itertools.combinations(list(range(num_sites + 1)), 2)):
        #     site_connections[c] = []

        term_type_markers = ["pauliSet", "transverse"]
        transverse_axis = None
        for term in separate_terms:
            components = term.split("_")
            if "pauliSet" in components:
                components.remove("pauliSet")

                for l in components:
                    if l[0] == "d":
                        dim = int(l.replace("d", ""))
                    elif l[0] in core_operators:
                        operators = l.split("J")
                    else:
                        sites = l.split("J")
                sites = tuple([int(a) for a in sites])
                # assumes like-like pauli terms like xx, yy, zz
                op = operators[0]
                try:
                    site_connections[sites].append(op)
                except:
                    site_connections[sites] = [op]
            elif "transverse" in components:
                components.remove("transverse")
                for l in components:
                    if l[0] == "d":
                        transverse_dim = int(l.replace("d", ""))
                    elif l in core_operators:
                        transverse_axis = l

        ordered_connections = list(sorted(site_connections.keys()))
        latex_term = ""

        for c in ordered_connections:
            if len(site_connections[c]) > 0:
                this_term = r"\sigma_{"
                this_term += str(c)
                this_term += "}"
                this_term += "^{"
                for t in site_connections[c]:
                    this_term += "{}".format(t)
                this_term += "}"
                latex_term += this_term
        if transverse_axis is not None:
            latex_term += "T^{}_{}".format(transverse_axis, transverse_dim)
        latex_term = "${}$".format(latex_term)
        return latex_term
