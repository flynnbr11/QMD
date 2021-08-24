import numpy as np
import argparse
from matplotlib.lines import Line2D
import sys
import os
import pickle
import matplotlib.pyplot as plt
import pandas
import warnings

plt.switch_backend('agg')
sys.path.append(
    os.path.abspath(
        os.path.join(os.path.dirname( __file__ ), '..')
    )
)
import qmla
import qmla.analysis

parser = argparse.ArgumentParser(
    description='Pass variables for QMLA.'
)

# Add parser arguments, ie command line arguments

parser.add_argument(
    '-dir', '--results_directory',
    help="Directory where results of multiple QMD are held.",
    type=str,
    default=os.getcwd()
)
parser.add_argument(
    '-log', '--log_file',
    help='File to log RQ workers.',
    type=str,
    default='.default_qmd_log.log'
)

parser.add_argument(
    '-bcsv', '--bayes_csv',
    help="CSV given to QMD to store all Bayes factors computed.",
    type=str,
    default=os.getcwd()
)

parser.add_argument(
    '-top', '--top_number_models',
    help="N, for top N models by number of QMD wins.",
    type=int,
    default=3
)

parser.add_argument(
    '-qhl', '--qhl_mode',
    help="Whether QMD is being used in QHL mode.",
    type=int,
    default=0
)

parser.add_argument(
    '-fqhl', '--further_qhl_mode',
    help="Whether in further QHL stage.",
    type=int,
    default=0
)

parser.add_argument(
    '-runinfo', '--run_info_file',
    help="Path to pickled true params info.",
    type=str,
    default=None
)

parser.add_argument(
    '-sysmeas', '--system_measurements_file',
    help="Path to pickled true expectation values.",
    type=str,
    default=None
)

parser.add_argument(
    '-es', '--exploration_rules',
    help='Rule applied for generation of new models during QMD. \
    Corresponding functions must be built into model_generation',
    type=str,
    default=None
)
parser.add_argument(
    '-gs', '--gather_summary_results',
    help="Unpickle all results files and \
        compile into single file. \
        Don't want to do this if already compiled.",
    type=int,
    default=1
)

parser.add_argument(
    '-latex', '--latex_mapping_file',
    help='File path to save tuples which give model \
        string names and latex names.',
    type=str,
    default=None
)
parser.add_argument(
    '-plotprobes', '--probes_plot_file',
    help="File to pickle probes against which to plot expectation values.",
    type=str,
    default=None
)
parser.add_argument(
    '-ff', '--figure_format',
    help="Format of figures generated.",
    type=str,
    default="png"
)


# Parse command line arguments
arguments = parser.parse_args()

# Format inputs for use in this script
directory_to_analyse = arguments.results_directory
log_file = arguments.log_file
all_bayes_csv = arguments.bayes_csv
qhl_mode = bool(arguments.qhl_mode)
further_qhl_mode = bool(arguments.further_qhl_mode)
run_info_file = arguments.run_info_file
system_measurements_file = arguments.system_measurements_file
exploration_rule = arguments.exploration_rules
gather_summary_results = bool(arguments.gather_summary_results)
true_exploration_class = qmla.get_exploration_class(
    exploration_rules=exploration_rule,
    true_params_path=arguments.run_info_file,
    plot_probes_path=arguments.probes_plot_file,
    log_file=log_file
)
true_exploration_class.get_true_parameters()
latex_mapping_file = arguments.latex_mapping_file
figure_format = arguments.figure_format
probes_plot_file = arguments.probes_plot_file
results_collection_file = "{}/collect_analyses.p".format(
    directory_to_analyse
)

if run_info_file is not None:
    true_params_info = pickle.load(
        open(
            run_info_file,
            'rb'
        )
    )
    true_params_dict = true_params_info['params_dict']
    true_model = true_params_info['true_model']
else:
    true_params_dict = None
    true_model = true_exploration_class.true_model
true_model_latex = true_exploration_class.latex_name(
    true_model
)
if not directory_to_analyse.endswith('/'):
    directory_to_analyse += '/'

