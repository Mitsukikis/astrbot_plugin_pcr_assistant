"""Offline tests for complete, ordered and bounded arena team composition."""

from copy import deepcopy
from itertools import product

import pytest

import arena_team_builder as builder
from arena_team_builder import build_disjoint_team_plans


def candidate(start, **metadata):
    return {'ids': list(range(start, start + 5)), **metadata}


def disjoint_groups(*sizes):
    return [
        [candidate(1001 + group * 200 + position * 5, position=position)
         for position in range(size)]
        for group, size in enumerate(sizes)
    ]


@pytest.mark.parametrize('group_count', [1, 2, 3])
@pytest.mark.parametrize('limit', [5, 10])
def test_returns_five_or_ten_plans_when_available(group_count, limit):
    groups = disjoint_groups(*([10] * group_count))

    plans = build_disjoint_team_plans(groups, max_plans=limit)

    assert isinstance(plans, list)
    assert len(plans) == limit
    assert all(isinstance(plan, tuple) and len(plan) == group_count for plan in plans)
    positions = [tuple(team['position'] for team in plan) for plan in plans]
    expected = sorted(product(range(10), repeat=group_count),
                      key=lambda indices: (sum(indices), indices))[:limit]
    assert positions == expected


def test_default_returns_ten_plans():
    assert len(build_disjoint_team_plans(disjoint_groups(4, 4))) == 10


@pytest.mark.parametrize(('group_count', 'expected_positions'), [
    (2, [(0, 1), (1, 0), (1, 1)]),
    (3, [(0, 1, 0), (0, 1, 1), (1, 0, 1), (1, 1, 1)]),
])
def test_rejects_character_reuse_across_every_team(group_count, expected_positions):
    groups = [
        [candidate(1001, position=0), candidate(1011, position=1)],
        [candidate(1005, position=0), candidate(1021, position=1)],
        [candidate(1009, position=0), candidate(1031, position=1)],
    ][:group_count]

    plans = build_disjoint_team_plans(groups)

    assert [tuple(team['position'] for team in plan) for plan in plans] == expected_positions
    for plan in plans:
        ids = [cid for team in plan for cid in team['ids']]
        assert len(ids) == len(set(ids)) == group_count * 5


def test_preserves_defense_order_original_dicts_and_opaque_metadata():
    images = [object(), object(), object()]
    groups = [
        [candidate(1501, defense=0, image=images[0])],
        [candidate(1201, defense=1, image=images[1])],
        [candidate(1001, defense=2, image=images[2])],
    ]

    plans = build_disjoint_team_plans(groups)

    assert len(plans) == 1
    for index, team in enumerate(plans[0]):
        assert team is groups[index][0]
        assert team['defense'] == index
        assert team['image'] is images[index]


@pytest.mark.parametrize('sizes', [(1,), (1, 1), (1, 1, 1), (1, 2), (1, 1, 3), (2, 2)])
def test_returns_only_real_results_even_when_fewer_than_five(sizes):
    groups = disjoint_groups(*sizes)
    expected_positions = sorted(product(*(range(size) for size in sizes)),
                                key=lambda indices: (sum(indices), indices))

    plans = build_disjoint_team_plans(groups)

    assert len(plans) == len(expected_positions)
    assert [tuple(team['position'] for team in plan) for plan in plans] == expected_positions


@pytest.mark.parametrize('groups', [
    None, [], (), 42, 'groups', b'groups', {'ids': []},
    [None], [[]], [42], ['group'], [b'group'], [{}],
    [[candidate(1001)], None],
    [[candidate(1001)], []],
    [[candidate(1001)], [None, {}, {'ids': [1002]}]],
    [[candidate(1001)], [], [candidate(1201)]],
    [[candidate(1001)], [candidate(1101)], None],
    [[candidate(1001)]] * 4,
])
def test_empty_missing_or_invalid_groups_never_become_partial_plans(groups):
    assert build_disjoint_team_plans(groups) == []


