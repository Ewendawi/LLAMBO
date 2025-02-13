import json
import uuid
from datetime import datetime
import logging
import pickle
import os
from matplotlib import pyplot as plt
import numpy as np
from scipy.signal import savgol_filter 
from scipy.ndimage import gaussian_filter1d  
import pandas as pd
from pandas.api.types import is_numeric_dtype
from .population.population import Population, desc_similarity
from .individual import Individual

class NoCodeException(Exception):
    """Could not extract generated code."""

class BOOverBudgetException(Exception):
    """Exceeded the budget for the number of evaluations."""

def handle_timeout(signum, frame):
    raise TimeoutError

#========================================
#Logger
#========================================
class CustomFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: grey + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

def setup_logger(logger = None, level=logging.INFO, filename=None):
    if logger is None:
        logger = logging.getLogger()
    logger.setLevel(level)
    if filename:
        fh = logging.FileHandler(filename)
        fh.setLevel(level)
        logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(CustomFormatter())
    logger.addHandler(ch)
    return logger

def get_logger(name = None, level=logging.INFO, filename=None):
    logger = logging.getLogger(name)
    setup_logger(logger, level, filename)
    return logger

class LogggerJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if hasattr(o, '__to_json__'):
            return o.__to_json__()
        return super().default(o)

class IndividualLogger:
    def __init__(self):
        self.individual_map:dict[str, Individual] = {}
        self.experiment_map:dict[str, dict] = {}
        self._file_name = "individual_set"
        self.dirname = "logs"

    @property
    def file_name(self):
        return self._file_name

    @file_name.setter
    def file_name(self, value):
        new_value = value
        if value is not None:
            new_value = value.replace(" ", "")
            new_value = new_value.replace(":", "_")
            new_value = new_value.replace("/", "_")
        self._file_name = new_value

    def log_individual(self, individual):
        self.individual_map[individual.id] = individual

    def get_individual(self, ind_id):
        return self.individual_map.get(ind_id, None)

    def log_experiment(self, name, id_list):
        exp_id = str(uuid.uuid4())
        experiment = {
            "id": exp_id,
            "name": name,
            "id_list": id_list
        }
        self.experiment_map[exp_id] = experiment

    def get_experiment(self, experiment_id):
        return self.experiment_map.get(experiment_id, None)

    def save(self, filename=None, dirname=None):
        if dirname is None:
            dirname = self.dirname
        if not os.path.exists(dirname):
            os.mkdir(dirname)
        if filename is None:
            filename = self.file_name
        filename = filename.replace(" ", "")
        filename = filename.replace(":", "_")
        filename = filename.replace("/", "_")
        time_stamp = datetime.now().strftime("%m%d%H%M%S")
        filename = os.path.join(dirname, f"{filename}_{time_stamp}.pkl")
        with open(filename, "wb") as f:
            pickle.dump((self.individual_map,self.experiment_map), f)

    def get_successful_individuals(self):
        successful_individuals = []
        for _, individual in self.individual_map.items():
            if isinstance(individual, dict):
                # No longer compatible with older formats
                continue
            if individual.error is None and "deprecated" not in individual.metadata:
                successful_individuals.append(individual)
        return successful_individuals

    def get_failed_individuals(self, error_type=None):
        failed_individuals = []
        for _, individual in self.individual_map.items():
            if isinstance(individual, dict):
                # No longer compatible with older formats
                continue
            if individual.error is None or "deprecated" in individual.metadata:
                continue
            if (error_type is None or individual.metadata["error_type"] == error_type):
                failed_individuals.append(individual)
        return failed_individuals

# {
#     "contents": {
#         "<id>": {
#             "id": "",
#             "solution": "", // code block
#             "name": "",
#             "description": "", // desc block, markdown
#             "fitness": "",
#             "feedback": "", // feedback and error block, markdown
#             "error": "",
#             "parent_id": "",
#             "metadata": {
#                 "error_type": "", // single-choice filter
#                 "model": "", // single-choice filter
#                 "prompt": "", // prompt block, foldable
#                 "raw_response": "", // response block, markdown
#                 "problem": "", // single-choice filter
#                 "tags": [] // multiple-choice filter
#             }
#         }
#     },
#     "experiments": {
#         "<experiment_id>": {
#             "id": "", // single-choice filter. retrieve all the content in the id_list.
#             "name": "",
#             "id_list": [] // id: content_id
#         }
#     }
# }

    def save_reader_format(self, filename=None):
        json_str = self.covert_to_reader_format()
        time_stamp = datetime.now().strftime("%m%d%H%M%S")
        if filename is None:
            filename = self.file_name
        filename = filename.replace(" ", "")
        filename = filename.replace(":", "_")
        filename = filename.replace("/", "_")
        filepath = os.path.join(self.dirname, f"reader_format_{filename}_{time_stamp}.json")
        with open(f"{filepath}", "w", encoding="utf-8") as f:
            f.write(json_str)

    def covert_to_reader_format(self) -> str:
        reader_format = {
            "experiments": self.experiment_map.copy()
        }
        contents = {}
        for ind_id, individual in self.individual_map.items():
            contents[ind_id] = individual
            handler = Population.get_handler_from_individual(individual)
            individual.metadata["raw_response"] = handler.raw_response
            individual.metadata["prompt"] = handler.prompt

        reader_format["contents"] = contents

        for _, individual in reader_format["contents"].items():
            individual.metadata["language"]= "python"

        json_str = json.dumps(reader_format, indent=4, cls=LogggerJSONEncoder)
        return json_str

    @classmethod
    def load(cls, filepath=None):

        if filepath is None and not os.path.exists(filepath):
            return None
        logger = cls()
        if filepath is None:
            return
        if os.path.exists(filepath):
            with open(filepath, "rb") as f:
                logger.individual_map, logger.experiment_map = pickle.load(f)
        else:
            raise FileNotFoundError(f"File {filepath} not found")
        return logger

    @classmethod
    def merge_logs(cls, log_dir, save=True):
        # check if the log_dir is a directory
        if not os.path.isdir(log_dir):
            return None

        log_files = [os.path.join(log_dir, f) for f in os.listdir(log_dir) if f.endswith(".pkl")]
        loggers = []
        for log_file in log_files:
            logger = cls().load(log_file)
            loggers.append(logger)
        merged_logger = cls()
        for logger in loggers:
            merged_logger.individual_map.update(logger.individual_map)
            merged_logger.experiment_map.update(logger.experiment_map)
        if save:
            merged_logger.save()
        return merged_logger


    def replace_metadata_key(self, old_key, new_key):
        for _, ind in self.individual_map.items():
            if old_key in ind.metadata:
                ind.metadata[new_key] = ind.metadata[old_key]
                del ind.metadata[old_key]

