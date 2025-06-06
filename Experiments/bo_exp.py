import random
import logging
import time
import tqdm
from llamevol import LLaMEvol, LLMmanager
from llamevol.prompt_generators import PromptGenerator, BoZeroPromptGenerator, BoZeroPlusPromptGenerator, BaselinePromptGenerator
from llamevol.utils import setup_logger, IndividualLogger 
from llamevol.evaluator.ioh_evaluator import IOHEvaluator 
from llamevol.llm import LLMS

def run_bo_exp_code_generation(model:tuple, aggressiveness:float, use_botorch:bool, prompt_generator:PromptGenerator, n_iterations:int=1, n_generations:int=1):
    llamevol = LLaMEvol()

    llm = LLMmanager(api_key=model[1], model=model[0], base_url=model[2], max_interval=model[3])

    if isinstance(prompt_generator, BoZeroPlusPromptGenerator):
        prompt_generator.use_botorch = use_botorch
        prompt_generator.aggressiveness = aggressiveness
    elif isinstance(prompt_generator, BoZeroPromptGenerator):
        prompt_generator.use_botorch = use_botorch

    progress_bar = tqdm.tqdm(range(n_iterations), desc="Iterations")
    for _ in range(n_iterations):
        population = SequencePopulation()
        evaluator = RandomBoTorchTestEvaluator()

        other_results = evaluator.evaluate_others()

        llamevol.run_evolutions(llm, evaluator, prompt_generator, population, n_generation=n_generations, n_retry=3, sup_results=other_results)
        log_aggressiveness_and_botorch(population, aggressiveness, use_botorch)
        progress_bar.update(1)

    log_file_name = f"bo_exp_p1_{model[0]}_{aggressiveness}_{use_botorch}"
    log_dir_name = "logs_temp"
    log_population(population, save=True, dirname=log_dir_name, filename=log_file_name)

def run_bo_exp_fix_errors(model:tuple, log_path:str, prompt_generator:PromptGenerator,n_iterations:int=1, n_generations:int=1):
    llamevol = LLaMEvol()

    llm = LLMmanager(api_key=model[1], model=model[0], base_url=model[2], max_interval=model[3])

    p1_logger = IndividualLogger.load(log_path)
    failed_individuals = p1_logger.get_failed_individuals()

    n_samples = 2 * n_iterations

    error_type_group = {}
    for ind in failed_individuals:
        error_type = ind.metadata["error_type"]
        if error_type not in error_type_group:
            error_type_group[error_type] = []
        error_type_group[error_type].append(ind)

    selected_failed_individuals = []
    for error_type, individuals in error_type_group.items():
        selected_failed_individuals.append(random.choice(individuals))
        if len(selected_failed_individuals) > n_samples:
            break

    if len(selected_failed_individuals) < n_samples:
        selected_failed_individuals.extend(random.sample(failed_individuals, n_samples - len(selected_failed_individuals)))

    progress_bar = tqdm.tqdm(range(n_iterations), desc="Iterations")
    for _ in range(n_iterations):
        candidate = selected_failed_individuals.pop()
        aggressiveness = candidate.metadata["aggressiveness"]
        use_botorch = "botorch" in candidate.metadata["tags"]
        problem_str = candidate.metadata["problem"]
        problem_dim = candidate.metadata["dimension"]

        if isinstance(prompt_generator, BoZeroPlusPromptGenerator):
            prompt_generator.use_botorch = use_botorch
            prompt_generator.aggressiveness = aggressiveness
        elif isinstance(prompt_generator, BoZeroPromptGenerator):
            prompt_generator.use_botorch = use_botorch

        evaluator = RandomBoTorchTestEvaluator(dim=problem_dim, obj_fn_name=problem_str)
        if evaluator.obj_fn is None:
            logging.error("Failed to load the objective function for %s with dim %s", problem_str, problem_dim)
            continue

        population = SequencePopulation()
        population.add_individual(candidate)
        population.name = f"bo_exp_p2_{candidate.metadata['error_type']}_{model[0]}_{problem_str}"

        llamevol.run_evolutions(llm, evaluator, prompt_generator, population, n_generation=n_generations, n_retry=3)
        log_aggressiveness_and_botorch(population, aggressiveness, use_botorch)
        progress_bar.update(1)

    log_file_name = f"bo_exp_p2_{model[0]}"
    log_dir_name = "logs_temp"
    log_population(population, save=True, dirname=log_dir_name, filename=log_file_name)