def test_no_alternatives_for_conflicting_teams():
    assert build_disjoint_team_plans([[candidate(1001)], [candidate(1005)]]) == []


def test_pairwise_solutions_do_not_fake_a_full_three_team_composition():
    groups = [[candidate(1001), candidate(1101)] for _ in range(3)]

    assert all(build_disjoint_team_plans([groups[first], groups[second]])
               for first, second in [(0, 1), (0, 2), (1, 2)])
    assert build_disjoint_team_plans(groups) == []


class CoercionTrap:
    def __int__(self):
        raise AssertionError('IDs must not be coerced')

    def __hash__(self):
        raise AssertionError('Invalid IDs must not be hashed')


class IntegerSubclass(int):
    pass


@pytest.mark.parametrize('bad_id', [
    1000, 2000, 0, -1005, 100501, 10 ** 100,
    True, False, 1005.0, float('nan'), float('inf'),
    '1005', '100501', '<script>alert(1)</script>',
    "__import__('os').system('untrusted')", None,
    [1005], {'id': 1005}, {1005}, CoercionTrap(), IntegerSubclass(1005),
])
def test_invalid_or_malicious_ids_are_skipped_without_coercion(bad_id):
    invalid = {'ids': [1001, 1002, 1003, 1004, bad_id]}
    valid = candidate(1101)

    plans = build_disjoint_team_plans([[invalid, valid]])

    assert len(plans) == 1
    assert plans[0][0] is valid
    assert build_disjoint_team_plans([[invalid]]) == []


@pytest.mark.parametrize('invalid', [
    None, [], 1001, 'candidate', {}, {'id': [1001, 1002, 1003, 1004, 1005]},
    {'ids': None}, {'ids': 1001}, {'ids': []},
    {'ids': [1001, 1002, 1003, 1004]},
    {'ids': [1001, 1002, 1003, 1004, 1005, 1006]},
    {'ids': [1001, 1002, 1003, 1004, 1004]},
    {'ids': '1001,1002,1003,1004,1005'}, {'ids': b'12345'},
    {'ids': {1001: 1, 1002: 1, 1003: 1, 1004: 1, 1005: 1}},
])
def test_malformed_candidates_are_skipped(invalid):
    valid = candidate(1101)
    plans = build_disjoint_team_plans([[invalid, valid]])
    assert len(plans) == 1
    assert plans[0][0] is valid


@pytest.mark.parametrize('container', [list, tuple, set, frozenset])
def test_valid_boundary_ids_in_unordered_or_ordered_collections(container):
    team = {'ids': container([1001, 1002, 1500, 1998, 1999])}
    assert build_disjoint_team_plans([[team]])[0][0] is team


def test_deduplicates_unordered_ids_and_keeps_earliest_candidate():
    first = candidate(1001, image=b'first image')
    reordered = {'ids': tuple(reversed(first['ids'])), 'image': b'later image'}
    second = candidate(1101)
    duplicate_second = {'ids': set(second['ids'])}

    plans = build_disjoint_team_plans([[first, reordered, second, duplicate_second]])

    assert len(plans) == 2
    assert plans[0][0] is first
    assert plans[1][0] is second


@pytest.mark.parametrize('gap', [None, {'ids': [1205, 1204, 1203, 1202, 1201]}])
def test_ranking_uses_original_positions_after_invalid_or_duplicate_gaps(gap):
    groups = [
        [candidate(1001, position=0), candidate(1011, position=1)],
        [{'ids': [1001, 1011, 1301, 1302, 1303], 'position': 0},
         candidate(1201, position=1), gap, candidate(1211, position=3)],
    ]

    plans = build_disjoint_team_plans(groups)

    assert [tuple(team['position'] for team in plan) for plan in plans] == [
        (0, 1), (1, 1), (0, 3), (1, 3),
    ]