# Plotting

# Moving Average Smoothing
def moving_average(data, window_size):
    window = np.ones(window_size) / window_size
    if len(data.shape) == 1:
        return np.convolve(data, window, mode='same')
    else:
        return np.array([np.convolve(data[i], window, mode='same') for i in range(data.shape[0])])


# Savitzky-Golay Filter (preserves peaks)
def savgol_smoothing(data, window_size, polyorder):
    """
    window_size: The length of the filter window. Must be odd.
    polyorder: The order of the polynomial used to fit the samples. Must be less than window_size.
    """
    try:
        return savgol_filter(data, window_size, polyorder)
    except ValueError as e:
        print(f"Savitzky-Golay error: {e}.  Ensure window_size is odd and larger than polyorder.")
        return data  # Return original if error


# Gaussian Smoothing (Good for general smoothing)
def gaussian_smoothing(data, sigma):
    """
    sigma: The standard deviation of the Gaussian kernel.  Larger sigma = more smoothing.
    """
    return gaussian_filter1d(data, sigma)


def plot_lines(y:list[np.ndarray], x:list[np.ndarray],

                labels:list[list[str]],
                label_fontsize:int = 7,

                filling:list[np.ndarray]=None, 
                linewidth:float = 1.0,

                colors:list[list]=None,
                
                y_scales:list[tuple[str, dict]]=None,

                x_dot:list[np.ndarray]=None,

                x_labels:list[str]=None, y_labels:list[str]=None, 

                sub_titles:list[str]=None,
                sub_title_fontsize:int = 10,

                baselines:np.ndarray=None, baseline_labels:list[list[str]]=None, 

                title:str = None,
                title_fontsize:int = 12, 
                caption:str = None, caption_fontsize:int = 10,

                filename:str = None, 
                n_cols:int = 1, figsize:tuple[int,int] = (10, 6), 
                show:bool = True):
    
    # y.shape = (n_plots, n_lines, n_points)
    if len(labels) != len(y):
        logging.warning("PLOT:Number of labels does not match the number of plots.")
    
    if x_labels is not None and len(x_labels) != len(y):
        logging.warning("PLOT:Number of x_labels does not match the number of plots.")
    
    if y_labels is not None and len(y_labels) != len(y):
        logging.warning("PLOT:Number of y_labels does not match the number of plots.")

    if sub_titles is not None and len(sub_titles) != len(y):
        logging.warning("PLOT:Number of sub_titles does not match the number of plots.")

    n_plots = len(y)
    n_cols = min(n_cols, n_plots)
    n_rows = n_plots // n_cols 
    if n_plots % n_cols != 0:
        n_rows += 1

    axs_ids = []
    for row in range(n_rows):
        row_ids = []
        for col in range(n_cols):
            row_ids.append(row * n_cols + col)
        axs_ids.append(row_ids)
    fig, axs = plt.subplot_mosaic(axs_ids, figsize=figsize)
    for i in range(n_plots):
        row = i // n_cols
        col = i % n_cols
        ax = axs[i]

        _x = x[i]
        _y = y[i]
        ax.ticklabel_format(axis='y', style='sci', scilimits=(-3,3))

        if y_scales is not None and len(y_scales) > i and y_scales[i] is not None:
            scale, scale_kwargs = y_scales[i] 
            ax.set_yscale(scale, **scale_kwargs)

        _labels = labels[i] if len(labels) > i else []
        _filling = filling[i] if filling is not None else None
        _x_dot = x_dot[i] if x_dot is not None else None
        _colors = colors[i] if colors is not None else None
        for j in range(_y.shape[0]):
            label = _labels[j] if len(_labels) > j else f"{j}"
            _color = _colors[j] if _colors is not None and len(_colors) > j else None
            ax.plot(_x, _y[j,:], label=label, linewidth=linewidth, color=_color)

            _color = _color if _color is not None else ax.get_lines()[-1].get_color()
            if _filling is not None:
                upper, lower = _filling[j]
                ax.fill_between(_x, lower, upper, alpha=0.3, color=_color)

            if _x_dot is not None and len(_x_dot) > j:
                _dot_x = _x_dot[j]
                _dot_y = _y[j][_dot_x]
                # if _dot_y is nan, look forward
                _step = 0
                _len = min(10, len(_y[j]) - _dot_x)
                while _step < _len and np.isnan(_dot_y):
                    _dot_y = _y[j][_dot_x + _step]
                    _step += 1
                # get the color from the line
                # color = ax.get_lines()[-1].get_color()
                _dot_x = _dot_x.astype(np.float64) + np.random.uniform(-0.2, 0.2, len(_dot_x))
                ax.scatter(_dot_x, _dot_y, facecolors='none', edgecolors=_color)
            
        _baseline = baselines[i] if baselines is not None else None
        if _baseline is not None:
            _bl_labels = baseline_labels[i] if len(baseline_labels) > i else []
            for j, base in enumerate(_baseline):
                label = _bl_labels[j] if len(_bl_labels) > j else f"{j}"
                ax.axhline(y=base, label=label, linestyle="--", color="black", linewidth=linewidth, alpha=0.6)

        ax.legend(fontsize=label_fontsize)
        ax.grid(True)

        if x_labels is not None:
            x_label = x_labels[i] if len(x_labels) > i else ""
            ax.set_xlabel(x_label)
        if y_labels is not None:
            y_label = y_labels[i] if len(y_labels) > i else ""
            ax.set_ylabel(y_label)
        if sub_titles is not None:
            sub_title = sub_titles[i] if len(sub_titles) > i else ""
            ax.set_title(sub_title, fontsize=sub_title_fontsize)

    if title:
        fig.suptitle(title, fontsize=title_fontsize)

    if caption:
        fig.text(0.5, -0.11, caption, ha='center', fontsize=caption_fontsize)
    
    if filename:
        plt.savefig(filename, dpi=300)

    fig.tight_layout()

    if show:
        plt.show(block=False)

