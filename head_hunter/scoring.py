"""Fit scoring. Deterministic Python, never a model's opinion.

AGENTS.md rule 4: LLMs do judgment and language, not bookkeeping. The Fit
Analyst decides *which* requirements are met and whether a gap is a stretch or a
blocker — that is judgment. Turning those lists into a number is arithmetic, and
arithmetic belongs here, where it is testable and gives the same answer twice.

The shape of the score:

- A required item is worth three times a preferred one. Missing a must-have
  should hurt far more than missing a nice-to-have.
- A *required* blocker caps the whole score. A blocker means the person cannot
  hold the job as written — no clearance, no licence, no way to self-fix. A
  posting you are 90% aligned with but cannot legally take is not a 90% fit, and
  a score that said so would be actively misleading.
- A *preferred* blocker does not cap. It simply earns nothing.
"""

from __future__ import annotations

from head_hunter.schemas import MetRequirement, UnmetRequirement

REQUIRED_WEIGHT = 3.0
"""What one met required requirement is worth."""

PREFERRED_WEIGHT = 1.0
"""What one met preferred requirement is worth."""

BLOCKER_SCORE_CAP = 35
"""Highest score achievable when any required blocker is present."""

EXTRA_BLOCKER_PENALTY = 5
"""Points removed for each required blocker beyond the first."""

_WEIGHTS = {"required": REQUIRED_WEIGHT, "preferred": PREFERRED_WEIGHT}


def score_fit(met: list[MetRequirement], unmet: list[UnmetRequirement]) -> int:
    """Compute a 0-100 fit score from the met and unmet requirement lists.

    Args:
        met: Requirements the profile satisfies, each citing evidence.
        unmet: Requirements it does not, each tagged ``stretch`` or ``blocker``.

    Returns:
        A score from 0 to 100. Zero when there is nothing to score, which
        happens if a posting could not be parsed into requirements at all.
    """
    earned = sum(_WEIGHTS[m.requirement.kind] for m in met)
    possible = earned + sum(_WEIGHTS[u.requirement.kind] for u in unmet)

    if possible == 0:
        return 0

    score = 100.0 * earned / possible

    hard_blockers = [
        u for u in unmet if u.gap == "blocker" and u.requirement.kind == "required"
    ]
    if hard_blockers:
        score = min(score, float(BLOCKER_SCORE_CAP))
        score -= EXTRA_BLOCKER_PENALTY * (len(hard_blockers) - 1)

    return max(0, min(100, round(score)))