# Directories to store analyses in
results_directories = {
    'exploration_strategy' : os.path.join(directory_to_analyse, 'exploration_strategy_plots'),
    'meta' : os.path.join(directory_to_analyse, 'meta'),
    'champions' : os.path.join(directory_to_analyse, 'champion_models'),
    'performance' : os.path.join(directory_to_analyse, 'performance'),
    'combined_datasets' : os.path.join(directory_to_analyse, 'combined_datasets')
}
for d in results_directories.values():
    if not os.path.exists(d):
        try:
            os.makedirs(d)
        except:
            pass


# Generate results' file names etc depending 
# on what type of QMLA was run
if further_qhl_mode == True:
    results_csv_name = 'summary_further_qhl_results.csv'
    results_csv = directory_to_analyse + results_csv_name
    results_file_name_start = 'further_qhl_results'
    plot_desc = 'further_'
else:
    results_csv_name = 'combined_results.csv'
    results_csv = directory_to_analyse + results_csv_name
    results_file_name_start = 'results'
    plot_desc = ''

# Preliminary analysis 
os.chdir(directory_to_analyse)
pickled_files = []
for file in os.listdir(directory_to_analyse):
    if (
        file.endswith(".p")
        and file.startswith(results_file_name_start)
    ):
        pickled_files.append(file)

exploration_strategies = {}
for f in pickled_files:
    fname = directory_to_analyse + '/' + str(f)
    result = pickle.load(open(fname, 'rb'))
    alph = result['NameAlphabetical']
    if alph not in list(exploration_strategies.keys()):
        exploration_strategies[alph] = result['ExplorationRule']

unique_exploration_classes = {}
unique_exploration_strategies = true_params_info['all_exploration_strategies']
for g in unique_exploration_strategies:
    try:
        unique_exploration_classes[g] = qmla.get_exploration_class(
            exploration_rules=g,
            true_params_path=arguments.run_info_file,
            plot_probes_path=arguments.probes_plot_file,
            log_file=log_file
        )
        unique_exploration_classes[g].get_true_parameters()
    except BaseException:
        unique_exploration_classes[g] = None

# First get model scores (number of wins per model)
model_score_results = qmla.analysis.get_model_scores(
    directory_name=directory_to_analyse,
    unique_exploration_classes=unique_exploration_classes,
    collective_analysis_pickle_file=results_collection_file,
)
model_scores = model_score_results['scores']
exploration_strategies = model_score_results['exploration_strategies']
exploration_classes = model_score_results['exploration_classes']
unique_exploration_classes = model_score_results['unique_exploration_classes']
median_coeff_determination = model_score_results['avg_coeff_determination']
f_scores = model_score_results['f_scores']
latex_coeff_det = model_score_results['latex_coeff_det']
pickle.dump(
    model_score_results, 
    open(
        os.path.join(
            results_directories['champions'], 
            'champions_info.p'
        ), 'wb'
    )
)
# Rearrange some results... TODO this could be tidier/removed?
models = sorted(model_score_results['wins'].keys())
models.reverse()

f_score = {
    'title': 'F-score',
    'res': [model_score_results['f_scores'][m] for m in models],
    'range': 'cap_1',
}
r_squared = {
    'title': '$R^2$',
    'res': [model_score_results['latex_coeff_det'][m] for m in models],
    'range': 'cap_1',
}

sensitivity = {
    'title': 'Sensitivity',
    'res': [model_score_results['sensitivities'][m] for m in models],
    'range': 'cap_1',
}
precision = {
    'title': 'Precision',
    'res': [model_score_results['precisions'][m] for m in models],
    'range': 'cap_1',
}
wins = {
    'title': 'Number Wins',
    'res': [model_score_results['wins'][m] for m in models],
    'range': 'uncapped',
}


#######################################
# Analyse the results according to various available analyses
#######################################

print("\nAnalysing and storing results in", directory_to_analyse)

#######################################
# Gather results
#######################################