def test_deterministic_global_ranking_and_lexicographic_ties():
    groups = disjoint_groups(3, 3, 3)
    expected = sorted(product(range(3), repeat=3),
                      key=lambda indices: (sum(indices), indices))[:10]

    for _ in range(3):
        plans = build_disjoint_team_plans(groups)
        assert [tuple(team['position'] for team in plan) for plan in plans] == expected
        for plan in plans:
            assert all(team is groups[index][team['position']]
                       for index, team in enumerate(plan))


@pytest.mark.parametrize(('limit', 'expected_count'), [
    (-100, 1), (0, 1), (1, 1), (5, 5), (10, 10), (11, 10), (10 ** 100, 10),
])
def test_integer_limits_are_clamped(limit, expected_count):
    assert len(build_disjoint_team_plans(disjoint_groups(10, 10), limit)) == expected_count


@pytest.mark.parametrize('limit', [None, '5', 5.5, True, float('nan')])
def test_non_integer_limits_use_the_default(limit):
    assert len(build_disjoint_team_plans(disjoint_groups(10, 10), limit)) == 10


def test_input_contents_and_nested_metadata_are_unchanged():
    groups = disjoint_groups(3, 3)
    groups[0][0]['metadata'] = {'names': ['same name'], 'votes': [1, 2]}
    groups[0][0]['image'] = b'opaque image bytes'
    groups[1].insert(1, {'ids': list(reversed(groups[1][0]['ids']))})
    groups[1].insert(2, {'ids': ['1001', 1002, 1003, 1004, 1005]})
    before = deepcopy(groups)
    original_objects = [[id(team) for team in group] for group in groups]

    build_disjoint_team_plans(groups, 5)

    assert groups == before
    assert [[id(team) for team in group] for group in groups] == original_objects


def test_variants_with_different_ids_and_identical_names_remain_separate():
    base = candidate(1001, name='same character', names=['same name'] * 5)
    variant = candidate(1101, name='same character', names=['same name'] * 5)

    plans = build_disjoint_team_plans([[base], [variant]])

    assert len(plans) == 1
    assert plans[0][0] is base
    assert plans[0][1] is variant


def test_identical_ids_conflict_even_if_names_differ():
    first = candidate(1001, name='base')
    second = candidate(1001, name='different name')
    assert build_disjoint_team_plans([[first], [second]]) == []


def test_reads_no_more_than_ten_entries_per_group():
    def bounded_candidates(start):
        for position in range(10):
            yield candidate(start + position * 5, position=position)
        raise AssertionError('The eleventh website entry must not be read')

    groups = [bounded_candidates(start) for start in (1001, 1201, 1401)]
    assert len(build_disjoint_team_plans(groups)) == 10


def test_invalid_first_ten_entries_are_not_backfilled_from_later_options():
    group = [None] * 10 + [candidate(1001)]
    assert build_disjoint_team_plans([group]) == []


def test_duplicate_first_ten_entries_are_not_backfilled():
    first = candidate(1001)
    group = [first] * 10 + [candidate(1101)]
    plans = build_disjoint_team_plans([group])
    assert len(plans) == 1
    assert plans[0][0] is first


def test_combinations_are_bounded_to_one_thousand(monkeypatch):
    inspected = 0

    def counted_product(*groups):
        nonlocal inspected
        assert len(groups) == 3
        assert all(len(group) == 10 for group in groups)
        for combination in product(*groups):
            inspected += 1
            assert inspected <= 1000
            yield combination

    monkeypatch.setattr(builder, 'product', counted_product)

    assert len(build_disjoint_team_plans(disjoint_groups(12, 12, 12), 1)) == 1
    assert inspected == 1000


def test_oversized_outer_iterable_is_rejected_after_four_groups():
    inspected = 0

    def groups():
        nonlocal inspected
        for _ in range(4):
            inspected += 1
            yield [candidate(1001)]
        raise AssertionError('More than four groups must not be inspected')

    assert build_disjoint_team_plans(groups()) == []
    assert inspected == 4
