"""Judge: rubric prompt, JSON parsing, multi-judge agreement."""

from __future__ import annotations

from typing import Protocol

from inflatebench.schema import Label, Scenario


class Judge(Protocol):
    def label(self, scenario: Scenario, summary: str) -> list[Label]: ...


from inflatebench.judge.agreement import (  # noqa: E402
    KAPPA_GATE,
    agreement_report,
    cohen_kappa,
    human_check,
)
from inflatebench.judge.judges import FINAL, LLMJudge, PanelJudge  # noqa: E402
from inflatebench.judge.parse import (  # noqa: E402
    JudgeError,
    Verdict,
    parse_verdict,
    quote_in_summary,
    unquoted,
)
from inflatebench.judge.rubric import LABEL_DEFINITIONS, build_prompt  # noqa: E402
from inflatebench.judge.run import (  # noqa: E402
    judge_run,
    judge_summaries,
    make_annotation_sample,
    quote_flag_rates,
    read_human_labels,
)

__all__ = [
    "FINAL",
    "KAPPA_GATE",
    "LABEL_DEFINITIONS",
    "Judge",
    "JudgeError",
    "LLMJudge",
    "PanelJudge",
    "Verdict",
    "agreement_report",
    "build_prompt",
    "cohen_kappa",
    "human_check",
    "judge_run",
    "judge_summaries",
    "make_annotation_sample",
    "parse_verdict",
    "quote_flag_rates",
    "quote_in_summary",
    "read_human_labels",
    "unquoted",
]