if gather_summary_results: 
    # Collect results together into single file. 
    # don't want to waste time doing this if already compiled
    # so gather_summary_results can be set to 0 in analysis script.
    combined_results = qmla.analysis.collect_results_store_csv(
        directory_name = directory_to_analyse,
        results_file_name_start = results_file_name_start,
        results_csv_name = results_csv_name, 
    )

    try:
        datasets_generated = qmla.analysis.generate_combined_datasets(
            combined_datasets_directory =  results_directories['combined_datasets'],
            directory_name = directory_to_analyse,
        )
    except:
        print("ANALYSIS FAILURE: Generate combined dataset.")
        raise

    try:
        qmla.analysis.cross_instance_bayes_factor_heatmap(
            combined_datasets_directory = results_directories['combined_datasets'],
            save_directory = results_directories['performance']
        )
    except:
        print("ANALYSIS FAILURE: Bayes factor heatmap.")
        pass

    try:
        qmla.analysis.correlation_fitness_f_score(
            combined_datasets_directory = results_directories['combined_datasets'],
            save_directory = results_directories['exploration_strategy']
        )
    except:
        print("ANALYSIS FAILURE: Correlation plot b/w fitness and F-score.")
        # raise
        pass        
        
    # Find number of occurences of each model
    # quite costly so it is optional
    plot_num_model_occurences = False 
    if plot_num_model_occurences:
        try:
            qmla.analysis.count_model_occurences(
                latex_map=latex_mapping_file,
                true_model_latex=true_exploration_class.latex_name(
                    true_model
                ),
                save_counts_dict=str(
                    directory_to_analyse +
                    "count_model_occurences.p"
                ),
                save_to_file=str(
                    directory_to_analyse +
                    "occurences_of_models.png"
                )
            )
        except BaseException:
            print("ANALYSIS FAILURE: number of occurences for each model.")
            raise
else:
    combined_results = pandas.read_csv(
        os.path.join(directory_to_analyse, results_csv_name)
    )

#######################################
# results/Outputs
## Dynamics
#######################################
try:
    qmla.analysis.plot_dynamics_multiple_models(  # average expected values
        directory_name=directory_to_analyse,
        # dataset=dataset,
        results_path=results_csv,
        results_file_name_start=results_file_name_start,
        true_expectation_value_path=system_measurements_file,
        exploration_rule=exploration_rule,
        unique_exploration_classes=unique_exploration_classes,
        top_number_models=arguments.top_number_models,
        probes_plot_file=probes_plot_file,
        collective_analysis_pickle_file=results_collection_file,
        save_to_file=os.path.join(
            results_directories['performance'], 
            str(plot_desc + 'dynamics')
        ),
        figure_format=figure_format
    )
except:
    print("ANALYSIS FAILURE: dynamics.")
    raise

#####

#######################################
# Parameter analysis
#######################################

try:
    qmla.analysis.plot_terms_and_parameters(
        results_path = directory_to_analyse, 
        save_to_file = os.path.join(
            directory_to_analyse, 
            "champion_models", 
            "terms_and_params"),
        figure_format=figure_format
    )
except Exception as e:
    print("ANALYSIS FAILURE {} with exception {}".format("plot_terms_and_parameters", e))

try:
    # Get average parameters of champion models across instances
    average_priors = qmla.analysis.average_parameters_across_instances(
        results_path=results_csv,
        top_number_models=arguments.top_number_models,
        file_to_store = os.path.join(
            directory_to_analyse, 
            'average_priors.p'
        )
    )
except BaseException:
    print("ANALYSIS FAILURE: finding average parameters across instances.")
    # raise

try:
    qmla.analysis.average_parameter_estimates(
        directory_name=directory_to_analyse,
        results_path=results_csv,
        top_number_models=arguments.top_number_models,
        results_file_name_start=results_file_name_start,
        exploration_rule=exploration_rule,
        unique_exploration_classes=unique_exploration_classes,
        true_params_dict=true_params_dict,
        save_to_file=os.path.join(
            directory_to_analyse,
            "{}param_avg".format('param_avg')
        ),
        save_directory = results_directories['champions'],
        figure_format=figure_format
    )
