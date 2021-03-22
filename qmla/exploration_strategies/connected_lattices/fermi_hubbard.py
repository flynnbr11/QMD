import numpy as np
import itertools
import sys
import os

from qmla.exploration_strategies import connected_lattice
import qmla.shared_functionality.probe_set_generation
import qmla.shared_functionality.latex_model_names
from qmla import model_building_utilities

# flatten list of lists
def flatten(l): return [item for sublist in l for item in sublist]


class FermiHubbardBase(
    connected_lattice.ConnectedLattice
):
    def __init__(
        self,
        exploration_rules,
        **kwargs
    ):
        # print("[Exploration Strategies] init nv_spin_experiment_full_tree")
        super().__init__(
            exploration_rules=exploration_rules,
            **kwargs
        )
        # self.true_model = 'FHhop_1h2_up_d2'
        self.true_model = 'FHhop_1h2_down_d3+FHhop_1h2_up_d3+FHhop_1h3_down_d3+FHhop_2h3_up_d3+FHonsite_1_d3+FHonsite_2_d3+FHonsite_3_d3'  # for testing
        self.tree_completed_initially = True
        self.initial_models = [
            self.true_model
        ]
        self.latex_string_map_subroutine = qmla.shared_functionality.latex_model_names.fermi_hubbard_latex
        self.system_probes_generation_subroutine = qmla.shared_functionality.probe_set_generation.separable_fermi_hubbard_half_filled
        # unless specifically different set of probes required
        self.simulator_probes_generation_subroutine = self.system_probes_generation_subroutine
        self.shared_probes = True  # i.e. system and simulator get same probes for learning
        self.plot_probes_generation_subroutine = qmla.shared_functionality.probe_set_generation.fermi_hubbard_half_filled_superposition
        # self.plot_probes_generation_subroutine = qmla.shared_functionality.probe_set_generation.FermiHubbard_single_spin_n_sites

        # self.max_time_to_consider = 20
        self.num_sites_true = model_building_utilities.get_num_qubits(self.true_model)
        self.num_qubits_true = 2*self.num_sites_true # FH uses 2 qubits per sites (up and down spin) 
        self.max_num_qubits = (self.num_sites_true * 2) + 2
        self.num_processes_to_parallelise_over = 9
        self.max_num_models_by_shape = {
            1: 0,
            2: 0,
            4: 10,
            6 : 1, 
            'other': 0
        }


class FermiHubbardProbabilistic(
    FermiHubbardBase
):
    def __init__(
        self,
        exploration_rules,
        **kwargs
    ):
        super().__init__(
            exploration_rules=exploration_rules,
            **kwargs
        )
        self.max_num_sites = 4
        self.max_num_probe_qubits = self.max_num_sites
        self.max_num_qubits = self.max_num_sites
        self.timing_insurance_factor = 20
        # self.num_probes = 20
        self.lattice_dimension = 1
        self.tree_completed_initially = False
        self.num_top_models_to_build_on = 1
        self.model_generation_strictness = 0
        self.fitness_win_ratio_exponent = 1
        self.qhl_models = [
            'FHhop_1h2_down_d3+FHonsite_3_d3'
        ]

        self.true_model_terms_params = {
            # term : true_param
            # 'FHhop_1h2_up_d2' : 1,
        }
        self.max_num_models_by_shape = {
            'other': 4
        }

        self.setup_exploration_class()

    def check_model_validity(
        self,
        model,
        **kwargs
    ):
        # possibility that some models not valid; not needed by default but
        # checked for general case
        terms = model_building_utilities.get_constituent_names_from_name(model)

        if np.all(['FHhop' in a for a in terms]):
            return True
        elif np.all(['FHonsite' in a for a in terms]):
            # onsite present in all terms: discard
            # self.log_print(
            #     ["Rejecting model", model, "b/c all onsite terms"]
            # )
            return False
        else:
            hopping_sites = []
            number_term_sites = []
            chemical_sites = []
            num_sites = model_building_utilities.get_num_qubits(model)
            for term in terms:
                constituents = term.split('_')
                constituents.remove('d{}'.format(num_sites))
                if 'FHhop' in term:
                    constituents.remove('FHhop')
                    for c in constituents:
                        if 'h' in c:
                            hopping_sites.extend(c.split('h'))
                elif 'FHonsite' in term:
                    constituents.remove('FHonsite')
                    number_term_sites.extend(constituents)
                elif 'FHchemical' in term:
                    constituents.remove('FHchemical')
                    chemical_sites.extend(constituents)

    #         print("hopping_sites:", hopping_sites)
    #         print('number term sites:', number_term_sites)
            hopping_sites = set(hopping_sites)
            number_term_sites = set(number_term_sites)
            overlap = number_term_sites.intersection(hopping_sites)

            if number_term_sites.issubset(hopping_sites):
                return True
            else:
                # no overlap between hopping sites and number term sites
                # so number term will be constant
                self.log_print(
                    [
                        "Rejecting model", model,
                        "bc number terms present"
                        "which aren't present in kinetic term"
                    ]
                )
                return False

    def match_dimension(
        self,
        mod_name,
        num_sites,
        **kwargs
    ):
        dimension_matched_name = match_dimension_hubbard(
            mod_name,
            num_sites,
        )
        return dimension_matched_name

    def generate_terms_from_new_site(
        self,
        **kwargs
    ):

        return generate_new_terms_hubbard(**kwargs)

    def combine_terms(
        self,
        terms,
    ):
        addition_string = '+'
        terms = sorted(terms)
        return addition_string.join(terms)


