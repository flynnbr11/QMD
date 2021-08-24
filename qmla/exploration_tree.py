from __future__ import absolute_import
from __future__ import print_function

import math
import numpy as np
import os as os
import sys as sys
import pandas as pd
import time
from time import sleep
import random
import itertools

import pickle
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

import qmla.logging
import qmla.model_building_utilities

pickle.HIGHEST_PROTOCOL = 4
plt.switch_backend("agg")

__all__ = ["ExplorationTree", "BranchQMLA"]


class ExplorationTree:
    r"""
    Tree corresponding to an exploration strategy for management within QMLA.

    Each :class:`~qmla.exploration_strategies.ExplorationStrategy` in the  :class:`~qmla.QuantumModelLearningAgent`
    instance is associated with one tree (instance of this class).
    The tree interacts with the QMLA environment, for instance to choose the next set of models
    to learn through :meth:`~qmla.ExplorationTree.next_layer`.
    :class:`~qmla.BranchQMLA` exist both on the tree and the QMLA environment.

    :param ExplorationStrategy exploration_class: instance of the exploration strategy to associate with this tree.
    """

    def __init__(
        self,
        exploration_class,
    ):
        # Give tree access to the ES instance
        self.exploration_class = exploration_class

        # Give the ES access to this tree.
        self.exploration_class.tree = self
        self.exploration_strategy = self.exploration_class.exploration_rules

        # Infrastructure
        self.log_file = self.exploration_class.log_file
        self.log_print(["Tree started for {}".format(self.exploration_strategy)])
        self.branches = {}
        self.models = {}
        self.model_storage_instances = {}
        self.parent_children = {}
        self.child_parents = {}
        self.spawn_step = 0
        self.prune_step = 0
        self.graphs = {}

    ##########
    # Section: Interface with exploration strategy
    ##########

    def get_initial_models(
        self,
    ):
        r"""
        Models for the first layer of this exploration strategy.

        :return list initial_models: list of model names to place on the first
            layer corresponding to this ES
        :return list pairs_to_compare: list of model name pairs to compare
        """

        # Get models to learn
        if self.exploration_class.initial_models is None:
            # call generate_models if not explicitly set by ES
            self.log_print(["Initial models not set; retrieving from generate_models"])
            self.initial_models = self.exploration_class.generate_models(model_list=[])
        else:
            self.initial_models = self.exploration_class.initial_models

        # Get comparisons: pairs of models to compare on the first layer
        if self.exploration_class.branch_comparison_strategy == "all":
            pairs_to_compare = "all"
        elif self.exploration_class.branch_comparison_strategy == "optimal_graph":
            self.log_print(
                [
                    "Getting optimal comparison graph for {} models".format(
                        len(self.initial_models)
                    )
                ]
            )
            # pairs_to_compare, graph = qmla.shared_functionality.model_pairing_strategies.find_efficient_comparison_pairs(
            #     model_names=self.initial_models
            # )
            (
                pairs_to_compare,
                graph,
            ) = qmla.shared_functionality.model_pairing_strategies.generate_random_regular_graph(
                model_list=self.initial_models
            )

            self.log_print(
                [
                    "Using optimal graph to select subset of model pairs to compare. ({} pairs)".format(
                        len(pairs_to_compare)
                    ),
                ]
            )
            # self.log_print(["Got pairs to compare:", pairs_to_compare])
            self.graphs[self.spawn_step] = graph
        elif self.exploration_class.branch_comparison_strategy == "minimal":
            # TODO very few connections, only used to avoid crash
            model_list = self.initial_models
            first_half = model_list[: int(len(model_list) / 2)]
            second_half = model_list[int(len(model_list) / 2) :]
            pairs_to_compare = list(zip(first_half, second_half))

        elif self.exploration_class.branch_comparison_strategy == "sparse_connection":
            pairs_to_compare = []
        else:
            pairs_to_compare = "all"

        return self.initial_models, pairs_to_compare

    def next_layer(self, **kwargs):
        r"""
        Determine the next set of models, for the next branch of this exploration strategy tree.

        These are generated iteratively in stages, until that stage is marked as complete within the exploration strategy.
        * Spwaning: using the set of models from the previous branch to construct new models,
          via :meth:`~qmla.exploration_strategies.ExplorationStrategy.generate_models`.
        * The spawning stage is terminated when :meth:`~qmla.exploration_strategies.ExplorationStrategy.check_tree_completed`
          returns True. For example, if a predetermined number of spawn steps have passed,
          or if the model learning has converged.
        * After the spawn stage, the tree enters the pruning stage.
          For example, parental collapse: branch champions of this tree
          are compared with their parents; if either parent or child is strongly superior,
          the loser does not progress to the next branch.
        * Pruning is carried out by :meth:`~qmla.exploration_strategies.ExplorationStrategy.tree_pruning`, until
          :meth:`~qmla.exploration_strategies.ExplorationStrategy.check_tree_pruned returns True.
        * After the pruning stage, it must be possible for this tree to nominate a list of
          models to be considered for global champion, by :meth:`~qmla.ExplorationTree.nominate_champion`.

        The set of models decided by this method are placed on the next QMLA branch.
        ``pairs_to_compare`` here specifies which pairs of models on that next branch should be compared.
        Typically, model learning corresponds to spawning; during this stage all models on branches
        should be compared.
        Pruning then corresponds to comparing models which have already been leared
        (though new unlearned models will be learned).
        During pruning, it may not be necessary to compare all pairs, for instance if it is desired only
        to compare parent/child pairs at a given branch.

        :param dict kwargs: key word args passed directly to spawning/pruning functions.
        :return list model_list: list of model names to place on the next QMLA branch
        :return str or list pairs_to_compare: which model IDs within the model_list
            to perform comparisons between.
        """

        if not self.exploration_class.check_tree_completed(spawn_step=self.spawn_step):
            self.spawn_step += 1
            self.exploration_class.spawn_step = self.spawn_step
            self.log_print(["Next layer - spawn"])
            model_list = self.exploration_class.generate_models(
                spawn_step=self.spawn_step, **kwargs
            )
            if self.exploration_class.branch_comparison_strategy == "all":
                pairs_to_compare = "all"
            elif self.exploration_class.branch_comparison_strategy == "optimal_graph":
                self.log_print(["Getting graph for restricted comparisons"])

                # pairs_to_compare, graph = qmla.shared_functionality.model_pairing_strategies.find_efficient_comparison_pairs(
                #     model_names=model_list
                # )
                (
                    pairs_to_compare,
                    graph,
                ) = qmla.shared_functionality.model_pairing_strategies.generate_random_regular_graph(
                    model_list=model_list
                )
                self.log_print(
                    [
                        "Using optimal graph to select subset of model pairs to compare. ({} pairs)".format(
                            len(pairs_to_compare)
                        )
                    ]
                )
                self.graphs[self.spawn_step] = graph
            elif self.exploration_class.branch_comparison_strategy == "minimal":
                # TODO very few connections, only used to avoid crash
                first_half = model_list[: int(len(model_list) / 2)]
                second_half = model_list[int(len(model_list) / 2) :]
                pairs_to_compare = list(zip(first_half, second_half))
            else:
                pairs_to_compare = "all"

        elif not self.exploration_class.check_tree_pruned(prune_step=self.prune_step):
            self.prune_step += 1
            self.log_print(["Next layer - prune"])
            model_list, pairs_to_compare = self.exploration_class.tree_pruning(
                previous_prune_branch=kwargs["called_by_branch"]
            )
        else:
            self.log_print(
                ["Trying to generate next layer but neither pruning or spawning."]
            )

        model_list = list(set(model_list))
        model_list = [qmla.model_building_utilities.alph(mod) for mod in model_list]
        if isinstance(pairs_to_compare, list):
            pairs_to_compare = [(min(p), max(p)) for p in pairs_to_compare]
        return model_list, pairs_to_compare

    def finalise_tree(self, **kwargs):
        r"""
        After learning/pruning complete, run :meth:`~qmla.ExplorationStrategy.finalise_model_learning`.
        """

        last_branch = self.branches[max(self.branches.keys())]
        kwargs["evaluation_log_likelihoods"] = last_branch.evaluation_log_likelihoods
        kwargs["branch_model_points"] = last_branch.bayes_points

        self.exploration_class.finalise_model_learning(**kwargs)

    def nominate_champions(
        self,
    ):
        r"""
        After tree has completed, nominate champion(s) to contest for global champion.

        Exploration Strategies can nominate one or more models as global champion.
        The nominated champions of all ESs enter an all-vs-all contest
        in :meth:`~qmla.QuantumModelLearningAgent.compare_nominated_champions`,
        with the winner deemed the global champion.
        This tree object interfaces with the ES, so here it is just a wrapper for
        :meth:`~qmla.exploration_strategies.ExplorationStrategy.nominate_champions`.
        """
        return self.exploration_class.nominate_champions()

    def new_branch_on_tree(
        self,
        branch_id,
        models,
        pairs_to_compare,
        model_storage_instances,
        precomputed_models,
        spawning_branch,
        **kwargs
    ):
        r"""
        Add a branch to this tree.

        Generate a new :class:`~qmla.BranchQMLA`, and places the given models on it,
        and assign it to this tree. Return the object, so it can also act as a branch/layer in
        the :class:`~qmla.QuantumModelLearningAgent` environment.
        Note models can reside on multiple branches.

        :param int branch_id: branch ID unique to this branch and new in the QMLA environment.
        :param list models: model names to place on this branch.
        :param list pairs_to_compare: list of pairs of models to compare on this branch.
        :param dict model_storage_instances: :class:`~qmla.ModelInstanceForStorage` instances of
            each model id to be placed on this branch.
        :param list precomputed_models: models to place on branch
            which have already been learned on a previous branch.
        :param int spawning_branch: branch ID spawning this branch, to be recorded
            as the new branch's parent.
        :return BranchQMLA branch: instance of branch
        """

        # Instantiate branch
        branch = BranchQMLA(
            branch_id=branch_id,
            models=models,
            model_storage_instances=model_storage_instances,
            precomputed_models=precomputed_models,
            tree=self,
            spawning_branch=spawning_branch,
            pairs_to_compare=pairs_to_compare,
            **kwargs
        )

        # Update trees records
        self.branches[branch_id] = branch
        for m in model_storage_instances:
            self.model_storage_instances[m] = model_storage_instances[m]

        return branch

    ##########
    # Section: Inspect tree
    ##########

    def is_tree_complete(
        self,
    ):
        r"""
        Check if tree has completed and doesn't need any further branches.
        """

        # Check both spawning and pruning stages complete.
        tree_complete = self.exploration_class.check_tree_completed(
            spawn_step=self.spawn_step
        ) and self.exploration_class.check_tree_pruned(prune_step=self.prune_step)

        # If initially complete, don't need any further iterations.
        if self.exploration_class.tree_completed_initially:
            self.log_print(["Tree complete initially."])
            tree_complete = True

        self.log_print(["Checking if tree complete... ", tree_complete])

        return tree_complete

    ##########
    # Section: Utilities
    ##########

    def log_print(self, to_print_list):
        r"""Wrapper for :func:`~qmla.print_to_log`"""
        qmla.logging.print_to_log(
            to_print_list=to_print_list,
            log_file=self.log_file,
            log_identifier="Tree {}".format(self.exploration_strategy),
        )


