from __future__ import print_function  # so print doesn't show brackets

import numpy as np
import sys
import warnings
import copy

import scipy as sp
import qinfer as qi
import time

import qmla.shared_functionality.experimental_data_processing
import qmla.get_exploration_strategy
import qmla.memory_tests
import qmla.shared_functionality.probe_set_generation
import qmla.construct_models
import qmla.logging 

global_print_loc = False
global debug_print
debug_print = False
global debug_mode
debug_mode = True
global debug_print_file_line
debug_print_file_line = False


class QInferModelQMLA(qi.FiniteOutcomeModel):
    r"""
    Interface between QMLA and QInfer.

    QInfer is a library for performing Bayesian inference
    on quantum data for parameter estimation.
    It underlies the Quantum Hamiltonian Learning subroutine
    employed within QMLA.
    Bayesian inference relies on comparisons likelihoods
    of the target and candidate system. 
    This class, specified by an exploration strategy, defines how to 
    compute the likelihood for the user's system. 
    Most functionality is inherited from QInfer, but methods listed 
    here are edited for QMLA's needs. 
    The likelihood function given here should suffice for most QMLA 
    implementations, though users may want to overwrite 
    get_system_pr0_array and get_simulator_pr0_array, 
    for instance to specify which experimental data points to use. 
    
    :param str model_name: Unique string representing a model.
    :param np.ndarray modelparams: list of parameters to multiply by operators, 
        unused for QMLA reasons but required by QInfer. 
    :param np.ndarray oplist: Set of operators whose sum
        defines the evolution Hamiltonian 
        (where each operator is associated with a distinct parameter).
    :param np.ndarray true_oplist: list of operators of the target system,
        used to construct true hamiltonian.
    :param np.ndarray trueparams: list of parameters of the target system,
        used to construct true hamiltonian.
    :param int num_probes: number of probes available in the probe sets, 
        used to loop through probe set
    :param dict probe_dict: set of probe states to be used during training
        for the system, indexed by (probe_id, num_qubits). 
    :param dict sim_probe_dict: set of probe states to be used during training
        for the simulator, indexed by (probe_id, num_qubits). Usually the same as 
        the system probes, but not always. 
    :param str exploration_rule: string corresponding to a unique exploration strategy,
        used to generate an explorationStrategy_ instance.
    :param dict experimental_measurements: fixed measurements of the target system, 
        indexed by time.
    :param list experimental_measurement_times: times indexed in experimental_measurements.
    :param str log_file: Path of log file.
    """

    ## INITIALIZER ##

    def __init__(
        self,
        model_name,
        modelparams,
        oplist,
        true_oplist,
        truename,
        true_param_dict,
        true_model_constructor,
        trueparams,
        num_probes,
        probe_dict,
        sim_probe_dict,
        exploration_rules,
        experimental_measurements,
        experimental_measurement_times,
        log_file,
        qmla_id=-1, 
        evaluation_model=False,
        estimated_params=None,
        comparison_model=False, 
        debug_mode=False,
        **kwargs
    ):
        self.model_name = model_name
        self.log_file = log_file
        self.qmla_id = qmla_id
        self.exploration_rules = exploration_rules
        self._oplist = oplist
        self._a = 0
        self._b = 0
        self.probe_counter = 0
        self.probe_rotation_frequency = 10
        self._modelparams = modelparams
        self.signs_of_inital_params = np.sign(modelparams)
        self._true_oplist = true_oplist
        self._trueparams = trueparams
        self._truename = truename
        self._true_dim = qmla.construct_models.get_num_qubits(self._truename)
        self.true_param_dict = true_param_dict 
        self.true_model_constructor = true_model_constructor
        self.store_likelihoods = {x : {} for x in ['system', 'simulator_median', 'simulator_mean']}
        self.likelihood_calls = {_ : 0 for _ in ['system', 'simulator']}
        self.summarise_likelihoods = {
            x : []
            for x in [
                'system', 
                'particles_median', 'particles_mean',
                'particles_std', 'particles_lower_quartile', 'particles_upper_quartile']
        }
        self.store_p0_diffs = []
        self.debug_mode = debug_mode
        # get true_hamiltonian from true_param dict
        self.log_print(["True params dict:", self.true_param_dict])
        true_ham = None
        for k in list(self.true_param_dict.keys()):
            param = self.true_param_dict[k]
            mtx = qmla.construct_models.compute(k)
            if true_ham is not None:
                true_ham += param * mtx
            else:
                true_ham = param * mtx
        self.true_hamiltonian = true_ham

        self.timings = {
            'system': {}, 
            'simulator' : {}
        }
        for k in self.timings:
            self.timings[k] = {
                'expectation_values' : 0, 
                'get_pr0' : 0,
                'get_probe' : 0, 
                'construct_ham' : 0,
                'storing_output' : 0,
                'likelihood_array' : 0,
                'likelihood' : 0, 
            }
        self.calls_to_likelihood = 0 
        self.single_experiment_timings = {
            k : {} for k in ['system', 'simulator']
        }
        try:
            self.exploration_class = qmla.get_exploration_strategy.get_exploration_class(
                exploration_rules=self.exploration_rules,
                log_file=self.log_file,
                qmla_id=self.qmla_id, 
            )
        except BaseException:
            self.log_print([
                "Could not instantiate exploration strategy {}. Terminating".foramt(
                    self.exploration_rules
                )
            ])
            raise
        self.experimental_measurements = experimental_measurements
        self.experimental_measurement_times = experimental_measurement_times
        self.iqle_mode = self.exploration_class.iqle_mode 
        self.comparison_model = comparison_model
        self.evaluation_model = evaluation_model
        if self.evaluation_model:
            self.estimated_params = estimated_params
            self.log_print([
                "Evaluation qinfer model. Estimated parameters: {}".format(
                    self.estimated_params
                )
            ])
            estimated_model=None
            for i in range(len(self.estimated_params)):
                p = self.estimated_params[i]
                m = self._oplist[i]
                if estimated_model is None:
                    estimated_model = p*m
                else:
                    estimated_model += p*m
            self.estimated_model = estimated_model
            try:
                self.log_print([
                    "Estimated model's difference from true model", 
                    np.max(np.abs(self.estimated_model - self.true_hamiltonian))
                ])
            except:
                # different dimension candidate from true model; doesn't really matter
                pass


        # Required by QInfer: 
        self._min_freq = 0 # what does this do?
        self._solver = 'scipy'
        # This is the solver used for time evolution scipy is faster
        # QuTip can handle implicit time dependent likelihoods

        # self.model_dimension = qmla.construct_models.get_num_qubits(self.model_name)
        self.model_dimension = int(np.log2(self._oplist[0].shape[0]))
        self._true_dim = int(np.log2(self.true_hamiltonian.shape[0]))
        self.log_print(["\nModel {} dimension: {}. ".format(
            self.model_name,  self.model_dimension
        )])
        if true_oplist is not None and trueparams is None:
            raise(
                ValueError(
                    '\nA system Hamiltonian with unknown \
                    parameters was requested'
                )
            )
        super(QInferModelQMLA, self).__init__(self._oplist)
        # self.log_print_debug([
        #     "true ops:\n", self._true_oplist,
        #     "\nsim ops:\n", self._oplist
        # ])

        try:
            self.probe_dict = probe_dict
            self.sim_probe_dict = sim_probe_dict
            self.probe_number = num_probes
        except:
            raise ValueError(
                "Probe dictionaries not passed to Qinfer model"
            )
        self.log_print_debug([
            "_trueparams:", self._trueparams
        ])


    def log_print(
        self, 
        to_print_list, 
        log_identifier=None
    ):
        r"""Writng to unique QMLA instance log."""
        if log_identifier is None: 
            log_identifier = 'QInfer interface {}'.format(self.model_name)

        qmla.logging.print_to_log(
            to_print_list = to_print_list, 
            log_file = self.log_file, 
            log_identifier = log_identifier
        )

    def log_print_debug(
        self, 
        to_print_list
    ):
        r"""Log print if global debug_mode set to True."""

        if self.debug_mode:
            self.log_print(
                to_print_list = to_print_list,
                log_identifier = 'QInfer interface debug'
            )

    ## PROPERTIES ##
    @property
    def n_modelparams(self):
        r"""
        Number of parameters in the specific model 
        typically, in QMLA, we have one parameter per model.
        """

        return len(self._oplist)

    @property
    def modelparam_names(self):
        r"""
        Returns the names of the various model parameters admitted by this
        model, formatted as LaTeX strings. (Inherited from Qinfer)
        """
        try:
            individual_term_names = self.model_name.split('+')
        except:
            individual_term_names = ['w0']
            for modpar in range(self.n_modelparams - 1):
                individual_term_names.append('w' + str(modpar + 1))
        
        return individual_term_names


    @property
    def expparams_dtype(self):
        r"""
        Returns the dtype of an experiment parameter array. 
        
        For a model with single-parameter control, this will likely be a scalar dtype,
        such as ``"float64"``. More generally, this can be an example of a
        record type, such as ``[('time', py.'float64'), ('axis', 'uint8')]``.
        This property is assumed by inference engines to be constant for
        the lifetime of a Model instance.
        In the context of QMLA the expparams_dtype are assumed to be a list of tuple where
        the first element of the tuple identifies the parameters (including type) while the second element is
        the actual type of of the parameter, typicaly a float.
        (Modified from Qinfer).
        """

        # expparams are the {t, probe_id, w1, w2, ...} guessed parameters, i.e. each 
        # particle has a specific sampled value of the corresponding
        # parameter
        
        expnames = [
            ('t', 'float'),
            ('probe_id', 'int')
        ]
        try:
            individual_model_terms = self.model_name.split('+')
        except:
            individual_model_terms = [
                'w_{}'.format(i)
                for i in range(self.n_modelparams)
            ]
        for term in individual_model_terms:
            expnames.append( (term, 'float') )

        return expnames

    ################################################################################
    # Methods
    ################################################################################

    def are_models_valid(self, modelparams):
        r"""
        Checks that the proposed models are valid.

        Before setting new distribution after resampling,
        checks that all parameters have same sign as the
        initial given parameter for that term.
        Otherwise, redraws the distribution.
        Modified from qinfer.
        """

        same_sign_as_initial = False
        if same_sign_as_initial == True:
            new_signs = np.sign(modelparams)
            validity_by_signs = np.all(
                np.sign(modelparams) == self.signs_of_inital_params,
                axis=1
            )
            return validity_by_signs
        else:
            validity = np.all(np.abs(modelparams) > self._min_freq, axis=1)
            return validity

    def n_outcomes(self, expparams):
        r"""
        Returns an array of dtype ``uint`` describing the number of outcomes
        for each experiment specified by ``expparams``.

        :param numpy.ndarray expparams: Array of experimental parameters. This
            array must be of dtype agreeing with the ``expparams_dtype``
            property.
        """
        return 2

    def likelihood(
        self,
        outcomes,
        modelparams,
        expparams
    ):
        r"""
        Function to calculate likelihoods for all the particles
        
        Inherited from Qinfer:
        Calculates the probability of each given outcome, conditioned on each
        given model parameter vector and each given experimental control setting.

        QMLA modifications: 
        Given a list of experiments to perform, expparams, 
        extract the time list. Typically we use a single experiment
        (therefore single time) per update.
        QInfer passes particles as modelparams.
        QMLA updates its knowledge in two steps:
            * "simulate" an experiment (which can include outsourcing from here to perform a real experiment), 
            * update parameter distribution by comparing Np particles to the experimental result
        
        It is important that the comparison is fair, meaning:
            * The evolution time must be the same
            * The probe state to evolve must be the same.

        To simulate the experiment, we call QInfer's simulate_experiment,
        which calls likelihood(), passing a single particle. 
        The update function calls simulate_experiment with Np particles. 
        Therefore we know, when a single particle is passed to likelihood, 
        that we want to call the true system (we know the true parameters 
        and operators by the constructor of this class). 
        So, when a single particle is detected, we circumvent QInfer by triggering
        get_system_pr0_array. Users can overwrite this function as desired; 
        by default it computes true_hamiltonian, 
        and computes the likelhood for the given time. 
        When >1 particles are detected, pr0 is computed by constructing Np 
        candidate Hamiltonians, each corresponding to a single particle, 
        where particles are chosen by Qinfer and given as modelparams.
        This is done through get_simulator_pr0_array.
        We know calls to likelihood are coupled: 
        one call for the system, and one for the update, 
        which must use the same probes. Therefore probes are indexed
        by a probe_id as well as their dimension. 
        We track calls to likelihood() in _a and increment the probe_id
        to pull every second call, to ensure the same probe_id is used for 
        system and simulator.

        :param np.ndarray outcomes: outcomes of the experiments
        :param np.ndarray modelparams: 
            values of the model parameters particles 
            A shape ``(n_particles, n_modelparams)``
            array of model parameter vectors describing the hypotheses for
            which the likelihood function is to be calculated.
        
        :param np.ndarray expparams: 
            experimental parameters, 
            A shape ``(n_experiments, )`` array of
            experimental control settings, with ``dtype`` given by 
            :attr:`~qinfer.Simulatable.expparams_dtype`, describing the
            experiments from which the given outcomes were drawn.
            
        :rtype: np.ndarray
        :return: A three-index tensor ``L[i, j, k]``, where ``i`` is the outcome
            being considered, ``j`` indexes which vector of model parameters was used,
            and where ``k`` indexes which experimental parameters where used.
            Each element ``L[i, j, k]`` then corresponds to the likelihood
            :math:`\Pr(d_i | \vec{x}_j; e_k)`.
        """

        self.calls_to_likelihood+=1
        t_likelihood_start = time.time()
        super(QInferModelQMLA, self).likelihood(
            outcomes, modelparams, expparams
        )  # just adds to self._call_count (Qinfer abstact model class)

        # process expparams
        times = expparams['t'] # times to compute likelihood for. typicall only per experiment. 
        probe_id = expparams['probe_id'][0]
        expparams_sampled_particle = np.array(
            [expparams.item(0)[2:]]) # TODO THIS IS DANGEROUS - DONT DO IT OUTSIDE OF TESTS               
        self.log_print_debug([
            "expparams_sampled_particle:", expparams_sampled_particle
        ])
        self.ham_from_expparams = np.tensordot(
            expparams_sampled_particle, 
            self._oplist, 
            axes=1    
        )[0]

        num_particles = modelparams.shape[0]
        num_parameters = modelparams.shape[1]

        # assumption is that calls to likelihood are paired: 
        # one for system, one for simulator
        # therefore the same probe should be assumed for consecutive calls
        # probe id is tracked with _a and _b.
        # i.e. increments each 2nd call, loops back when probe dict exhausted

        if num_particles == 1:
            # TODO better mechanism to determine if self.true_evolution, 
            # rather than assuming 1 particle => system
            # call the system, use the true paramaters as a single particle, 
            # to get the true evolution
            self.true_evolution = True
            params = [copy.deepcopy(self._trueparams)]
        else:
            self.true_evolution = False
            params = modelparams

        self.probe_counter = probe_id

        self.log_print_debug([
            "\n\nLikelihood fnc called. Probe counter={}. True system -> {}.".format(self.probe_counter, self.true_evolution)
        ])

        try:
            if self.true_evolution:
                t_init = time.time()
                # self.log_print(["Getting system pr0"])
                self.log_print_debug([
                    "Getting system Pr0 w/ params ", params
                ])
                pr0 = self.get_system_pr0_array(
                    times=times,
                    particles=params,
                )
                timing_marker = 'system'
                self.timings[timing_marker]['get_pr0'] += time.time() - t_init
            else:
                t_init = time.time()
                # self.log_print(["Getting simulator pr0"])
                self.log_print_debug([
                    "Getting simulator Pr0 w/ params ", params
                ])
                pr0 = self.get_simulator_pr0_array(
                    times=times,
                    particles=params,
                ) 
                timing_marker = 'simulator'
                self.timings[timing_marker]['get_pr0'] += time.time() - t_init
        except:
            self.log_print([
                "Failed to compute pr0. probe id used: {}".format(self.probe_counter)
            ])
            # self.log_print(["H_ for IQLE:", self.ham_from_expparams[0]])
            raise # TODO raise specific error
            sys.exit()
        t_init = time.time()
        likelihood_array = (
            qi.FiniteOutcomeModel.pr0_to_likelihood_array(
                outcomes, pr0
            )
        )
        self.timings[timing_marker]['likelihood_array'] += time.time() - t_init
        self.single_experiment_timings[timing_marker]['likelihood'] = time.time() - t_likelihood_start

        self.log_print_debug([
            '\ntrue_evo:', self.true_evolution,
            '\nevolution times:', times,
            '\nlen(outcomes):', len(outcomes),
            '\n_a = {}, _b={}'.format(self._a, self._b),
            '\nprobe counter:', self.probe_counter,
            '\nexp:', expparams,
            '\nOutcomes:', outcomes[:3],
            '\nparticles:', params[:3],
            "\nPr0: ", pr0[:3], 
            "\nLikelihood: ", likelihood_array[0][:3],
            "\nexpparams_sampled_particle:", expparams_sampled_particle
        ])
        
        self.timings[timing_marker]['likelihood'] += time.time() - t_likelihood_start

        t_storage_start = time.time()
        if self.true_evolution: 
            self.log_print_debug(["Storing system likelihoods"])
            self.store_likelihoods['system'][self.likelihood_calls['system']] = pr0
            self.summarise_likelihoods['system'].append(np.median(pr0))
            self.likelihood_calls['system'] += 1 
        else:
            self.store_likelihoods['simulator_mean'][self.likelihood_calls['simulator']] = np.mean(pr0)
            self.store_likelihoods['simulator_median'][self.likelihood_calls['simulator']] = np.median(pr0)
            diff_p0 = np.abs( pr0 - self.store_likelihoods['system'][self.likelihood_calls['simulator']] )
            self.store_p0_diffs.append( [np.median(diff_p0), np.std(diff_p0)] )
            self.summarise_likelihoods['particles_mean'].append( np.median(pr0) )
            self.summarise_likelihoods['particles_median'].append( np.median(pr0) )
            self.summarise_likelihoods['particles_std'].append( np.std(pr0) )
            self.summarise_likelihoods['particles_lower_quartile'].append( np.percentile(pr0, 25) )
            self.summarise_likelihoods['particles_upper_quartile'].append( np.percentile(pr0, 75) )
            self.likelihood_calls['simulator'] += 1 
        self.single_experiment_timings[timing_marker]['storage'] = time.time() - t_storage_start
        self.log_print_debug([
            "Setting single_experiment_timings for {}[{}] -> {}".format(
                timing_marker, 'storage', time.time() - t_storage_start
            )
        ])

        self.log_print_debug(["Stored likelihoods"])

        if self.evaluation_model:
            self.log_print_debug([
                "\nSystem evolution {}. t={} Likelihood={}".format(
                self.true_evolution, times[0], likelihood_array[:3]
            )])
        
        return likelihood_array

    def get_system_pr0_array(
        self, 
        times,
        particles, 
        # **kwargs
    ):
        r"""
        Compute pr0 array for the system. 
        # TODO compute e^(-iH) once for true Hamiltonian and use that rather than computing every step. 

        For user specific data, or method to compute system data, replace this function 
            in exploration_strategy.qinfer_model_subroutine. 
        Here we pass the true operator list and true parameters to 
            default_pr0_from_modelparams_times_.

        :param list times: times to compute pr0 for; usually single element.
        :param np.ndarry particles: list of parameter-lists, used to construct
            Hamiltonians. In this case, there should be a single particle
            corresponding to the true parameters. 
        
        :returns np.ndarray pr0: probabilities of measuring specified outcome
        """
        timing_marker = 'system'

        operator_list = self._true_oplist
        ham_num_qubits = self._true_dim
        # format of probe dict keys: (probe_id, qubit_number)
        # probe_counter controlled in likelihood method
        # probe = self.get_probe(
        #     probe_id = self.probe_counter, 
        #     probe_set = "system"
        # )
        probe = self.probe_dict[
            self.probe_counter,
            self._true_dim 
        ]
        # self.log_print([
        #     "\nTrue Model {} has dim {} (operator shape {}) using system probe dimension: {}".format(
        #         self._truename, self._true_dim, np.shape(operator_list[0]), probe.shape),
        #     # "\nTrue Model  {} has shape {} with dimension {}".format(self._truename, np.shape(operator_list[0]), self._true_dim)
        # ])

        # TODO: could just work with true_hamiltonian, worked out on __init__
        return self.default_pr0_from_modelparams_times(
            t_list = times,
            particles = particles, 
            oplist = operator_list, 
            # hamiltonian=self.true_hamiltonian, 
            probe = probe, 
            timing_marker=timing_marker
            # **kwargs
        )

    def get_simulator_pr0_array(
        self, 
        particles, 
        times,
        # **kwargs
    ):
        r"""
        Compute pr0 array for the simulator. 

        For user specific data, or method to compute simulator data, replace this function 
            in exploration_strategy.qinfer_model_subroutine. 
        Here we pass the candidate model's operators and particles
            to default_pr0_from_modelparams_times_.

        :param list times: times to compute pr0 for; usually single element.
        :param np.ndarry particles: list of particles (parameter-lists), used to construct
            Hamiltonians. 
        
        :returns np.ndarray pr0: probabilities of measuring specified outcome
        """
        timing_marker = 'simulator'
        ham_num_qubits = self.model_dimension
        # format of probe dict keys: (probe_id, qubit_number)
        # probe_counter controlled in likelihood method
        t_init = time.time()

        probe = self.sim_probe_dict[
            self.probe_counter,
            self.model_dimension
        ]

        self.timings[timing_marker]['get_probe'] += time.time() - t_init
        operator_list = self._oplist
        if self.evaluation_model:
            # self.log_print_debug([
            self.log_print_debug([
                "\nUsing precomputed Hamiltonian. probe[0] (ID {}):\n{}".format(
                    self.probe_counter, 
                    probe[0]
                )
            ])
            hamiltonian = self.estimated_model
        else:
            hamiltonian = None
        
        t_init = time.time()
        pr0 = self.default_pr0_from_modelparams_times(
            t_list = times, 
            particles = particles, 
            oplist = operator_list, 
            probe = probe, 
            hamiltonian=hamiltonian,
            timing_marker=timing_marker
            # **kwargs
        )
        return pr0

    def default_pr0_from_modelparams_times(
        self,
        t_list,
        particles,
        oplist,
        probe,
        timing_marker,
        hamiltonian=None,
        **kwargs
    ):
        r"""
        Compute probabilities of available outputs as an array.

        :param np.ndarray t_list: 
            List of times on which to perform experiments
        :param np.ndarray particles: 
            values of the model parameters particles 
            A shape ``(n_particles, n_modelparams)``
            array of model parameter vectors describing the hypotheses for
            which the likelihood function is to be calculated.
        :param list oplist:
            list of the operators defining the model
        :param np.ndarray probe: quantum state to evolve

        :returns np.ndarray pr0: list of probabilities (one for each particle).
            The calculation, meaning and interpretation of these probabilities 
            depends on the user defined ExplorationStrategy.expectation_value function. 
            By default, it is the expecation value:
                | < probe.transpose | e^{-iHt} | probe > |**2,
                but can be replaced in the ExplorationStrategy_.  
        """

        from rq import timeouts
        if np.shape(probe)[0] < 4 : 
            probe_to_print = probe
        else:
            probe_to_print = probe[0]

        self.log_print_debug([
            "Getting pr0; true system ->", self.true_evolution, 
            "\n(part of) Probe (dimension {}): \n {}".format(
                np.shape(probe),
                probe_to_print,
            ),
            "\nTimes: ", t_list
        ])

        # if hamiltonian is not None: 
        #     self.log_print([
        #         "Hamiltonian passed:\n", hamiltonian
        #     ])

        num_particles = len(particles)
        num_times = len(t_list)
        output = np.empty([num_particles, num_times])

        for evoId in range(num_particles):  
            try:
                t_init = time.time()
                if hamiltonian is None:
                    ham = np.tensordot(
                        particles[evoId], oplist, axes=1
                    )
                else:                    
                    ham = hamiltonian

                if self.iqle_mode and self.true_evolution:
                    # H to compute for IQLE on the system
                    ham =  self.true_hamiltonian - self.ham_from_expparams
                elif self.iqle_mode and not self.true_evolution:
                    # H to compute for IQLE on the simulator
                    ham = ham - self.ham_from_expparams
                    if np.any(np.isnan(ham)):
                        self.log_print(["NaN detected in Hamiltonian. Ham from expparams:", self.ham_from_expparams])

                self.timings[timing_marker]['construct_ham'] += time.time()-t_init
            except BaseException:
                self.log_print(
                    [
                        "Failed to build Hamiltonian.",
                        "\nparticles:", particles[evoId],
                        "\noplist:", oplist
                    ],
                )
                raise
            # if evoId == 0:
            #     self.log_print_debug([
            #         "\nHamiltonian:\n", ham,
            #         "\ntimes:", t_list,
            #         "\nH from expparams:", self.ham_from_expparams
            #     ])

            for tId in range(len(t_list)):

                t = t_list[tId]
                if t > 1e6:  # Try limiting times to use to 1 million
                    import random
                    # random large number but still computable without error
                    t = random.randint(1e6, 3e6)
                try:
                    t_init = time.time()
                    prob_meas_input_state = self.exploration_class.get_expectation_value(
                        ham=ham,
                        t=t,
                        state=probe,
                        log_file=self.log_file,
                        log_identifier='get pr0 call exp val'
                    )
                    self.timings[timing_marker]['expectation_values'] += time.time() - t_init
                    t_init = time.time()
                    output[evoId][tId] = prob_meas_input_state
                    self.timings[timing_marker]['storing_output'] += time.time() - t_init

                except NameError:
                    self.log_print([
                        "Error raised; unphysical expecation value.",
                        "\nParticle:\n", particles[evoId],
                        "\nt=", t,
                    ])
                    sys.exit()
                except timeouts.JobTimeoutException:
                    self.log_print([
                        "RQ Time exception.",
                        "\nParticle:\n", particles[evoId],
                        "\nt=", t,
                    ])
                    sys.exit()

                if output[evoId][tId] < 0:
                    print("NEGATIVE PROB")
                    self.log_print([
                        "Negative probability : \
                        \n probability = ",
                        output[evoId][tId],
                        "\nat t=", t_list
                    ])
                elif output[evoId][tId] > 1.001:
                    self.log_print(
                        [
                            "[QLE] Probability > 1: \
                            \t \t probability = ",
                            output[evoId][tId]
                        ]
                    )
        return output


