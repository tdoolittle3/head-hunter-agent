"""Fit scoring is arithmetic, so it gets exercised like arithmetic.

The behaviour that matters most: a required blocker has to dominate the score,
because a posting you cannot legally take is not a good fit no matter how well
the rest lines up.
"""

from __future__ import annotations

from head_hunter.schemas import MetRequirement, Requirement, UnmetRequirement
from head_hunter.scoring import BLOCKER_SCORE_CAP, score_fit


def req(kind: str = "required", category: str = "skill") -> Requirement:
    return Requirement(text=f"a {kind} {category}", kind=kind, category=category)


def met(kind: str = "required") -> MetRequirement:
    return MetRequirement(requirement=req(kind), evidence_ids=["ev-1"])


def unmet(kind: str = "required", gap: str = "stretch") -> UnmetRequirement:
    return UnmetRequirement(requirement=req(kind), gap=gap, note="because")


def test_no_requirements_scores_zero() -> None:
    assert score_fit([], []) == 0


def test_everything_met_scores_100() -> None:
    assert score_fit([met("required"), met("preferred")], []) == 100


def test_nothing_met_scores_zero() -> None:
    assert score_fit([], [unmet("required"), unmet("preferred")]) == 0


def test_required_counts_more_than_preferred() -> None:
    # One required met out of (1 required + 1 preferred) = 3 / 4.
    only_required = score_fit([met("required")], [unmet("preferred")])
    # One preferred met out of the same pool = 1 / 4.
    only_preferred = score_fit([met("preferred")], [unmet("required")])

    assert only_required == 75
    assert only_preferred == 25
    assert only_required > only_preferred


def test_a_required_blocker_caps_an_otherwise_strong_fit() -> None:
    strong = [met("required")] * 9
    with_blocker = score_fit(strong, [unmet("required", "blocker")])

    assert score_fit(strong, [unmet("required", "stretch")]) == 90
    assert with_blocker <= BLOCKER_SCORE_CAP


def test_extra_blockers_push_the_score_further_down() -> None:
    strong = [met("required")] * 9
    one = score_fit(strong, [unmet("required", "blocker")])
    two = score_fit(strong, [unmet("required", "blocker")] * 2)
    three = score_fit(strong, [unmet("required", "blocker")] * 3)

    assert one > two > three


def test_a_preferred_blocker_does_not_cap() -> None:
    """A nice-to-have you cannot get should not sink the whole report."""
    strong = [met("required")] * 9
    score = score_fit(strong, [unmet("preferred", "blocker")])

    assert score > BLOCKER_SCORE_CAP


def test_score_never_leaves_the_0_to_100_range() -> None:
    many_blockers = [unmet("required", "blocker")] * 50
    assert score_fit([], many_blockers) == 0
    assert 0 <= score_fit([met()] * 3, many_blockers) <= 100


def test_scoring_is_repeatable() -> None:
    m, u = [met(), met("preferred")], [unmet("required", "stretch")]
    assert len({score_fit(m, u) for _ in range(5)}) == 1