class BranchQMLA:
    def __init__(
        self,
        branch_id,
        models,
        model_storage_instances,
        pairs_to_compare,
        tree,
        precomputed_models,
        spawning_branch,
    ):
        r"""
        Branch on which to group models.

        Branches simultenously belong to a :class:`~qmla.ExplorationTree` and the main
        :class:`~qmla.QuantumModelLearningAgent` environment, with the same ID on both.
        Sets of models reside on each branch. Models can reside on multiple branches.
        Models are instances of :class:`~qmla.ModelInstanceForStorage`.
        Branches are essentially a mechanism to group models within an exploration strategy.
        By default, all models on a branch are compared with each other, but it is
        possible to compare only a subset, e.g. during the tree pruning stage.
        Models on branches are learned via
        :meth:`~qmla.QuantumModelLearningAgent.learn_models_on_given_branch`;
        if a model was previously considered on another branch it is not learned again.
        Model comparisons for the branch are performed by
        :meth:`~qmla.QuantumModelLearningAgent.compare_models_within_branch`.

        :param int branch_id: branch ID unique to this branch and new in the QMLA environment.
        :param list models: model names to place on this branch.
        :param dict model_storage_instances: :class:`~qmla.ModelInstanceForStorage` instances of
            each model id to be placed on this branch.
        :param list pairs_to_compare: list of pairs of models to compare on this branch.
        :param ExplorationTree tree: tree to which this branch is associated.
        :param list precomputed_models: models to place on branch
            which have already been learned on a previous branch.
        :param int spawning_branch: branch ID spawning this branch, to be recorded
            as the new branch's parent.
        """

        self.branch_id = branch_id

        # Get attributes from this branch's tree
        self.tree = tree
        self.log_file = self.tree.log_file
        self.exploration_class = self.tree.exploration_class
        self.exploration_strategy = self.exploration_class.exploration_rules

        self.log_print(
            [
                "Branch {} on tree {}".format(self.branch_id, self.tree),
            ]
        )

        # Get parent branch of this branch
        try:
            self.parent_branch = self.tree.branches[spawning_branch]
            self.log_print(
                [
                    "Setting parent branch of {} -> parent is {}".format(
                        self.branch_id, self.parent_branch.branch_id
                    )
                ]
            )
        except BaseException:
            self.parent_branch = None
            self.log_print(["Failed to set parent branch for ", branch_id])

        # Models to place on the branch
        # TODO tidy up how models passed etc. (currently a bit redundant)
        self.model_storage_instances = model_storage_instances
        self.models = models
        self.models_by_id = models
        self.model_id_by_name = {self.models_by_id[m]: m for m in self.models_by_id}
        self.resident_model_ids = sorted(self.models_by_id.keys())
        self.resident_models = list(self.models_by_id.values())
        self.num_models = len(self.resident_models)

        # Choose models to compare within this branch
        if pairs_to_compare == "all":
            self.log_print(["All pairs to be compared on branch ", self.branch_id])
            self.pairs_to_compare = list(
                itertools.combinations(self.resident_model_ids, 2)
            )
        else:
            self.log_print(["Comparison pairs passed:", pairs_to_compare])
            self.pairs_to_compare = pairs_to_compare
        # order pairs so they read (low, high)
        self.pairs_to_compare = [(min(p), max(p)) for p in self.pairs_to_compare]
        self.num_model_pairs = len(self.pairs_to_compare)

        # Models already considered on a previous branch
        self.precomputed_models = precomputed_models
        self.num_precomputed_models = len(self.precomputed_models)
        self.unlearned_models = list(
            set(self.resident_models) - set(self.precomputed_models)
        )

        # Interface with QMLA: attributes tp be called/edited continuously
        self.model_learning_complete = False
        self.comparisons_complete = False
        self.bayes_points = {}
        self.rankings = []  # ordered from best to worst
        self.result_counter = 0

        self.log_print(
            ["New branch {}; models: {}".format(self.branch_id, self.models)]
        )

    ##########
    # Section: Interact with QMLA instance
    ##########

    def update_branch(self, pair_list, models_points=None):
        r"""
        Process results for this branch.

        :param list pair_list: pairs of models which were compared on this branch
        :param dict models_points: results of comparisons
        """

        self.log_print(
            ["Updating branch {}. \n pair_list: {}".format(self.branch_id, pair_list)]
        )
        # Track calls to this method for this branch
        self.result_counter += 1

        if self.result_counter == 1:
            # TODO should not be using bayes_points anywhere
            self.bayes_points = models_points
            self.evaluation_log_likelihoods = {
                k: self.model_storage_instances[k].evaluation_log_likelihood
                for k in self.resident_model_ids
            }
        else:
            self.log_print(
                [
                    "Reconsidering branch {} [{} considerations so far] champion with pairs {}".format(
                        self.branch_id, self.result_counter, pair_list
                    )
                ]
            )

        # Inspect the pairwise comparisons;
        pair_list = [(int(min(pair)), int(max(pair))) for pair in pair_list]
        bayes_factors = {
            pair: self.model_storage_instances[min(pair)].model_bayes_factors[
                max(pair)
            ][-1]
            for pair in pair_list
        }

        # Update the ES ratings system
        self.log_print(["Updating ratings for branch {}".format(self.branch_id)])
        self.exploration_class.ratings_class.batch_update(
            model_pairs_bayes_factors=bayes_factors,
            spawn_step=self.tree.spawn_step,
            force_new_rating=True,  # try to force new ratings
        )

        # Use exploration strategy's reasoning to decide if a champion can be set
        self.log_print(["Selecting champion(s) for branch {}".format(self.branch_id)])
        if (
            self.exploration_class.branch_champion_selection_stratgey
            == "number_comparison_wins"
        ):
            self.log_print(["Choosing champion from number of wins on branch."])

            max_points = max(models_points.values())
            models_with_max_points = [
                key for key, val in models_points.items() if val == max_points
            ]

            if len(models_with_max_points) > 1:
                # if multiple models have same number of wins,
                # can't declare a branch champion yet
                self.log_print(
                    [
                        "Multiple models have same number of points within branch {}:\n{} \nPoints:\n{}".format(
                            self.branch_id, models_with_max_points, models_points
                        )
                    ]
                )
                # Set joint champions so QMLA can re-compare the subset
                self.joint_branch_champions = models_with_max_points
                self.is_branch_champion_set = False
                # return
            else:
                # champion is model with most points
                self.ranked_models = sorted(
                    models_points, key=models_points.get, reverse=True
                )
                # TODO rankings for models should be set as they are distinguished
                # ie 10 models at first which are reduced to a competition bw 3,
                # rankings for models 4-10 should be set at first call.
                self.is_branch_champion_set = True
                self.joint_branch_champions = None

        elif self.exploration_class.branch_champion_selection_stratgey == "ratings":
            # TODO check if multiple models have exactly same rating (unlikely)
            self.ranked_models = self.exploration_class.ratings_class.get_rankings(
                model_list=self.resident_model_ids
            )
            self.log_print(["Champion set by ratings"])
            self.is_branch_champion_set = True

        elif self.exploration_class.branch_champion_selection_stratgey == "fitness":
            # using a genetic algorithm - so we can now analyse the generation because it has finished
            ranked_models_by_name = self.exploration_class.analyse_generation(
                model_points=models_points,
                model_names_ids=self.models_by_id,
            )
            self.log_print(
                [
                    "ranked_models_by_name:",
                    ranked_models_by_name,
                    "\n model IDs:\n",
                    self.model_id_by_name,
                ]
            )
            self.ranked_models = [
                self.model_id_by_name[m] for m in ranked_models_by_name
            ]  # get id from name
            self.log_print(
                ["Champion set by fitness. Ranked models:", self.ranked_models]
            )
            self.is_branch_champion_set = True

        if self.result_counter > 1 and not self.is_branch_champion_set:
            self.log_print(
                [
                    "On branch {}, no outright champion after {} considerations. \
                    Forcing selection.".format(
                        self.branch_id, self.result_counter
                    )
                ]
            )
            self.is_branch_champion_set = True
            self.ranked_models = sorted(
                models_points, key=models_points.get, reverse=True
            )

        # Update branch with results of competition
        if self.is_branch_champion_set:
            self.champion_id = int(self.ranked_models[0])
            self.champion_name = self.models[self.champion_id]
            self.log_print(
                ["Branch {} champion ID: {}".format(self.branch_id, self.champion_id)]
            )

    ##########
    # Section: Utilities
    ##########

    def log_print(self, to_print_list):
        qmla.logging.print_to_log(
            to_print_list=to_print_list,
            log_file=self.log_file,
            log_identifier="Branch {}".format(self.branch_id),
        )