def _plot_get_element_from_list(data, index, default=None):
    if isinstance(data, list) and len(data) > index:
        return data[index]
    return default

def plot_box_violin(
    data:list[np.ndarray],
    labels: list[list[str]], 
    long_labels: list[str] = None,
    label_fontsize:int = 7,
    sub_titles: list[str] = None,
    x_labels: list[str] = None,
    y_labels: list[str] = None,
    title = "", 
    plot_type:str = "violin",
    n_cols:int = 1, figsize:tuple[int,int] = (10, 6), 
    show:bool = True,
    filename=None):

    if len(labels) != len(data):
        logging.warning("PLOT:Number of labels does not match the number of plots.")
    if long_labels is not None and len(long_labels) != len(data):
        logging.warning("PLOT:Number of long_labels does not match the number of plots.")

    n_plots = len(data)
    n_cols = min(n_cols, n_plots)
    n_rows = n_plots // n_cols
    if n_plots % n_cols != 0:
        n_rows += 1

    axs_ids = []
    for row in range(n_rows):
        row_ids = []
        for col in range(n_cols):
            row_ids.append(row * n_cols + col)
        axs_ids.append(row_ids)
    fig, axs = plt.subplot_mosaic(axs_ids, figsize=figsize)

    for i in range(n_plots):
        row = i // n_cols
        col = i % n_cols
        ax = axs[i]

        sub_title = sub_titles[i] if sub_titles is not None else ""
        if plot_type == "violin":
            ax.violinplot(data[i], showmeans=False, showmedians=True)
        elif plot_type == "box":
            ax.boxplot(data[i])
        ax.set_title(sub_title)
        ax.yaxis.grid(True)
        _labels = _plot_get_element_from_list(labels, i, None) 
        if _labels is not None:
            ax.set_xticks([y + 1 for y in range(len(data[i]))], labels=_labels, fontsize=label_fontsize)
        _x_labels = _plot_get_element_from_list(x_labels, i, "")
        ax.set_xlabel(_x_labels, fontsize=label_fontsize)
        _y_labels = _plot_get_element_from_list(y_labels, i, "")
        ax.set_ylabel(_y_labels, fontsize=label_fontsize)
    
    fig.suptitle(title)
    fig.tight_layout()
    if filename:
        plt.savefig(filename, dpi=300)
    if show:
        plt.show(block=False)
        

from .evaluator.evaluator_result import EvaluatorResult

def dynamical_access(obj, attr_path):
    attrs = attr_path.split(".")
    target = obj
    for attr in attrs:
        target = getattr(target, attr, None)
        if target is None:
            break
    return target