class QInferNVCentreExperiment(QInferModelQMLA):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def get_system_pr0_array(
        self, 
        times,
        particles, 
        **kwargs
    ):
        self.log_print_debug(["Getting pr0 from experimental dataset."])
        # time = expparams['t']
        if len(times) > 1:
            self.log_print("Multiple times given to experimental true evolution:", times)
            sys.exit()

        time = times[0]
        
        try:
            # If time already exists in experimental data
            experimental_expec_value = self.experimental_measurements[time]
        except BaseException:
            # map to nearest experimental time
            try:
                experimental_expec_value = qmla.shared_functionality.experimental_data_processing.nearest_experimental_expect_val_available(
                    times=self.experimental_measurement_times,
                    experimental_data=self.experimental_measurements,
                    t=time
                )
            except:
                self.log_print_debug([
                    "Failed to get experimental data point"
                ])
                raise
            self.log_print_debug([
                "experimental value for t={}: {}".format(
                    time, 
                    experimental_expec_value
                )
            ])
        self.log_print_debug([
            "Using experimental time", time,
            "\texp val:", experimental_expec_value
        ])
        pr0 = np.array([[experimental_expec_value]])
        self.log_print_debug([
            "pr0 for system:", pr0
        ])
        return pr0

    def get_simulator_pr0_array(
        self, 
        particles, 
        times,
        # **kwargs
    ):
        # map times to experimentally available times
        mapped_times = [
            qmla.shared_functionality.experimental_data_processing.nearest_experimental_time_available(
                times = self.experimental_measurement_times,
                t = t
            )
            for t in times
        ]
        return super().get_simulator_pr0_array(
            particles, 
            mapped_times
        )