except:
    print("ANALYSIS FAILURE: average parameter plots.")
    # raise

# Cluster champion learned parameters.
try:
    qmla.analysis.cluster_results_and_plot(
        path_to_results=results_csv,
        true_expec_path=system_measurements_file,
        plot_probe_path=probes_plot_file,
        true_params_path=run_info_file,
        exploration_rule=exploration_rule,
        save_param_values_to_file=str(
            plot_desc + 'clusters_by_param.png'),
        save_param_clusters_to_file=str(
            plot_desc + 'clusters_by_model.png'),
        save_redrawn_expectation_values=str(
            plot_desc + 'clusters_expec_vals.png'),
        plot_prefix = plot_desc, 
        save_directory = results_directories['champions'], 
    )
except BaseException:
    print("ANALYSIS FAILURE: clustering plots.")


#######################################
# QMLA Performance
## model win rates and statistics
#######################################
# Model number of wins
try:
    qmla.analysis.plot_scores(
        scores=model_scores,
        exploration_classes=exploration_classes,
        unique_exploration_classes=unique_exploration_classes,
        exploration_strategies=exploration_strategies,
        plot_r_squared=False,
        coefficients_of_determination=median_coeff_determination,
        coefficient_determination_latex_name=latex_coeff_det,
        f_scores=f_scores,
        true_model=true_model,
        exploration_rule=exploration_rule,
        save_file=os.path.join(results_directories['performance'], 'model_wins'),
        figure_format=figure_format,
    )
except:
    print("ANALYSIS FAILURE: plotting model win rates.")
    raise
    # pass

# Model statistics (f-score, precision, sensitivty)
try:
    qmla.analysis.plot_statistics(
        to_plot = [wins, f_score, precision, sensitivity],
        models = models,
        true_model=true_model_latex,
        save_to_file = os.path.join(
            results_directories['performance'], 
            'model_statistics.png'
        )        
    )
except:
    print("ANALYSIS FAILURE: plotting model statistics.")
    raise

try:
    qmla.analysis.count_term_occurences(
        combined_results = combined_results, 
        save_directory = results_directories['performance']
    )
except:
    print("ANALYSIS FAILURE: Counting term occurences.")
    raise


# Evaluation: log likelihoods of considered models, compared with champion/true
try:
    qmla.analysis.plot_evaluation_log_likelihoods(
        combined_results = combined_results, 
        save_directory = results_directories['performance'],
        include_median_likelihood=False, 
    )
except: 
    print("ANALYSIS FAILURE: Evaluation log likleihoods.")
    pass

# inspect how nodes perform
try:
    qmla.analysis.inspect_times_on_nodes(
        combined_results = combined_results, 
        save_directory = results_directories['meta'],
    )
except: 
    print("ANALYSIS FAILURE: Time inspection of nodes.")
    pass
    # raise


# model statistics histograms (f-score, precision, sensitivty)
try:
    # Plot metrics such as F1 score histogram
    qmla.analysis.stat_metrics_histograms(
        champ_info = model_score_results, 
        save_to_file=os.path.join(
            results_directories['performance'], 
            'metrics.png'
        )
    )
except: 
    print("ANALYSIS FAILURE: statistical metrics")
    raise

# Summarise results into txt file for quick checking results. 
try:
    qmla.analysis.summarise_qmla_text_file(
        results_csv_path = results_csv, 
        path_to_summary_file = os.path.join(
            directory_to_analyse, 
            'summary.txt'
        )
    )
except:
    print("ANALYSIS FAILURE: summarising txt")
    raise

#######################################
# QMLA Internals
## How QMLA proceeds 
## metrics at each layer
## Quadratic losses, R^2, volume at each experiment
## 
#######################################
try:
    qmla.analysis.generational_analysis(
        combined_results = combined_results, 
        save_directory = results_directories['exploration_strategy'],
    )
