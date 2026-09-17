"""Resume traceability. Deterministic Python, never a model's opinion.

AGENTS.md rule 2: every ``ResumeBullet`` references at least one ``evidence_id``,
and :func:`validate_resume` fails the bullet if the reference is missing or the
bullet introduces a number, tool, company, or title that does not appear in the
cited evidence. The schema enforces the easy half (a bullet cannot be built with
zero citations); this module enforces the rest.

Two decisions worth knowing about, because they shape what passes:

**What counts as "the cited evidence".** Not only the ``Evidence.source_text``.
A bullet citing ``ev-1234`` may also draw on the records anchored to that
evidence: the accomplishment that was built from it (situation, action, result,
metrics, tools), the role that accomplishment belongs to (company, title), and
any skill that cites it. Those fields exist precisely because the Interviewer
structured the user's words, and every one of them already had to be backed by
the same statement. Widening the corpus this far and no further is what lets a
bullet say "9 days" when the user said "nine days", while still failing a bullet
that reaches into a *different* role's evidence for a company name.

**It fails closed.** An unusual verb the stop-list does not know can be flagged
as an untraceable proper noun. That is the error we want to make: the failure
message names the exact word, the Resume Tailor rewords the bullet, and nothing
invented reaches the page. The opposite error ships a resume claiming something
the user never said, which is the one thing this system promises not to do.
"""

from __future__ import annotations

import re

from head_hunter.schemas import (
    Profile,
    Resume,
    ResumeBullet,
    ValidationFailure,
    ValidationResult,
)

_WORD_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
    "thousand": 1000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}