def plot_search_result(results:list[tuple[str,Population]]):
    column_names = [
        'strategy',
        'problem_id',
        'instance_id',
        'exec_id',
        'n_gen',
        'n_iter',
        "log_y_aoc",
        "y_aoc",
        "best_y",
        'loss',
        ]

    def res_to_row(res, gen:int, strategy_name:str, n_iter:int):
        res_id = res.id
        res_split = res_id.split("-")
        problem_id = int(res_split[0])
        instance_id = int(res_split[1])
        repeat_id = int(res_split[2])
        row = {
            'strategy': strategy_name,
            'problem_id': problem_id,
            'instance_id': instance_id,
            'exec_id': repeat_id,
            'n_gen': gen+1,
            'n_iter': n_iter,
            "log_y_aoc": res.log_y_aoc,
            "y_aoc": res.y_aoc,
            "best_y": res.best_y,
            'loss': abs(res.optimal_value - res.best_y),
        }
        return row

        
    res_df = pd.DataFrame(columns=column_names)
    for strategy_name, pop in results:
        n_generation = pop.get_current_generation()
        n_iter = 0
        for gen in range(n_generation):
            # offspring generated in this generation
            gen_offsprings = pop.get_offsprings(generation=gen)
            n_iter += len(gen_offsprings)
            # offspring selected in this generation
            gen_inds = pop.get_individuals(generation=gen)
            for ind in gen_inds:
                handler = Population.get_handler_from_individual(ind)
                for res in handler.eval_result.result:
                    row = res_to_row(res, gen, strategy_name=strategy_name, n_iter=n_iter)
                    res_df.loc[len(res_df)] = row

    def _combine_acc(column='y_aoc', maximum=True):
        def _inner_combine_acc(df_series):
            _n_iters = df_series['n_iter']
            _contents = []
            _n_iters.sort()
            _aoc = df_series[column]
            for i, _n_iter in enumerate(_n_iters):
                n_fill = _n_iter - len(_contents) - 1
                if maximum:
                    _contents.extend([0] * n_fill)
                else:
                    _contents.extend([np.inf] * n_fill)
                _contents.append(_aoc[i])
            if maximum:
                _acc = np.maximum.accumulate(_contents)
            else:
                _acc = np.minimum.accumulate(_contents)
            return _acc
        return _inner_combine_acc
    
    def _plot_aoc():
        aoc_df = res_df.groupby(['strategy', 'problem_id', 'n_iter'])[["log_y_aoc", "y_aoc"]].agg(np.mean).reset_index()
        
        aoc_df = aoc_df.groupby(['strategy', 'problem_id'])[['n_iter',"log_y_aoc", "y_aoc"]].agg(list).reset_index()
        aoc_df['acc_y_aoc'] = aoc_df.apply(_combine_acc('y_aoc'), axis=1)
        aoc_df['acc_log_y_aoc'] = aoc_df.apply(_combine_acc('log_y_aoc'), axis=1)

        aoc_df = aoc_df.groupby(['strategy'])[['acc_y_aoc', 'acc_log_y_aoc']].agg(list).reset_index()

        strategy_aoc = [] 
        strategy_filling = []

        strategy_log_aoc = []
        strategy_log_filling = []
        
        labels = []

        unique_strategies = aoc_df['strategy'].unique()
        for strategy in unique_strategies:
            strategy_df = aoc_df[aoc_df['strategy'] == strategy]

            acc_y_aoc = np.array(strategy_df['acc_y_aoc'].values[0])
            y_aoc = np.mean(acc_y_aoc, axis=0)
            std_y_aoc = np.std(acc_y_aoc, axis=0)
            strategy_aoc.append(y_aoc)
            strategy_filling.append((y_aoc + std_y_aoc, y_aoc - std_y_aoc))

            acc_log_y_aoc = np.array(strategy_df['acc_log_y_aoc'].values[0])
            log_y_aoc = np.mean(acc_log_y_aoc, axis=0)
            std_log_y_aoc = np.std(acc_log_y_aoc, axis=0)
            strategy_log_aoc.append(log_y_aoc)
            strategy_log_filling.append((log_y_aoc + std_log_y_aoc, log_y_aoc - std_log_y_aoc))

            labels.append(strategy)


        plot_y = [np.array(strategy_log_aoc)]

        x_base = np.arange(len(strategy_aoc[0]), dtype=np.int16)
        x = np.tile(x_base, (len(plot_y), 1))
        plot_lines(
            y = plot_y,
            x = x,
            labels = [labels],
            filling=[strategy_log_filling], 
            # sub_titles=["AOC", "Log AOC"], 
            )

    
    def _plot_problem_aoc_and_loss():
        # aoc_df = res_df.copy()
        aoc_df = res_df.groupby(['strategy', 'problem_id','instance_id', 'exec_id', 'n_iter'])[["log_y_aoc", 'y_aoc', 'loss']].agg(np.mean).reset_index()
        aoc_df = aoc_df.groupby(['strategy', 'problem_id','instance_id', 'exec_id'])[['n_iter',"log_y_aoc", 'y_aoc', 'loss']].agg(list).reset_index()
        aoc_df['acc_y_aoc'] = aoc_df.apply(_combine_acc('y_aoc'), axis=1)
        aoc_df['acc_log_y_aoc'] = aoc_df.apply(_combine_acc('log_y_aoc'), axis=1)
        aoc_df['acc_loss'] = aoc_df.apply(_combine_acc('loss', maximum=False), axis=1)
        
        problem_log_aoc = []
        problem_log_aoc_filling = []
        problem_loss = []
        problem_loss_filling = []
        labels = []

        unique_problems = aoc_df['problem_id'].unique()
        
        for problem in unique_problems:
            problem_df = aoc_df[aoc_df['problem_id'] == problem]
            unique_strategies = problem_df['strategy'].unique()     
            _log_aoc = []
            _log_aoc_filling = []
            _loss = []
            _loss_filling = []
            _labels = []    
            for strategy in unique_strategies:
                strategy_df = problem_df[problem_df['strategy'] == strategy]
                acc_log_y_aoc = np.array(strategy_df['acc_log_y_aoc'].values)
                log_y_aoc = np.mean(acc_log_y_aoc, axis=0)
                std_log_y_aoc = np.std(acc_log_y_aoc, axis=0)
                _log_aoc.append(log_y_aoc)
                _log_aoc_filling.append((log_y_aoc + std_log_y_aoc, log_y_aoc - std_log_y_aoc))

                acc_loss = np.array(strategy_df['acc_loss'].values)
                loss = np.mean(acc_loss, axis=0)
                std_loss = np.std(acc_loss, axis=0)
                _loss.append(loss)
                _loss_filling.append((loss + std_loss, loss - std_loss))

                _labels.append(strategy)
            
            problem_log_aoc.append(_log_aoc)
            problem_log_aoc_filling.append(_log_aoc_filling)
            problem_loss.append(_loss)
            problem_loss_filling.append(_loss_filling)
            labels.append(_labels) 
        
        aoc_and_loss = []
        subtitles = []
        filling = []
        for i, problem in enumerate(unique_problems):
            aoc_and_loss.append(problem_log_aoc[i])
            subtitles.append(f"F{problem}-AOC")
            filling.append(problem_log_aoc_filling[i])
            
            aoc_and_loss.append(problem_loss[i])
            subtitles.append(f"F{problem}-Loss")
            filling.append(problem_loss_filling[i])
        labels = labels * 2

        plot_y = np.array(aoc_and_loss)

        x_base = np.arange(len(problem_log_aoc[0][0]), dtype=np.int16)
        x = np.tile(x_base, (len(plot_y), 1))

        plot_result(
            y = plot_y,
            x = x,
            labels = labels,
            filling=filling,
            sub_titles=subtitles, 
            n_cols=5,
            figsize=(15, 9)
            )
    # _plot_problem_aoc_and_loss()


    def _plot_similarity():
        strategy_group = {}
        for strategy_name, pop in results:
            if strategy_name not in strategy_group:
                strategy_group[strategy_name] = []
            strategy_group[strategy_name].append(pop)

        y_sim_list = []
        y_sim_filling = []
        labels = []
        y_pop_sim_list = []

        for strategy_name, group in strategy_group.items():
            sim_list = []
            pop_sim_list = []
            for pop in group:
                iter_sim_list = []
                n_iter = 1
                n_generation = pop.get_current_generation()
                for gen in range(n_generation):
                    gen_offsprings = pop.get_offsprings(generation=gen)
                    n_iter += len(gen_offsprings)

                    n_fill = n_iter - len(iter_sim_list)
                    mean_sim, _ = desc_similarity(gen_offsprings)
                    _sim = np.mean(mean_sim)
                    iter_sim_list.extend([_sim] * n_fill)
                sim_list.append(iter_sim_list)

                all_inds = pop.all_individuals()
                all_mean_sim, _ = desc_similarity(all_inds)
                pop_sim_list.append(np.mean(all_mean_sim))

            mean_sim = np.mean(sim_list, axis=0)
            std_sim = np.std(sim_list, axis=0)
            y_sim_list.append(mean_sim)
            y_sim_filling.append((mean_sim + std_sim, mean_sim - std_sim))

            labels.append(strategy_name)

            y_pop_sim_list.append(pop_sim_list)

        plot_y = [np.array(y_sim_list)]
        x_base = np.arange(len(y_sim_list[0]), dtype=np.int16)
        x = np.tile(x_base, (len(plot_y), 1))
        plot_lines(
            y = plot_y,
            x = x,
            labels = [labels],
            filling=[y_sim_filling], 
            )
        
        # plot_box_violin(
        #             data=[y_pop_sim_list],
        #             labels=[labels],
        #             plot_type="violin",
        #             n_cols=4,
        #             figsize=(14, 8),
        #             )
    # _plot_similarity()

    
    def _plot_error_state():
        # - error rate by strategy
        # - error rate by generation
        # - error type
        column_names = [
        'strategy',
        'n_gen',
        'n_repeat',
        'n_iter',
        'err_type',
        ]
        _err_df = pd.DataFrame(columns=column_names)
        _unique_strategies = res_df['strategy'].unique()
        _strategy_count = {}
        for strategy_name, pop in results:
            if strategy_name not in _strategy_count:
                _strategy_count[strategy_name] = 0
            _strategy_count[strategy_name] += 1

            n_generation = pop.get_current_generation()
            n_iter = 0
            for gen in range(n_generation):
                # offspring generated in this generation
                gen_offsprings = pop.get_offsprings(generation=gen)
                n_iter += len(gen_offsprings)
                # offspring selected in this generation
                for ind in gen_offsprings:
                    handler = Population.get_handler_from_individual(ind)
                    res = {
                        'strategy': strategy_name,
                        'n_gen': gen+1,
                        'n_iter': n_iter,
                        'n_repeat': _strategy_count[strategy_name],
                        'err_type': handler.error_type
                    }
                    _err_df.loc[len(_err_df)] = res

        # error rate by strategy
        def _plot_all_error_rate():
            _all_error_df = _err_df.groupby(['strategy', 'n_repeat'])['err_type'].agg(list).reset_index()
            _all_error_df['err_rate'] = _all_error_df['err_type'].apply(lambda x: len([ele for ele in x if ele is not None]) / len(x))

            y_err_rates = []
            for strategy in _unique_strategies:
                _strategy_error_df = _all_error_df[_all_error_df['strategy'] == strategy]
                _error_rate = _strategy_error_df['err_rate'].to_list()
                y_err_rates.append(_error_rate)

            plot_box_violin(
                data=[y_err_rates],
                labels=[_unique_strategies],
                plot_type="violin",
                n_cols=4,
                figsize=(15, 9),
                ) 

        # error rate by generation
        def _plot_error_rate_by_generation():
            def _combine_err_rate(df_series):
                _n_iters = df_series['n_iter']
                _contents = []
                sort_idxs = np.argsort(_n_iters)
                _rates = df_series['err_rate']
                for i, _n_iter_idx in enumerate(sort_idxs):
                    _n_iter = _n_iters[_n_iter_idx]
                    _rate = _rates[_n_iter_idx]
                    n_fill = _n_iter - len(_contents)
                    _contents.extend([_rate] * n_fill)
                return np.array(_contents)
            
            _gen_error_df = _err_df.groupby(['strategy', 'n_iter', 'n_repeat'])['err_type'].agg(list).reset_index()
            _gen_error_df['err_rate'] = _gen_error_df['err_type'].apply(lambda x: len([ele for ele in x if ele is not None]) / len(x))
            _gen_error_df = _gen_error_df.groupby(['strategy', 'n_repeat'])[['err_rate', 'n_iter']].agg(list).reset_index()
            _gen_error_df['evol_err_rate'] = _gen_error_df.apply(_combine_err_rate, axis=1)

            y_err_rates = []
            y_err_rates_filling = []
            labels = []
            for strategy in _unique_strategies:
                _strategy_error_df = _gen_error_df[_gen_error_df['strategy'] == strategy]

                _evol_err_rate = _strategy_error_df['evol_err_rate'].to_list()
                _mean_err_rate = np.mean(_evol_err_rate, axis=0)
                _std_err_rate = np.std(_evol_err_rate, axis=0)

                y_err_rates.append(_mean_err_rate)
                y_err_rates_filling.append((_mean_err_rate + _std_err_rate, _mean_err_rate - _std_err_rate))

                labels.append(strategy)
                
            plot_y = [np.array(y_err_rates)]
            x_base = np.arange(len(y_err_rates[0]), dtype=np.int16)
            x = np.tile(x_base, (len(plot_y), 1))
            plot_lines(
                y = plot_y,
                x = x,
                labels = [labels],
                filling=[y_err_rates_filling], 
                ) 

        # error type
        def _plot_error_type():
            _size = _err_df.size
            type_count = _err_df['err_type'].value_counts()
            _all_type_count = type_count.sum()
            # type_percentage = type_count.div(type_count.sum()).mul(100)

            _title = f"{_all_type_count} errors in {_size} algorithms"
            _title = f'Total errors: {_all_type_count}/{_size}'
            _plot_data = type_count

            _, ax = plt.subplots()
            ax.pie(_plot_data, 
                   labels=_plot_data.index, 
                   autopct='%1.1f%%',
                #    autopct=lambda p: '{:d}'.format(int(p / 100 * _all_type_count)),
                   )
            ax.set_title(_title)
    
        _plot_all_error_rate()
        _plot_error_rate_by_generation()
        _plot_error_type()

        pass

    _plot_error_state()

    pass
        