class FermiHubbardPredetermined(
    FermiHubbardProbabilistic
):
    def __init__(
        self,
        exploration_rules,
        **kwargs
    ):
        super().__init__(
            exploration_rules=exploration_rules,
            **kwargs
        )
        # self.true_model = 'FHhop_1h2_up_d2'
        self.tree_completed_initially = True
        # self.max_time_to_consider = 5
        self.num_processes_to_parallelise_over = 9
        self.max_num_models_by_shape = {
            # Note dN here requires 2N qubits so d3 counts as shape 6
            1: 0,
            2: 0,
            3 : 4,
            4: 4,
            6: 4,
            8: 4,
            'other': 0
        }
        self.max_num_qubits = 8
        self.initial_models = [
            'FHhop_1h2_down_d2',
            'FHhop_1h2_up_d2',
            'FHhop_1h2_down_d2+FHhop_1h2_up_d2',
            'FHhop_1h2_down_d3+FHhop_1h2_up_d3+FHhop_1h3_down_d3+FHonsite_1_d3+FHonsite_2_d3+FHonsite_3_d3',
            'FHhop_1h2_down_d3+FHhop_1h2_up_d3+FHhop_1h3_down_d3+FHhop_1h3_up_d3+FHhop_2h3_down_d3+FHhop_2h3_up_d3',
            'FHhop_1h2_down_d3+FHhop_1h2_up_d3+FHhop_1h3_down_d3+FHhop_1h3_up_d3+FHhop_2h3_down_d3+FHhop_2h3_up_d3+FHonsite_1_d3+FHonsite_2_d3+FHonsite_3_d3',
            'FHhop_1h2_down_d3+FHhop_1h2_up_d3+FHhop_1h3_down_d3+FHhop_2h3_up_d3+FHonsite_1_d3+FHonsite_2_d3+FHonsite_3_d3',
            # 'FHhop_1h2_down_d4+FHhop_1h2_up_d4+FHhop_1h3_down_d4+FHhop_2h4_down_d4+FHonsite_1_d4+FHonsite_2_d4+FHonsite_3_d4+FHonsite_4_d4',
        ]
        self.max_num_sites = 4
        self.qhl_models = self.initial_models

        self.true_model_terms_params = {
            'FHhop_1h2_down_d3': 0.56358314008409693, 
            'FHhop_1h2_up_d3': 0.61068905874925739, 
            'FHhop_1h3_down_d3': 0.49954927338652116, 
            'FHhop_2h3_up_d3': 0.52398243911927589, 
            'FHonsite_1_d3': 0.6260708716247626, 
            'FHonsite_2_d3': 0.51488767350916587, 
            'FHonsite_3_d3': 0.6516084737325778
        }

        if self.true_model not in self.initial_models:
            self.log_print(
                [
                    "True model not present in initial models for predetermined set; adding it."
                ]
            )
            self.initial_models.append(self.true_model)
        self.log_print(
            [
                "Predetermined models:", self.initial_models
            ]
        )
        self.setup_exploration_class()


def generate_new_terms_hubbard(
    connected_sites,
    num_sites,
    new_sites,
    **kwargs
):
    new_terms = []
    for pair in connected_sites:
        i = pair[0]
        j = pair[1]
        for spin in ['up', 'down']:
            hopping_term = "FHhop_{}h{}_{}_d{}".format(
                i, j, spin, num_sites
            )
            new_terms.append(hopping_term)

    for site in new_sites:
        onsite_term = "FHonsite_{}_d{}".format(
            site, num_sites
        )

        new_terms.append(onsite_term)

    return new_terms


def match_dimension_hubbard(
    model_name,
    num_sites,
    **kwargs
):
    redimensionalised_terms = []
    terms = model_name.split('+')
    for term in terms:
        parts = term.split('_')
        for part in parts:
            if part[0] == 'd' and part not in ['down', 'double']:
                parts.remove(part)

        parts.append("d{}".format(num_sites))
        new_term = "_".join(parts)
        redimensionalised_terms.append(new_term)
    new_model_name = "+".join(redimensionalised_terms)
    return new_model_name
