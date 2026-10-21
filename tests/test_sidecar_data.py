import ast
import asyncio
import json
import sqlite3
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def helpers():
    path = Path(__file__).resolve().parents[1] / 'sidecar' / 'pcr_real_api.py'
    source = ast.parse(path.read_text(encoding='utf-8-sig'))
    names = {'_character_roster','_extract_members','_model_json','_clan_bosses','_select_account_alias','_ranking_item','_ranking_name_map'}
    body = [node for node in source.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names]
    namespace = dict(Path=Path, sqlite3=sqlite3, json=json, BATCH_ACCOUNT='BATCH_RUNNER',
                     ClanBattleBossInfoRequest=types.SimpleNamespace)
    exec(compile(ast.Module(body=body,type_ignores=[]),str(path),'exec'),namespace)
    return types.SimpleNamespace(**{name:namespace[name] for name in names})


def test_nested_clan_members_are_actual_roster(helpers):
    class Response:
        def json(self):
            return json.dumps({'clan':{'members':[{'viewer_id':123,'name':'合成成员'}]}})
    assert helpers._extract_members(Response()) == [{'viewer_id':123,'name':'合成成员'}]
    assert helpers._extract_members({'clan':{'members':[]}}) == []


def test_game_database_roster_does_not_require_game_login(helpers,tmp_path):
    with sqlite3.connect(tmp_path/'202610141504.db') as connection:
        connection.execute('create table unit_data(unit_id integer,unit_name text)')
        connection.executemany('insert into unit_data values (?,?)',[(100101,'合成角色'),(900101,'敌人'),(100102,'非角色变体')])
    result=helpers._character_roster(tmp_path)
    assert result['database_version']=='202610141504'
    assert result['characters']==[{'id':1001,'name':'合成角色'}]
    with pytest.raises(FileNotFoundError):
        helpers._character_roster(tmp_path/'missing')


def test_live_fighters_are_not_historical_attack_count(helpers):
    class Boss:
        def json(self):
            return json.dumps({'order_num':4,'lap_num':32,'current_hp':900,'max_hp':1000})
    client=types.SimpleNamespace(data=types.SimpleNamespace(clan=7),request=AsyncMock(return_value=types.SimpleNamespace(fighter_num=2,attack_count=999,current_hp=800)))
    top=types.SimpleNamespace(boss_info=[Boss()],clan_battle_id=55)
    bosses,errors=asyncio.run(helpers._clan_bosses(client,top))
    assert not errors
    assert bosses[0]['attacking_count']==2
    assert bosses[0]['current_hp']==800
    assert client.request.await_args.args[0].clan_id==7
    assert client.request.await_args.args[0].order_num==4


def test_boss_detail_error_is_unknown_not_zero(helpers):
    class Boss:
        def json(self):
            return json.dumps({'order_num':1,'lap_num':1,'current_hp':900})
    client=types.SimpleNamespace(data=types.SimpleNamespace(clan=7),request=AsyncMock(side_effect=RuntimeError('temporary error')))
    result,errors=asyncio.run(helpers._clan_bosses(client,types.SimpleNamespace(boss_info=[Boss()],clan_battle_id=55)))
    assert result[0]['attacking_count'] is None
    assert errors[0]['order_num']==1
    client.request.side_effect=RuntimeError('6002 connection closed')
    with pytest.raises(RuntimeError,match='6002'):
        asyncio.run(helpers._clan_bosses(client,types.SimpleNamespace(boss_info=[Boss()],clan_battle_id=55)))


def test_live_account_alias_selection_preserved(helpers):
    assert helpers._select_account_alias('main',['BATCH_RUNNER','actual'],'actual')=='actual'
    assert helpers._select_account_alias('missing',['actual'],'actual') is None
    assert helpers._select_account_alias('main',['BATCH_RUNNER']) is None


def test_ranking_names_are_fetched_on_every_query(helpers):
    ranking=[types.SimpleNamespace(viewer_id=123,user_name=None,rank=1)]
    client=types.SimpleNamespace(get_profile=AsyncMock(return_value=types.SimpleNamespace(user_info=types.SimpleNamespace(user_name='实时游戏名'))))
    for _ in range(2):
        names=asyncio.run(helpers._ranking_name_map(client,ranking))
        assert helpers._ranking_item(ranking[0],names)['user_name']=='实时游戏名'
    assert client.get_profile.await_count==2