def plot_algo_result(results:list[EvaluatorResult], **kwargs):

    # dynamic access from EvaluatorBasicResult. None means it should be handled separately
    column_name_map = {
        'algorithm' : None,
        'problem_id' : None,
        'instance_id' : None,
        'exec_id' : None,
        'n_init' : 'n_initial_points',
        'acq_exp_threshold' : 'search_result.acq_exp_threshold',

        'log_y_aoc' : 'log_y_aoc',
        'y_aoc' : 'y_aoc',
        'y' : 'y_hist',
        
        'loss' : None,
        'best_loss' : None,
        
        'r2' : 'r2_list',
        'r2_on_train' : 'r2_list_on_train',
        'uncertainty' : 'uncertainty_list',
        'uncertainty_on_train' : 'uncertainty_list_on_train',
        
        'grid_coverage' : 'search_result.coverage_grid_list',   
        'acq_grid_coverage' : 'search_result.iter_coverage_grid_list',
        
        'dbscan_circle_coverage' : 'search_result.coverage_dbscan_circle_list',
        'acq_dbscan_circle_coverage' : 'search_result.iter_coverage_dbscan_circle_list',
        
        'dbscan_rect_coverage' : 'search_result.coverage_dbscan_rect_list',
        'acq_dbscan_rect_coverage' : 'search_result.iter_coverage_dbscan_rect_list',
        
        'online_rect_coverage' : 'search_result.coverage_online_rect_list',
        'acq_online_rect_coverage' : 'search_result.iter_coverage_online_rect_list',
        
        'online_circle_coverage' : 'search_result.coverage_online_circle_list',
        'acq_online_circle_coverage' : 'search_result.iter_coverage_online_circle_list',
        
        'exploitation_rate' : 'search_result.k_distance_exploitation_list',
        'acq_exploitation_rate' : 'search_result.iter_k_distance_exploitation_list',
        
        'acq_exploitation_score' : 'search_result.acq_exploitation_scores',
        'acq_exploration_score' : 'search_result.acq_exploration_scores',
        
        'acq_exploitation_validity' : 'search_result.acq_exploitation_validity',
        'acq_exploration_validity' : 'search_result.acq_exploration_validity',

        'acq_exploitation_improvement' : 'search_result.acq_exploitation_improvement',
        'acq_exploration_improvement' : 'search_result.acq_exploration_improvement',
    }

    def _none_to_nan(_target):
        if isinstance(_target, list):
            return [np.nan if ele is None else ele for ele in _target] 
        return np.nan if _target is None else _target

    def res_to_row(res, algo:str):
        res_id = res.id
        res_split = res_id.split("-")
        problem_id = int(res_split[0])
        instance_id = int(res_split[1])
        repeat_id = int(res_split[2])
        loss = res.y_hist - res.optimal_value
        row = {}

        for column_name, column_path in column_name_map.items():
            if column_path is None:
                if column_name == 'algorithm':
                    row[column_name] = algo
                elif column_name == 'problem_id':
                    row[column_name] = problem_id
                elif column_name == 'instance_id':
                    row[column_name] = instance_id
                elif column_name == 'exec_id':
                    row[column_name] = repeat_id
                elif column_name == 'loss':
                    row[column_name] = loss
                elif column_name == 'best_loss':
                    row[column_name] = np.minimum.accumulate(loss)
            else:
                value = dynamical_access(res, column_path)
                non_none_value = _none_to_nan(value)
                row[column_name] = non_none_value
        return row

    res_df = pd.DataFrame(columns=column_name_map.keys())
    for result in results:
        algo = result.name.removeprefix("BL")
        for res in result.result:
            row = res_to_row(res, algo)
            if row is not None:
                res_df.loc[len(res_df)] = row

    # hanle aoc
    def _plot_aoc():
        problem_id_list = res_df['problem_id'].unique()
        aoc_df = res_df.groupby(['algorithm','problem_id'])[['y_aoc', 'log_y_aoc']].agg(list).reset_index()
        #(problem, data)
        aoc_plot_data = []
        log_plot_data = []
        labels = []
        short_labels = []
        sub_titles = []
        for problem_id in problem_id_list:
            _temp_df = aoc_df[aoc_df['problem_id'] == problem_id].agg(list)
            aoc_plot_data.append(_temp_df['y_aoc'].to_list())
            log_plot_data.append(_temp_df['log_y_aoc'].to_list())
            sub_titles.append(f"F{problem_id}")

            _labels = _temp_df['algorithm'].to_list()
            labels.append(_labels)
            short_labels.append([label[:10] for label in _labels])

        labels = short_labels

        # plot aoc
        # plot_box_violin(data=aoc_plot_data, 
        #                 labels=labels, 
        #                 sub_titles=sub_titles, 
        #                 title="AOC",
        #                 plot_type="violin", 
        #                 n_cols=4,
        #                 figsize=(14, 8),
        #                 **kwargs)

        # # plot log aoc
        plot_box_violin(data=log_plot_data,
                        labels=labels,
                        sub_titles=sub_titles,
                        title="AOC",
                        plot_type="violin",
                        n_cols=4,
                        figsize=(15, 9),
                        **kwargs)
    
    _plot_aoc()

    def mean_std_agg(agg_series):
        if is_numeric_dtype(agg_series.dtype):
            mean = np.nanmean(agg_series)
            std = np.nanstd(agg_series)
            return [mean, std]
        else:  
            agg_list = agg_series.to_list()
            min_len = min([len(ele) for ele in agg_list])
            # clip the list to the minimum length
            cliped_list = [ele[:min_len] for ele in agg_list]
            mean_list = np.nanmean(cliped_list, axis=0)
            std_list = np.nanstd(cliped_list, axis=0)
            return [mean_list, std_list]

    def _min_accumulate(_series):
        if isinstance(_series, tuple):
            mean, _ = _series
            _mean = np.minimum.accumulate(mean)
            _std = np.full_like(_mean, 0)
            return (_mean, _std)
        return np.minimum.accumulate(_series)

    def fill_nan_with_left(arr):
        filled_arr = arr.copy()
        last_valid_index = 0 
        for i in range(len(filled_arr)):
            index = len(arr) - i - 1
            val = filled_arr[index]
            if np.isnan(val):
                pass
            else:
                last_valid_index = index
                break
                
        last_valid = None
        for i, val in enumerate(filled_arr):
            if np.isnan(val):
                if i<last_valid_index and last_valid is not None:
                    filled_arr[i] = last_valid
                else:
                    filled_arr[i] = np.nan
            else:
                last_valid = val
        return filled_arr

    
    def _plot_iter():

        # handle y
        data_col_map = {
            'n_init': '',
            'acq_exp_threshold': '',

            'loss': 'Loss',
            'best_loss': 'Best Loss',

            'r2': 'R2 on test',
            'r2_on_train' : 'R2 on train',
            'uncertainty' : 'Uncertainty on test',
            'uncertainty_on_train' : 'Uncertainty on train',

            'grid_coverage' : 'Grid Coverage',

            # 'dbscan_circle_coverage': 'DBSCAN Circle Coverage',
            # 'dbscan_rect_coverage': 'DBSCAN Rect Coverage',

            'online_rect_coverage': 'Online Cluster Rect Coverage',
            # 'online_circle_coverage': 'Online Circle Coverage',

            'acq_grid_coverage' : 'Acq Grid Coverage',

            # 'acq_dbscan_circle_coverage': 'DBSCAN Circle Coverage(Acq)',
            # 'acq_dbscan_rect_coverage': 'DBSCAN Rect Coverage(Acq)',

            'acq_online_rect_coverage': 'Online Cluster Rect Coverage(Acq)',
            # 'acq_online_circle_coverage': 'Online Circle Coverage(Acq)',

            'exploitation_rate': 'Exploitation Rate',
            'acq_exploitation_rate': 'Acq Exploitation Rate(er)',

            'acq_exploitation_improvement': 'Exploitation Improvement: $current-best$',
            'acq_exploitation_score': 'Exploitation Score: $improve/(best-optimum)$',
            'acq_exploitation_validity': 'Exploitation Validity: $score*er$',

            'acq_exploration_improvement': 'Exploration Improvement: $current-best$',
            'acq_exploration_score': 'Exploration Score: $improve/fixed\_base$',
            'acq_exploration_validity': 'Exploration Validity: $score*(1-er)$',
        }
        data_cols = list(data_col_map.keys())
        
        # if 'loss' in data_cols:
        #     # apply loss to min.accumulate, then create new column
        #     # y_df['best_loss'] = y_df['loss'].apply(_min_accumulate)
        #     res_df['best_loss'] = res_df['loss'].apply(np.minimum.accumulate)
        #     # insert best_loss to the next of loss in data_cols
        #     loss_index = data_cols.index('loss')
        #     data_cols.insert(loss_index+1, 'best_loss')
        #     data_col_map['best_loss'] = 'Best Loss'

        y_df = res_df.groupby(['algorithm', 'problem_id'])[data_cols].agg(mean_std_agg).reset_index()
        y_df[data_cols].applymap(lambda x: x[0] if isinstance(x, list) else x)

        problem_ids = y_df['problem_id'].unique()


        def smooth_factory(smooth_type='savgol', window_size=5, polyorder=2, sigma=1.0):
            def _smooth_data(data):
                if smooth_type == 'savgol':
                    return savgol_smoothing(data, window_size, polyorder)
                elif smooth_type == 'moving':
                    return moving_average(data, window_size)
                elif smooth_type == 'gaussian':
                    return gaussian_smoothing(data, sigma)
            return _smooth_data

        smooth_cols = {
            # 'exploitation_rate': smooth_factory(smooth_type='moving', window_size=5),
        }

        def clip_upper_factory(bound_type='mean', upper_len_ratio=0.25, inverse=False, _bound=None):
            def _clip_upper(data, bound_type=bound_type, upper_len_ratio=upper_len_ratio, inverse=inverse, _bound=_bound):
                _clip_len = int(data.shape[1] * upper_len_ratio)
                _upper_bound = _bound
                if bound_type == 'mean':
                    if inverse:
                        _upper_bound = np.nanmean(data[:, _clip_len:]) + np.nanstd(data[:, _clip_len:])
                    else:
                        _upper_bound = np.nanmean(data[:, :_clip_len]) + np.nanstd(data[:, :_clip_len])
                elif bound_type == 'median':
                    if inverse:
                        _upper_bound = np.nanmedian(data[:, _clip_len:])
                    else:
                        _upper_bound = np.nanmedian(data[:, :_clip_len])
                elif bound_type == 'fixed' and _bound is not None:
                    _upper_bound = _bound

                _data = np.clip(data, 0, _upper_bound)
                return _data, _upper_bound
            return _clip_upper

        clip_cols = {
            'loss': clip_upper_factory(bound_type='mean'),
        }

        y_scale_cols = {
            'loss': ('log', {}),
            'best_loss': ('log', {}),
        }

        non_fill_cols = [
            'loss',
            'best_loss',
        ]

        ignore_cols = [
            'n_init',
            'acq_exp_threshold',
        ]

        for problem_id in problem_ids:
            plot_data = []
            x_data = []
            plot_filling = []
            labels = []
            x_dots = []
            sub_titles = []
            y_scales = []
            colors = []
            baselines = []
            baseline_labels = []
            
            _temp_df = y_df[y_df['problem_id'] == problem_id]

            prop_cycle = plt.rcParams['axes.prop_cycle']
            _default_colors = prop_cycle.by_key()['color']

            for col in data_cols:
                if col in ignore_cols:
                    continue

                data = _temp_df[col].to_list()
                # remove empty data if len(data) == 0 or all nan
                empty_indexs = [i for i, ele in enumerate(data) if ele[0].size == 0 or np.all(np.isnan(ele[0]))]
                data = [ele for i, ele in enumerate(data) if i not in empty_indexs]

                if len(data) == 0:
                    continue
                
                # fill short data and replace nan with the left
                max_len = max([len(ele[0]) for ele in data])
                for i, ele in enumerate(data):
                    _content = []
                    for _sub_ele in ele:
                        _new_sub_ele = _sub_ele
                        if len(_new_sub_ele) < max_len:
                            fill_len = max_len - len(_new_sub_ele)
                            _new_sub_ele = np.append(_new_sub_ele, [np.nan] * fill_len)
                        _new_sub_ele = fill_nan_with_left(_new_sub_ele)
                        _content.append(_new_sub_ele)
                    data[i] = _content
                        
                mean_array = np.array([ele[0] for ele in data])
                std_array = np.array([ele[1] for ele in data])

                # clip if needed
                if col in clip_cols:
                    mean_array, _upper_bound = clip_cols[col](mean_array)
                    std_array = np.where(mean_array == _upper_bound, 0, std_array)

                # smooth if needed
                if col in smooth_cols:
                    mean_array = smooth_cols[col](mean_array)
                
                plot_data.append(mean_array)
                x_data.append(np.arange(mean_array.shape[1]))
                
                # fill the area between mean - std and mean + std
                if col not in non_fill_cols:
                    upper_bound = mean_array + std_array 
                    lower_bound = mean_array - std_array
                    plot_filling.append(list(zip(lower_bound, upper_bound)))
                else:
                    plot_filling.append(None)

                if 'acq_exploitation_rate' in col:
                    exp_threshold = _temp_df['acq_exp_threshold'].to_list()
                    mean_exp = [ele[0] for ele in exp_threshold]
                    _bl = np.nanmean(mean_exp)
                    baselines.append([_bl])
                    baseline_labels.append(["Threshold"])
                else:
                    baselines.append(None)
                    baseline_labels.append(None)

                # handle n_init
                n_init_data = _temp_df['n_init'].to_list()
                _x_dots = []
                for n_init in n_init_data:
                    if n_init[0] > 0:
                        _x_dots.append(np.array([n_init[0]], dtype=int))
                    else:
                        _x_dots.append(np.array([], dtype=int))
                # remove empty data
                _x_dots = [ele for i, ele in enumerate(_x_dots) if i not in empty_indexs]
                x_dots.append(_x_dots)

                _labels = _temp_df['algorithm'].to_list()
                _colors = _default_colors[:len(_labels)]
                _labels = [ele for i, ele in enumerate(_labels) if i not in empty_indexs]
                _labels = [label[:10] for label in _labels]
                _colors = [color for i, color in enumerate(_colors) if i not in empty_indexs]
                labels.append(_labels)
                colors.append(_colors)

                _sub_title = data_col_map.get(col, col)
                if col in y_scale_cols:
                    _y_scale, _y_scale_kwargs = y_scale_cols[col]
                    y_scales.append((_y_scale, _y_scale_kwargs))
                    sub_titles.append(_sub_title + f"({_y_scale})")
                else:
                    y_scales.append(None)
                    sub_titles.append(_sub_title)


            plot_lines(
                y=plot_data, x=x_data, 
                y_scales=y_scales,
                baselines=baselines,
                baseline_labels=baseline_labels,
                colors=colors,
                labels=labels, 
                label_fontsize=6,
                linewidth=1.0,
                filling=plot_filling,
                x_dot=x_dots,
                n_cols=5,
                sub_titles=sub_titles,
                sub_title_fontsize=9,
                title=f"F{problem_id}",
                figsize=(15, 9),
                **kwargs
            ) 


    # _plot_iter()
