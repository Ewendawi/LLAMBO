import os
import logging
from datetime import datetime
import pickle
import torch
import numpy as np
from llamea import LLaMBO
from llamea.llm import LLMmanager, LLMS
from llamea.prompt_generators import PromptGenerator, BaselinePromptGenerator
from llamea.population import Population, ESPopulation, IslandESPopulation, max_divese_desc_get_parent_fn, diversity_awarness_selection_fn
from llamea.evaluator import IOHEvaluator, AbstractEvaluator
from llamea.utils import setup_logger


def get_IOHEvaluator_for_evol():
    budget = 100
    dim = 5
    problems = list(range(1, 25))
    instances = [[1, 2]] * len(problems)
    repeat = 2
    evaluator = IOHEvaluator(budget=budget, dim=dim, problems=problems, instances=instances, repeat=repeat)
    return evaluator

def get_IOHEvaluator_for_final_eval():
    budget = 100
    dim = 5
    problems = list(range(1, 25))
    instances = [[4, 5, 6]] * len(problems)
    repeat = 5
    evaluator = IOHEvaluator(budget=budget, dim=dim, problems=problems, instances=instances, repeat=repeat)
    return evaluator

def get_IOHEvaluator_for_test():
    budget = 100
    dim = 5
    problems = [2, 8]
    instances = [[1]] * len(problems)
    repeat = 2
    evaluator = IOHEvaluator(budget=budget, dim=dim, problems=problems, instances=instances, repeat=repeat)
    return evaluator

def get_bo_prompt_generator():
    prompt_generator = BaselinePromptGenerator()
    prompt_generator.is_bo = True
    return prompt_generator

    
