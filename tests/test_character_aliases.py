import pytest

import pcr_chara as chara
from arena_solution import parse_solution_command


@pytest.mark.parametrize('alias,cid', [
    ('小虎',1005), ('跳跳虎',1005), ('茉莉',1005),
    ('ams',1230), ('AMS',1230), ('AmS',1230), ('ＡＭＳ',1230), ('ems',1230),
    ('爱梅斯',1230), ('蚊子',1186), ('捏比亚',1186), ('涅比亚',1186),
    ('万圣跳跳虎',1141), ('万圣老虎',1141),
])
def test_nickname_resolves_without_database_cache(alias,cid):
    assert chara.CharaRoster().parse_team(alias) == ([cid],'')


@pytest.mark.parametrize('text,expected', [
    ('春剑黄骑ams蚊子布丁',[1089,1034,1230,1186,1007]),
    ('春剑 黄骑 AMS 蚊子 布丁',[1089,1034,1230,1186,1007]),
    ('春剑,黄骑/AmS、捏比亚|布丁',[1089,1034,1230,1186,1007]),
    ('春剑黄骑小虎空花布丁',[1089,1034,1005,1045,1007]),
    ('春剑黄骑跳跳虎空花布丁',[1089,1034,1005,1045,1007]),
    ('万圣跳跳虎小虎ams蚊子布丁',[1141,1005,1230,1186,1007]),
])
def test_nicknames_mix_and_concatenate_without_losing_version(text,expected):
    assert chara.CharaRoster().parse_team(text) == (expected,'')


def test_cache_refresh_reload_keeps_new_aliases_and_playable_ids(tmp_path,monkeypatch):
    monkeypatch.setattr(chara,'CHARA_NAME',{cid:list(names) for cid,names in chara.CHARA_NAME.items()})
    monkeypatch.setattr(chara,'_ROSTER',chara.CharaRoster())
    cache = tmp_path/'characters.json'
    characters = [{'id':1005,'name':'茉莉'},{'id':1186,'name':'涅比亚'},{'id':1230,'name':'爱梅斯'}]
    chara.extend_character_roster(characters,cache)
    for _ in range(2):
        assert chara.parse_team_names('小虎跳跳虎AMS蚊子捏比亚') == ([1005,1005,1230,1186,1186],'')
        assert chara.parse_team_names('菲欧Nebia') == ([1230,1186],'')
        chara.load_character_roster(cache)
    assert chara.name_for_id(1005) == '茉莉'
    assert chara.name_for_id(1230) == '爱梅斯'
    assert chara.name_for_id(1186) == '涅比亚'


@pytest.mark.parametrize('characters', [
    [{'id':1900,'name':'爱梅斯'},{'id':1909,'name':'涅比亚'}],
    [{'id':1900,'name':'爱梅斯'},{'id':1230,'name':'爱梅斯'},
     {'id':1909,'name':'涅比亚'},{'id':1186,'name':'涅比亚'}],
    [{'id':1186,'name':'涅比亚'},{'id':1909,'name':'涅比亚'},
     {'id':1230,'name':'爱梅斯'},{'id':1900,'name':'爱梅斯'}],
])
def test_legacy_npc_cache_cannot_move_aliases_back_to_story_ids(tmp_path,monkeypatch,characters):
    import json
    monkeypatch.setattr(chara,'CHARA_NAME',{cid:list(names) for cid,names in chara.CHARA_NAME.items()})
    monkeypatch.setattr(chara,'_ROSTER',chara.CharaRoster())
    cache = tmp_path/'characters.json'
    chara.extend_character_roster(characters,cache)
    assert {row['id'] for row in json.loads(cache.read_text(encoding='utf-8'))} == {1230,1186}
    for _ in range(2):
        assert chara.parse_team_names('AMS蚊子爱梅斯涅比亚菲欧Nebia') == ([1230,1186,1230,1186,1230,1186],'')
        chara.load_character_roster(cache)


@pytest.mark.parametrize('prefix,region', [('',1),('b',2),('B',2),('台',3),('日',4)])
def test_attached_solution_command_reaches_character_parser(prefix,region):
    parsed = parse_solution_command(prefix+'怎么拆春剑黄骑AMS蚊子布丁')
    assert parsed == (region,'春剑黄骑AMS蚊子布丁')
    assert chara.CharaRoster().parse_team(parsed[1]) == ([1089,1034,1230,1186,1007],'')


@pytest.mark.parametrize('text', ['怎么打个电话','如何打开文件','jjc查询东西','随机聊天'])
def test_other_prefix_boundaries_still_do_not_capture_ordinary_chat(text):
    assert parse_solution_command(text) is None


def test_repeated_nicknames_remain_same_id_for_existing_duplicate_validation():
    assert chara.CharaRoster().parse_team('小虎跳跳虎茉莉') == ([1005,1005,1005],'')


def test_unknown_alias_is_not_silently_replaced():
    ids,unknown = chara.CharaRoster().parse_team('ams不存在外号蚊子')
    assert ids == [1230,1186]
    assert unknown == '不存在外号'