def run_bo_exp_optimize_performance(model:tuple, log_path:str, prompt_generator:PromptGenerator, n_iterations:int=1, n_generations:int=1):
    llamevol = LLaMEvol()

    llm = LLMmanager(api_key=model[1], model=model[0], base_url=model[2], max_interval=model[3])

    p_logger = IndividualLogger.load(log_path)
    successful_individuals = p_logger.get_successful_individuals()

    problem_group = {}
    for ind in successful_individuals:
        problem = ind.metadata["problem"]
        if problem not in problem_group:
            problem_group[problem] = []
        problem_group[problem].append(ind)

    selected_successful_individuals = []
    for problem, individuals in problem_group.items():
        selected_successful_individuals.append(random.choice(individuals))
        if len(selected_successful_individuals) > n_iterations:
            break

    if len(selected_successful_individuals) < n_iterations:
        selected_successful_individuals.extend(random.sample(successful_individuals, n_iterations - len(selected_successful_individuals)))

    selected_successful_individuals = random.sample(successful_individuals, n_iterations)
    progress_bar = tqdm.tqdm(range(n_iterations), desc="Iterations")
    for _ in range(n_iterations):
        candidate = selected_successful_individuals.pop()

        aggressiveness = 0.5
        use_botorch = False
        problem_str = candidate.metadata["problem"]
        problem_dim = None
        for tag in candidate.metadata["tags"]:
            if tag.startswith("aggr:"):
                aggressiveness = float(tag.split(":")[1])
            elif tag == "botroch:":
                use_botorch = True
            elif tag.startswith("dim:"):
                problem_dim = int(tag.split(":")[1])

        if isinstance(prompt_generator, BoZeroPlusPromptGenerator):
            prompt_generator.aggressiveness = aggressiveness
            prompt_generator.use_botorch = use_botorch
        elif isinstance(prompt_generator, BoZeroPromptGenerator):
            prompt_generator.use_botorch = use_botorch

        evaluator = RandomBoTorchTestEvaluator(dim=problem_dim, obj_fn_name=problem_str)
        if evaluator.obj_fn is None:
            logging.error("Failed to load the objective function for %s with dim %s", problem_str, problem_dim)
            continue

        population = SequencePopulation()
        population.add_individual(candidate)
        population.name = f"bo_exp_p3_{problem_str}_{model[0]}_dim{problem_dim}"

        llamevol.run_evolutions(llm, evaluator, prompt_generator, population, n_generation=n_generations, n_retry=3)
        log_aggressiveness_and_botorch(population, aggressiveness, use_botorch)
        progress_bar.update(1)

    log_file_name = f"bo_exp_p3_{model[0]}"
    log_dir_name = "logs_temp"
    log_population(population, save=True, dirname=log_dir_name, filename=log_file_name)

def test_multiple_processes():
    def mock_res_provider(*args, **kwargs):
        response = None
        with open("Experiments/bbob_test_res/successful_light_res2.md", "r") as f:
            response = f.read()
        return response
    
    llamevol = LLaMEvol()
    model = LLMS["deepseek/deepseek-chat"]
    llm = LLMmanager(api_key=model[1], model=model[0], base_url=model[2], max_interval=model[3])
    llm.mock_res_provider = mock_res_provider
    prompt_generator = BaselinePromptGenerator()

    budget = 100
    dim = 5
    problems = list(range(1, 25))
    instances = [[1, 2, 3]] * len(problems)
    repeat = 1
    time_out = 60 * budget * dim // 100
    evaluator = IOHEvaluator(budget=budget, dim=dim, problems=problems, instances=instances, repeat=repeat)

    n_generations = 1
    n_parent = 1
    n_parent_per_offspring = 1
    n_offspring = 1
    n_query_threads = n_parent

    n_eval_workers = 16
    population = ESPopulation(n_parent=n_parent, n_parent_per_offspring=n_parent_per_offspring, n_offspring=n_offspring)
    logging.info("Starting with %s processes", n_eval_workers)
    start = time.perf_counter()
    llamevol.run_evolutions(llm, evaluator, prompt_generator, population, n_generation=n_generations, n_retry=3, time_out_per_eval=time_out,
                          n_query_threads=n_query_threads, 
                          n_eval_workers=n_eval_workers
                          )
    end = time.perf_counter()
    logging.info("Time taken: %s with %s processes", end - start, n_eval_workers)

    n_eval_workers = 32
    population = ESPopulation(n_parent=n_parent, n_parent_per_offspring=n_parent_per_offspring, n_offspring=n_offspring)
    logging.info("Starting with %s processes", n_eval_workers)
    start = time.perf_counter()
    llamevol.run_evolutions(llm, evaluator, prompt_generator, population, n_generation=n_generations, n_retry=3, time_out_per_eval=time_out,
                          n_query_threads=n_query_threads,
                          n_eval_workers=n_eval_workers
                          )
    end = time.perf_counter()
    logging.info("Time taken: %s with %s processes", end - start, n_eval_workers)

if __name__ == "__main__":
    # logging.info(os.environ)
    # logging.info("CPU count: %s", os.cpu_count())

    # setup_logger(level=logging.DEBUG)
    setup_logger(level=logging.INFO)

    # test_multiple_processes()