_MAGNITUDES = {
    "k": 1000,
    "m": 1_000_000,
    "b": 1_000_000_000,
    "thousand": 1000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

_COMMON_WORDS = frozenset(
    """
    a about above across after against all almost along also although always among an
    and another any are around as at back be because been before being below between
    both but by came can cannot come could did do does doing done down during each
    early either else end enough even ever every first for from front full further
    gave get give given giving go going got had half has have having he her here hers
    him his how however i if in include included including inside instead into is it
    its itself just keep kept last late later least left less let like little made
    make making many may me might mine more most much must my myself near need never
    new next no none nor not now of off often on once one only onto or other others
    our ours out outside over own part per perhaps put rather re right same second
    several shall she should since so some still such than that the their theirs them
    themselves then there these they third this those though through throughout thus
    to today together too toward under until up upon us use used using very was way
    we well were what when where whether which while who whom whose why will with
    within without work worked working would year years yet you your yours

    accelerated achieved acquired adapted added addressed adopted advanced advised
    advocated aligned analysed analyzed answered anticipated applied appointed
    approved arranged assembled assessed assigned assisted assumed audited authored
    automated awarded balanced began boosted bridged brought budgeted built
    calculated captured carried centralised centralized chaired championed changed
    clarified classified closed coached collaborated collected combined communicated
    compared compiled completed composed computed conceived conducted configured
    connected consolidated constructed consulted contributed controlled converted
    convinced coordinated corrected created cultivated customised customized cut
    debugged decentralised decentralized decided decreased defined delegated
    delivered demonstrated deployed derived designed detected determined developed
    devised diagnosed directed discovered dispatched displayed distributed
    diversified documented doubled drafted drove earned edited educated eliminated
    enabled encouraged enforced engineered enhanced enlisted ensured established
    estimated evaluated examined exceeded executed expanded expedited explained
    explored extended extracted facilitated filed finalised finalized financed
    focused forecast forged formed formulated fostered founded gathered generated
    governed grew guided halved handled headed helped hired identified implemented
    improved increased influenced informed initiated innovated inspected inspired
    installed instituted instructed integrated interpreted interviewed introduced
    invented investigated launched led lectured leveraged lifted lowered maintained
    managed mapped marketed measured mediated mentored merged migrated minimised
    minimized mobilised mobilized modelled modeled moderated modernised modernized
    modified monitored motivated navigated negotiated observed obtained operated
    optimised optimized orchestrated ordered organised organized originated
    outlined overhauled oversaw owned partnered performed persuaded pioneered
    planned prepared presented prevented prioritised prioritized processed procured
    produced programmed promoted proposed protected proved provided publicised
    publicized published purchased pursued raised ran ranked rated realigned
    rebuilt received recommended reconciled recorded recovered recruited redesigned
    reduced refactored refined reformed regulated rehabilitated reinforced
    reorganised reorganized repaired replaced reported represented researched
    resolved responded restored restructured retained retrieved reviewed revised
    revitalised revitalized rewrote saved scaled scheduled screened secured
    selected separated served serviced set shaped shipped simplified solved sourced
    spearheaded specified spoke sponsored staffed standardised standardized started
    steered streamlined strengthened structured studied submitted succeeded
    summarised summarized supervised supplied supported surpassed surveyed
    sustained synthesised synthesized systematised systematized tailored targeted
    taught tested tightened tracked trained transformed translated trimmed tripled
    troubleshot turned uncovered unified updated upgraded utilised utilized
    validated verified visualised visualized won wrote

    january february march april may june july august september october november
    december monday tuesday wednesday thursday friday saturday sunday

    company customer customers data engineer engineering engineers team teams
    product products project projects platform service services system systems
    business client clients code cost costs delivery design development growth
    hiring leadership manager management onboarding operations organisation
    organization performance pipeline pipelines process processes production
    quality release releases reliability report reporting reports revenue roadmap
    scale scope security software staff stakeholder stakeholders strategy support
    testing time training uptime users
    """.split()
)
"""Words a capitalized token is allowed to be without tracing to evidence.

Function words, the standard resume verb vocabulary, months, and generic
industry nouns. Anything outside this list that is capitalized mid-sentence is
treated as a name the bullet has to justify.
"""

_SENTENCE_END = re.compile(r"[.!?:;]\s*$|^[-–—]\s*$")

_TOKEN_TRIM = re.compile(r"^[^\w$]+|[^\w%+#]+$")


def _strip_token(raw: str) -> str:
    """Trim surrounding punctuation, keeping characters that live inside names."""
    token = _TOKEN_TRIM.sub("", raw)
    if token.lower().endswith("'s"):
        token = token[:-2]
    return token


def _scaled(value: float) -> str:
    """Render a number canonically, so 2.0 and 2 compare equal."""
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def _number_variants(digits: str, suffix: str, next_word: str) -> set[str]:
    """Return the canonical form of one numeric mention.

    A magnitude replaces the bare value rather than joining it: ``$2M`` is two
    million, and letting it also match a bare ``2`` would let a bullet claim
    "$2M saved" off evidence that only ever said "two days". ``2 million``,
    ``2M`` and ``2000000`` all reduce to the same string, which is the point.
    """
    try:
        value = float(digits.replace(",", ""))
    except ValueError:
        return set()

    magnitude = _MAGNITUDES.get(suffix.lower()) or _MAGNITUDES.get(next_word.lower())
    if magnitude:
        return {_scaled(value * magnitude)}
    return {_scaled(value)}


def _numeric_token(token: str) -> bool:
    """Report whether a token is a quantity rather than a name containing digits.

    ``$2M`` and ``40%`` are quantities. ``S3``, ``k8s`` and ``Python3`` are
    names, and must be checked as names -- otherwise "migrated to S3" would
    pass on evidence that merely mentioned the number three.
    """
    match = _NUMBER_RE.search(token)
    if match is None:
        return False
    return not any(char.isalpha() for char in token[: match.start()])


def _number_mentions(text: str) -> list[tuple[str, set[str]]]:
    """Find every number in ``text``, digits or spelled out.

    Returns:
        One ``(as written, canonical forms)`` pair per mention. Ordinals are
        skipped: "first year" is not a claim about quantity.
    """
    mentions: list[tuple[str, set[str]]] = []
    words = text.split()

    for index, raw in enumerate(words):
        following = _strip_token(words[index + 1]) if index + 1 < len(words) else ""
        token = _strip_token(raw)

        matches = list(_NUMBER_RE.finditer(raw))
        if matches and _numeric_token(raw):
            for position, match in enumerate(matches):
                last = position == len(matches) - 1
                tail = raw[match.end() :].strip("%.,)-/") if last else ""
                variants = _number_variants(
                    match.group(), tail, following if last else ""
                )
                if variants:
                    mentions.append((token or raw, variants))
            continue

        word = token.lower()
        if word in _WORD_NUMBERS:
            value = float(_WORD_NUMBERS[word])
            magnitude = _MAGNITUDES.get(following.lower())
            mentions.append(
                (token, {_scaled(value * magnitude)} if magnitude else {_scaled(value)})
            )

    return mentions


def _corpus_numbers(texts: list[str]) -> set[str]:
    """Every canonical number the cited evidence contains."""
    numbers: set[str] = set()
    for text in texts:
        for _, variants in _number_mentions(text):
            numbers |= variants
    return numbers


def _corpus_terms(texts: list[str]) -> set[str]:
    """Every word the cited evidence contains, lowercased and split apart.

    ``CI/CD`` and ``month-end`` go in whole and in pieces, so a bullet may cite
    either form.
    """
    terms: set[str] = set()
    for text in texts:
        for raw in text.split():
            token = _strip_token(raw).lower()
            if not token:
                continue
            terms.add(token)
            terms.update(part for part in re.split(r"[/\-_.]", token) if part)
    return terms


def _known_names(profile: Profile) -> set[str]:
    """Proper nouns the profile knows about anywhere: companies, tools, schools.

    Used to judge the first word of a bullet, where an ordinary verb is
    capitalized for grammar rather than because it is a name.
    """
    names: set[str] = set()
    sources = [
        *(role.company for role in profile.roles),
        *(role.title for role in profile.roles),
        *(skill.name for skill in profile.skills),
        *(tool for acc in profile.accomplishments for tool in acc.tools),
        *(edu.institution for edu in profile.education),
        *(edu.credential for edu in profile.education),
    ]
    for source in sources:
        if source:
            names |= _corpus_terms([source])
    return names


def _is_hard_token(token: str) -> bool:
    """Report whether a token is unmistakably a name, acronym, or product.

    ``AWS``, ``BigQuery``, ``k8s`` and ``S3`` are never ordinary English, so
    they are checked wherever they appear, including as the first word.
    """
    letters = [c for c in token if c.isalpha()]
    if not letters:
        return False
    if len(token) >= 2 and token.upper() == token and any(c.isdigit() for c in token):
        return True
    if len(letters) >= 2 and all(c.isupper() for c in letters):
        return True
    if re.search(r"[a-z][A-Z]", token):
        return True
    return any(c.isdigit() for c in token) and any(c.isalpha() for c in token)


def _term_in_corpus(token: str, corpus: set[str]) -> bool:
    """Report whether a bullet's token is present in the cited evidence."""
    lowered = token.lower()
    if lowered in corpus:
        return True
    if lowered.endswith("s") and lowered[:-1] in corpus:
        return True
    if lowered + "s" in corpus:
        return True
    parts = [part for part in re.split(r"[/\-_.]", lowered) if part]
    return len(parts) > 1 and all(part in corpus for part in parts)


def _untraceable_terms(text: str, corpus: set[str], known_names: set[str]) -> list[str]:
    """Return the names in a bullet that the cited evidence does not support."""
    flagged: list[str] = []
    words = text.split()
    at_sentence_start = True

    for raw in words:
        token = _strip_token(raw)
        if not token or _numeric_token(token):
            at_sentence_start = at_sentence_start or bool(_SENTENCE_END.search(raw))
            continue

        hard = _is_hard_token(token)
        capitalized = token[0].isupper()

        should_check = False
        if hard:
            should_check = True
        elif capitalized and token.lower() not in _COMMON_WORDS:
            # A capitalized word at the start of a sentence is usually there for
            # grammar. Only judge it when the profile knows it as a real name.
            should_check = not at_sentence_start or token.lower() in known_names

        if should_check and not _term_in_corpus(token, corpus):
            if token not in flagged:
                flagged.append(token)

        at_sentence_start = bool(_SENTENCE_END.search(raw))

    return flagged


def _cited_texts(
    profile: Profile, evidence_ids: list[str]
) -> tuple[list[str], list[str]]:
    """Gather everything the cited evidence supports.

    Args:
        profile: The career profile the citations point into.
        evidence_ids: The ids one bullet cites.

    Returns:
        The supporting texts, and the ids that are not in the profile at all.
    """
    cited = set(evidence_ids)
    missing = [eid for eid in evidence_ids if profile.evidence_by_id(eid) is None]

    texts: list[str] = [
        evidence.source_text for evidence in profile.evidence if evidence.id in cited
    ]

    roles = {role.id: role for role in profile.roles}
    for accomplishment in profile.accomplishments:
        if accomplishment.evidence_id not in cited:
            continue
        texts += [
            accomplishment.situation,
            accomplishment.action,
            accomplishment.result,
            *accomplishment.metrics,
            *accomplishment.tools,
        ]
        role = roles.get(accomplishment.role_id)
        if role is not None:
            texts += [role.company, role.title, role.summary or ""]

    for skill in profile.skills:
        if cited & set(skill.evidence_ids):
            texts.append(skill.name)

    return [text for text in texts if text], missing


def _check_bullet(
    bullet: ResumeBullet, profile: Profile, known_names: set[str]
) -> str | None:
    """Return why a bullet fails, or None if it traces cleanly."""
    if not bullet.text.strip():
        return "The bullet is empty."

    texts, missing = _cited_texts(profile, bullet.evidence_ids)
    if missing:
        return (
            "Cites evidence that is not in the profile: "
            + ", ".join(sorted(missing))
            + ". Use ids exactly as load_tailoring_context returned them."
        )
    if not texts:
        return (
            "The cited evidence has no text behind it, so nothing in this "
            "bullet can be checked."
        )

    reasons: list[str] = []

    corpus_numbers = _corpus_numbers(texts)
    unsupported = [
        written
        for written, variants in _number_mentions(bullet.text)
        if not variants & corpus_numbers
    ]
    if unsupported:
        reasons.append(
            "These numbers are not in the cited evidence: "
            + ", ".join(dict.fromkeys(unsupported))
        )

    flagged = _untraceable_terms(bullet.text, _corpus_terms(texts), known_names)
    if flagged:
        reasons.append(
            "These names are not in the cited evidence: " + ", ".join(flagged)
        )

    if not reasons:
        return None

    return (
        "; ".join(reasons)
        + ". Either cite the evidence that says so, or rewrite the bullet "
        "using only what the cited evidence contains."
    )


def validate_resume(resume: Resume, profile: Profile) -> ValidationResult:
    """Check every bullet against the evidence it cites.

    This is plain Python on purpose (AGENTS.md rule 4). The Resume Tailor
    proposes language; whether that language is supported is arithmetic and
    string comparison, and it gives the same answer twice.

    Args:
        resume: The draft to check.
        profile: The career profile its citations point into.

    Returns:
        A :class:`ValidationResult` listing every bullet that could not be
        traced, with the reason. ``passed`` is true only when there are none.
    """
    known_names = _known_names(profile)
    failures: list[ValidationFailure] = []
    checked = 0

    for section in resume.sections:
        for bullet in section.bullets:
            checked += 1
            reason = _check_bullet(bullet, profile, known_names)
            if reason is not None:
                failures.append(
                    ValidationFailure(
                        section_title=section.title,
                        bullet_text=bullet.text,
                        reason=reason,
                    )
                )

    return ValidationResult(
        passed=not failures, failures=failures, checked_bullets=checked
    )
