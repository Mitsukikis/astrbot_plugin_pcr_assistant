import ast
import json
from pathlib import Path

import pytest

import pcr_chara as chara


ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT/'pcr_wiki_aliases.json').read_text(encoding='utf-8'))
FACTS = [(row['id'],alias) for row in DATA['characters'] for alias in row['aliases']]
BASE_AST = ast.parse((ROOT/'pcr_chara_data.py').read_text(encoding='utf-8-sig'))
BASE = next(ast.literal_eval(node.value) for node in BASE_AST.body if isinstance(node,ast.Assign)
            and any(isinstance(target,ast.Name) and target.id=='CHARA_NAME' for target in node.targets))
LEGACY = {1900:1230,1908:1185,1909:1186,1918:1181,1920:1182}


def test_bundled_snapshot_has_documented_coverage_and_unique_owners():
    assert DATA['verified_at'] == '2026-10-21'
    assert len(DATA['characters']) == 292
    assert len(FACTS) == 1222
    assert len({row['id'] for row in DATA['characters']}) == 292
    owners = {}
    for row in DATA['characters']:
        assert type(row['id']) is int and 1001 <= row['id'] < 1900
        assert isinstance(row['name'],str) and row['name']
        for alias in row['aliases']:
            assert isinstance(alias,str) and 0 < len(alias) <= 100
            assert 'UNIQ--' not in alias
            key = chara.compact_chara_text(alias)
            assert key
            assert owners.setdefault(key,row['id']) == row['id']


@pytest.mark.parametrize('cid,alias', FACTS)
def test_every_bundled_alias_resolves_to_its_verified_character(cid,alias):
    assert chara.CharaRoster().parse_team(alias) == ([cid],'')


def test_existing_aliases_keep_identity_except_known_playable_npc_migrations():
    baseline = chara.CharaRoster(BASE)
    expanded = chara.CharaRoster()
    for names in BASE.values():
        for alias in names:
            before,unknown = baseline.parse_team(alias)
            assert not unknown
            expected = [LEGACY.get(cid,cid) for cid in before]
            assert expanded.parse_team(alias) == (expected,''),alias


@pytest.mark.parametrize('text,ids', [
    ('elsAMS蚊子小虎布丁',[1290,1230,1186,1005,1007]),
    ('ELS 网管 捣蛋妖精 跳跳虎 水m',[1290,1230,1186,1005,1270]),
    ('ＥＬＳ ＡＭＳ 白猫 万圣跳跳虎 布丁',[1290,1230,1806,1141,1007]),
    ('镜华（夏日）美美（夏日）未奏希（夏日）',[1227,1229,1228]),
    ('xcw nnk 水猫',[1036,1070,1079]),
    ('花凛 绿色恶魔 兰法 美空',[1185,1185,1181,1182]),
])
def test_expanded_aliases_compose_and_preserve_version_and_existing_conflicts(text,ids):
    assert chara.CharaRoster().parse_team(text) == (ids,'')


@pytest.mark.parametrize('text', ['泥头车','能天使'])
def test_new_ambiguous_names_are_not_arbitrarily_assigned(text):
    assert chara.CharaRoster().parse_team(text)[1]


@pytest.mark.parametrize('old,cid,name', [(1908,1185,'花凛'),(1918,1181,'兰法'),(1920,1182,'美空')])
def test_old_cache_cannot_override_new_playable_roles(tmp_path,monkeypatch,old,cid,name):
    monkeypatch.setattr(chara,'CHARA_NAME',{key:list(values) for key,values in chara.CHARA_NAME.items()})
    monkeypatch.setattr(chara,'_ROSTER',chara.CharaRoster())
    cache = tmp_path/'characters.json'
    chara.extend_character_roster([{'id':old,'name':name}],cache)
    chara.load_character_roster(cache)
    assert chara.parse_team_names(name) == ([cid],'')
    assert chara.parse_team_names('ELSAMS蚊子小虎水m') == ([1290,1230,1186,1005,1270],'')


def test_full_names_override_another_characters_nickname():
    roster = chara.CharaRoster({1001:['角色甲','角色乙'],1002:['角色乙','乙别称']})
    assert roster.parse_team('角色乙乙别称') == ([1002,1002],'')


@pytest.mark.parametrize('separator', [' ', '\t', '\n', ',', '，', '/', '|', '+', '_', '-', '、'])
def test_explicit_separators_do_not_merge_two_members_into_a_duo(separator):
    text = separator.join(['初音','栞','布丁','黄骑','小虎'])
    assert chara.CharaRoster().parse_team(text) == ([1012,1038,1007,1034,1005],'')


@pytest.mark.parametrize('text,expected', [
    ('秋乃 咲恋 布丁 黄骑 小虎',[1032,1028,1007,1034,1005]),
    ('静流 璃乃 布丁 黄骑 小虎',[1049,1011,1007,1034,1005]),
    ('初音、栞 布丁 黄骑 小虎 AMS',[1807,1007,1034,1005,1230]),
    ('怜 （ 新年 ） 布丁 黄骑 小虎 AMS',[1089,1007,1034,1005,1230]),
    ('tp+3 布丁 黄骑 小虎 AMS',[1115,1007,1034,1005,1230]),
])
def test_duo_names_and_parenthesized_variants_remain_available(text,expected):
    assert chara.CharaRoster().parse_team(text) == (expected,'')


@pytest.mark.parametrize('separator', [' ', ',', '，', '/', '|', '+', '_', '-', '、'])
def test_operator_aliases_work_inside_larger_punctuation_lists(separator):
    assert chara.CharaRoster().parse_team(separator.join(['tp+3','布丁','黄骑','小虎','AMS'])) == ([1115,1007,1034,1005,1230],'')
