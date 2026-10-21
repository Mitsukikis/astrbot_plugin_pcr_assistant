"""Pure, bounded composition of website candidates for up to three defenses."""

from collections.abc import Collection, Mapping
from itertools import islice, product


def _candidate_ids(candidate) -> frozenset[int] | None:
    if not isinstance(candidate, dict):
        return None
    ids = candidate.get('ids')
    if (
        not isinstance(ids, Collection)
        or isinstance(ids, (str, bytes, bytearray, Mapping))
        or len(ids) != 5
    ):
        return None
    if any(type(cid) is not int or not 1001 <= cid < 2000 for cid in ids):
        return None
    unique_ids = frozenset(ids)
    return unique_ids if len(unique_ids) == 5 else None


def build_disjoint_team_plans(candidate_groups, max_plans: int = 10) -> list[tuple[dict, ...]]:
    """Return complete plans in defense order, retaining original candidate dicts.

    Only the first ten entries of each of one to three groups are inspected.
    Invalid candidates and unordered duplicate teams are skipped without
    renumbering website positions. Plans sort by (sum(positions), positions),
    after checking at most 10 ** 3 combinations for repeated character IDs.
    Integer limits are clamped to 1..10; non-integer limits use the default 10.
    Missing groups or groups without usable candidates yield no plans.
    """
    if isinstance(candidate_groups, (str, bytes, bytearray, Mapping)):
        return []
    try:
        groups = list(islice(candidate_groups, 4))
    except TypeError:
        return []
    if not 1 <= len(groups) <= 3:
        return []

    options_by_group = []
    for group in groups:
        if isinstance(group, (str, bytes, bytearray, Mapping)):
            return []
        try:
            candidates = iter(group)
        except TypeError:
            return []

        options = []
        seen = set()
        for position, candidate in enumerate(islice(candidates, 10)):
            ids = _candidate_ids(candidate)
            if ids is None or ids in seen:
                continue
            seen.add(ids)
            options.append((position, candidate, ids))
        if not options:
            return []
        options_by_group.append(options)

    ranked_plans = []
    for combination in product(*options_by_group):
        used_ids = set()
        for _, _, ids in combination:
            if not used_ids.isdisjoint(ids):
                break
            used_ids.update(ids)
        else:
            positions = tuple(option[0] for option in combination)
            plan = tuple(option[1] for option in combination)
            ranked_plans.append((positions, plan))

    ranked_plans.sort(key=lambda item: (sum(item[0]), item[0]))
    if type(max_plans) is not int:
        max_plans = 10
    limit = max(1, min(10, max_plans))
    return [plan for _, plan in ranked_plans[:limit]]
