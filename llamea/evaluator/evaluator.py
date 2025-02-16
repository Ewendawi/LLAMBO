from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any
from .evaluator_result import EvaluatorResult

class AbstractEvaluator(ABC):
    def __init__(self):
        self.return_checker:Callable[[tuple], str] = lambda x: ""
        self.ignore_over_budget = False
        self.inject_critic = False

    @abstractmethod
    def problem_prompt(self) -> str:
        pass

    @abstractmethod
    def problem_name(self) -> str:
        pass

    @abstractmethod
    def problem_dim(self) -> int:
        pass

    @abstractmethod
    def eval_bugdet(self) -> int:
        pass

    @abstractmethod
    def evaluate(self, code, cls_name, cls=None, max_eval_workers:int = 0, use_multi_process=False, timeout:int=None, cls_init_kwargs:dict[str, Any]=None, cls_call_kwargs:dict[str, Any]=None) -> EvaluatorResult:
        pass

    def evaluate_others(self) -> list[EvaluatorResult]:
        pass