except:
    print("ANALYSIS FAILURE: generational analysis.")
    pass

try:
    qmla.analysis.r_sqaured_average(
        results_path=results_csv,
        exploration_class=true_exploration_class,
        top_number_models=arguments.top_number_models,
        all_exploration_classes=exploration_classes,
        save_to_file = os.path.join(
            results_directories['champions'], 
            str(plot_desc + 'r_squared_avg.png')
        )
    )
except BaseException:
    print(
        "ANALYSIS FAILURE: R^2 against epochs.",
        "R^2 at each epoch not stored in QMLA output (method available in QML)."
    )
    pass

try:
    qmla.analysis.average_quadratic_losses(
        results_path=results_csv,
        exploration_classes=unique_exploration_classes,
        exploration_rule=exploration_rule,
        top_number_models=arguments.top_number_models,
        save_to_file = os.path.join(
            results_directories['champions'], 
            str( plot_desc + 'quadratic_losses.png')
        )
    )
except Exception as e:
    print("ANAYSIS FAILURE: {} with exception {}".format(
        "average_quadratic_losses", 
        e
    ))

try:
    qmla.analysis.volume_average(
        results_path=results_csv,
        exploration_class=true_exploration_class,
        top_number_models=arguments.top_number_models,
        save_to_file = os.path.join(
            results_directories['performance'], 
            str(plot_desc + 'volumes.png')
        )
    )
except Exception as e:
    print("ANAYSIS FAILURE: {} with exception {}".format(
        "volume_average", e
    ))
    pass

try:
    qmla.analysis.all_times_learned_histogram(
        results_path=results_csv,
        top_number_models=arguments.top_number_models,
        save_to_file=os.path.join(
            results_directories['performance'], 
            str(plot_desc + 'times_learned_upon.png')
        )
    )
except:
    print("ANALYSIS FAILURE: times learned upon.")



#######################################
# Exploration Strategy specific 
## genetic algorithm ananlytics
#######################################

# if model space is too big this takes too long, so optional
include_model_generation_plots = False 

try: 
    if include_model_generation_plots:
        unique_chromosomes = pandas.read_csv(
            os.path.join(results_directories['combined_datasets'], 'unique_chromosomes.csv')
        )
        qmla.analysis.model_generation_probability(
            combined_results = combined_results,
            unique_chromosomes = unique_chromosomes, 
            save_directory = results_directories['performance'], 
        )
except:
    print("ANALYSIS FAILURE: [gentic algorithm] Model generation rate.")
    pass
    # raise


try:
    qmla.analysis.genetic_alg_fitness_plots(
        combined_datasets_directory= results_directories['combined_datasets'],
        save_directory = results_directories['exploration_strategy'],
    )
except:
    print("ANALYSIS FAILURE: [genetic algorithm] Fitness measures.")
    pass


##################################
# Tree representing all QMLA instances
#######################################
try:
    tree_plot_log = str(directory_to_analyse + 'tree_plot_log.txt')
    attempt_tree_plot = False
    if attempt_tree_plot:
        sys.stdout = open(
            tree_plot_log, 'w'
        )

        qmla.analysis.plot_tree_multiple_instances(
            results_csv=results_csv,
            latex_mapping_file=latex_mapping_file,
            avg_type='medians',
            all_bayes_csv=all_bayes_csv,
            exploration_rule=exploration_rule,
            entropy=0,
            inf_gain=0,
            save_to_file=os.path.join(
                results_directories['performance'], 
                'DAG_multi_qmla.png'
            )
        )

        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

except ValueError:
    pass
except Exception as exc:
    print("Error plotting multi QMLA tree.")
    print(exc)
    pass

except NameError:
    print(
        "Can not plot multiQMD tree -- this might be because only \
        one instance of QMD was performed. All other plots generated \
        without error."
    )
    pass

except ZeroDivisionError:
    print(
        "Can not plot multiQMD tree -- this might be because only \
        one instance of QMD was performed. All other plots generated \
        without error."
    )
    pass
except BaseException:
    pass