class QInferInterfaceJordanWigner(QInferModelQMLA):
    r"""
    For use when models are implemented via Jordan Wigner transformation, 
    since this invokes 2 qubits per site in the system. 
    Therefore, everything remains as in other models, 
    apart from probe selection should use the appropriate probe id, 
    but twice the number of qubits specified by the model. 
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def get_probe(
        self, 
        probe_id, 
        probe_set
    ):
        self.log_print([
            "Using JW get_probe"
        ])
        if probe_set == 'simulator':
            probe = self.sim_probe_dict[
                probe_id,
                2*self.model_dimension            ]
            return probe

        elif probe_set == 'system': 
            # get dimension directly from true model since this can be generated by another ES 
            # and therefore note require the 2-qubit-per-site overhead of Jordan Wigner.
            dimension = np.log2(np.shape(self.true_hamiltonian)[0])
            probe = self.probe_dict[
                probe_id,
                self._true_dim
            ]
            return probe
        else:
            self.log_print([
                "get_probe must either act on simulator or system, received {}".format(probe_set)
            ])
            raise ValueError(
                "get_probe must either act on simulator or system, received {}".format(probe_set)
            )


class QInferInterfaceAnalytical(QInferModelQMLA):
    r"""
    Analytically computes the likleihood for an exemplary case. 
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def get_system_pr0_array(
        self, 
        times,
        particles, 
    ):

        pr0 = np.empty([len(particles), len(times)])
        t = times[0]
        self.log_print_debug([
            "(sys) particles:", particles,
            "time: ", t,
            "\n shapes: prt={} \t times={}".format(np.shape(particles), np.shape(times))
        ])

        for evoId in range(len(particles)):
            particle = particles[evoId][0]
            for t_id in range(len(times)):
                pr0[evoId][t_id] = (np.cos(particle * t / 2))**2

        return pr0

    def get_simulator_pr0_array(
        self, 
        particles, 
        times,
        # **kwargs
    ):
        pr0 = np.empty([len(particles), len(times)])
        t = times[0]
        self.log_print_debug([
            "(sim) particles:", particles,
            "time: ", t,
            "\n shapes: prt={} \t times={}".format(np.shape(particles), np.shape(times))
        ])

        for evoId in range(len(particles)):
            particle = particles[evoId]  
            for t_id in range(len(times)):
                pr0[evoId][t_id] = (np.cos(particle * t / 2))**2

        return pr0