def baseline_algo_eval_param(dim, budget):
    bl_init_params = {
        "budget": budget,
        "dim": dim,
        "bounds": np.array([[-5.0] * 5, [5.0] * 5]),
        "n_init": min(2 * dim, budget // 2),
        "seed": None,
        "device": "cpu",
        # "device": "cuda",
    }
    return bl_init_params

def _run_algrothim_eval_exp(code, cls_name, algo_cls, is_bl=False, **kwargs):
    evaluator = get_IOHEvaluator_for_final_eval()
    logging.info("Start evaluating %s on %s", cls_name, evaluator)

    ignore_over_budget = kwargs.pop("ignore_over_budget", False)
    evaluator.ignore_over_budget = ignore_over_budget

    extra_init_params = {}
    if is_bl:
        extra_init_params = baseline_algo_eval_param(evaluator.dim, evaluator.budget)
    
    res = evaluator.evaluate(
        code=code,
        cls_name=cls_name,
        cls=algo_cls,
        cls_init_kwargs=extra_init_params,
        **kwargs
    )
    dir_path = os.path.join("Experiments", "algo_eval_res")
    os.makedirs(dir_path, exist_ok=True)
    time_stamp = datetime.now().strftime("%m%d%H%M%S")
    file_path = os.path.join(dir_path, f"{algo_cls.__name__}_{time_stamp}.pkl")
    with open(file_path, "wb") as f:
        pickle.dump(res, f)

def run_algo_eval_exp(algo_cls, is_bl, **kwargs):
    if algo_cls is None:
        return
    code = "Here is the code"
    cls_name = algo_cls.__name__
    _run_algrothim_eval_exp(code, cls_name, algo_cls, is_bl=is_bl, **kwargs)

def run_ind_eval_exp(individual, **kwargs): 
    if individual is None:
        return
    handler = Population.get_handler_from_individual(individual)
    if handler is None or not handler.code or not handler.code_name:
        return
    _run_algrothim_eval_exp(handler.code, handler.code_name, None, is_bl=False, **kwargs)

def run_all_algo_eval_exp(**kwargs):
    from Experiments.baselines.bo_baseline import BLTuRBO1, BLTuRBOM, BLRBFKernelVanillaBO, BLScaledKernelVanillaBO, BLRandomSearch
    # run_algo_eval_exp(BLRandomSearch, is_bl=True, **kwargs)
    # run_algo_eval_exp(BLRBFKernelVanillaBO, is_bl=True, **kwargs)
    # run_algo_eval_exp(BLScaledKernelVanillaBO, is_bl=True, **kwargs) 
    # run_algo_eval_exp(BLTuRBO1, is_bl=True, ignore_over_budget=True, **kwargs)
    # run_algo_eval_exp(BLTuRBOM, is_bl=True, ignore_over_budget=True, **kwargs)  


    from Experiments.test_cands.EnsembleLocalSearchBOv1 import EnsembleLocalSearchBOv1
    from Experiments.test_cands.EnsembleDeepKernelAdaptiveTSLocalSearchARDv1 import EnsembleDeepKernelAdaptiveTSLocalSearchARDv1
    # run_algo_eval_exp(EnsembleLocalSearchBOv1, is_bl=False, **kwargs)
    run_algo_eval_exp(EnsembleDeepKernelAdaptiveTSLocalSearchARDv1, is_bl=False, **kwargs)

def _run_exp(prompt_generator:PromptGenerator, 
            evaluator:AbstractEvaluator, 
            llm:LLMmanager,
            population:Population,
            n_generations:int=200, 
            n_population:int=30, 
            gpu_name:str=None, 
            max_interval:int=5, 
            n_query_threads:int=0, 
            n_eval_workers:int=0,
            time_out_per_eval:int=None
            ):
    llambo = LLaMBO()

    population.name += f"_{llm.model_name()}_{prompt_generator}_{evaluator}"
    if torch.cuda.is_available():
        population.name += "_gpu"

    llambo.run_evolutions(llm, evaluator, prompt_generator, population,
                        n_generation=n_generations, n_population=n_population,
                        n_retry=3, sup_results=None,
                        time_out_per_eval=time_out_per_eval,
                        n_query_threads=n_query_threads,
                        n_eval_workers=n_eval_workers,
                        gpu_name=gpu_name,
                        max_interval=max_interval
                        )

    population.save()



def run_mu_plus_lambda_exp(
                    n_parent:int=2,
                    n_offspring:int=1,
                    n_parent_per_offspring:int=2,
                    **kwargs
                    ):
    population = ESPopulation(n_parent=n_parent, n_parent_per_offspring=n_parent_per_offspring, n_offspring=n_offspring)
    population.name = f"{n_parent}+{n_offspring}"
    
    _run_exp(
        population=population,
        **kwargs
    )

def run_1_plus_1_exp(**kwargs):
    run_mu_plus_lambda_exp(n_parent=1, n_offspring=1, n_parent_per_offspring=1, **kwargs)


def run_mu_plus_lambda_diversity_exp(
                    n_parent:int=2,
                    n_offspring:int=1,
                    n_parent_per_offspring:int=2,
                    **kwargs
                    ):
    population = ESPopulation(n_parent=n_parent, n_parent_per_offspring=n_parent_per_offspring, n_offspring=n_offspring)
    population.preorder_aware_init = True
    population.get_parent_strategy = max_divese_desc_get_parent_fn
    population.selection_strategy = diversity_awarness_selection_fn
    population.name = f"{n_parent}+{n_offspring}_diversity"

    _run_exp(
        population=population,
        **kwargs
    )


def run_island_exp(
        n_parent:int=2,
        n_offspring:int=1,
        n_parent_per_offspring:int=2,
        n_islands:int=3,
        n_warmup_generations:int=3,
        n_cambrian_generations:int=2,
        n_neogene_generations:int=2,
        **kwargs):

    population = IslandESPopulation(n_parent=n_parent,
                                    n_parent_per_offspring=n_parent_per_offspring,
                                    n_offspring=n_offspring,
                                    n_islands=n_islands,
                                    n_warmup_generations=n_warmup_generations,
                                    n_cambrian_generations=n_cambrian_generations,
                                    n_neogene_generations=n_neogene_generations
                                    )
    population.preorder_aware_init = True
    population.get_parent_strategy = max_divese_desc_get_parent_fn
    population.selection_strategy = diversity_awarness_selection_fn

    population.name = f"{n_parent}+{n_offspring}_island_{n_islands}"

    _run_exp(
        population=population,
        **kwargs
    )





def get_llm():
    # MODEL = LLMS["deepseek/deepseek-chat"]
    MODEL = LLMS["gemini-2.0-flash-exp"]
    # MODEL = LLMS["gemini-1.5-flash"]
    # MODEL = LLMS["gemini-exp-1206"]
    # MODEL = LLMS["llama-3.1-70b-versatile"]
    # MODEL = LLMS["llama-3.3-70b-versatile"]
    # MODEL = LLMS["o_gemini-flash-1.5-8b-exp"]
    # MODEL = LLMS["o_gemini-2.0-flash-exp"]

    
    def mock_res_provider(*args, **kwargs):
        file_list = [
            "Experiments/bbob_test_res/successful_heavy_res.md",
            "Experiments/bbob_test_res/successful_light_res.md",
            "Experiments/bbob_test_res/successful_light_res1.md",
            "Experiments/bbob_test_res/fail_excute_res.md",
            "Experiments/bbob_test_res/fail_overbudget_res.md",
        ]
        file_path = np.random.choice(file_list, size=1, p=[0.0, 0.0, 1.0, 0.0, 0.0])[0]
        file_path = "Experiments/bbob_test_res/successful_bl.md"
        response = None
        with open(file_path, "r") as f:
            response = f.read()
        return response

    llm = LLMmanager(api_key=MODEL[1], model=MODEL[0], base_url=MODEL[2], max_interval=MODEL[3])


    llm.mock_res_provider = mock_res_provider

    return llm


if __name__ == "__main__":
    # setup_logger(level=logging.DEBUG)
    setup_logger(level=logging.INFO)

    params = {
        # "time_out_per_eval": 60 * 20,
        "time_out_per_eval": None,

        "llm": get_llm(),
        "prompt_generator": get_bo_prompt_generator(),
        "n_generations": 200,
        "n_population": 10,
        "n_query_threads": 0,
        "n_eval_workers": 0,

        # "gpu_name": "cuda:7",
        "gpu_name": None,

        "max_interval": 5,

        
        "evaluator": get_IOHEvaluator_for_evol(),
        # "evaluator": get_IOHEvaluator_for_test(),
    }

    # run_1_plus_1_exp(**params)

    # N_PARENT = 2
    # N_PARENT_PER_OFFSPRING = 2
    # N_OFFSPRING = 1

    # run_mu_plus_lambda_exp(
    #     n_parent=N_PARENT,
    #     n_offspring=N_PARENT_PER_OFFSPRING,
    #     n_parent_per_offspring=N_OFFSPRING,
    #     **params)


    # run_mu_plus_lambda_diversity_exp(
    #     n_parent=N_PARENT,
    #     n_offspring=N_PARENT_PER_OFFSPRING,
    #     n_parent_per_offspring=N_OFFSPRING,
    #     **params)

    
    run_all_algo_eval_exp()
