import pcr_chara as chara


def test_game_database_playable_ids_override_story_npc_aliases(monkeypatch):
    monkeypatch.setattr(chara,'CHARA_NAME',{
        1900:['爱梅斯','ems'],1909:['涅比亚','涅宝'],
        1055:['步未'],1089:['怜(新年)'],1007:['宫子'],
    })
    monkeypatch.setattr(chara,'_ROSTER',chara.CharaRoster())
    chara.extend_character_roster([{'id':1230,'name':'爱梅斯'},{'id':1186,'name':'涅比亚'}])
    assert chara.parse_team_names('爱梅斯 涅比亚 步未 怜(新年) 宫子') == ([1230,1186,1055,1089,1007],'')
    assert chara.parse_team_names('ems 涅宝') == ([1230,1186],'')


def test_duplicate_story_names_keep_base_playable_character(monkeypatch):
    monkeypatch.setattr(chara,'CHARA_NAME',{1195:['可可萝'],1059:['可可萝','妈']})
    monkeypatch.setattr(chara,'_ROSTER',chara.CharaRoster())
    chara.extend_character_roster([{'id':1195,'name':'可可萝'},{'id':1059,'name':'可可萝'}])
    assert chara.parse_team_names('可可萝 妈') == ([1059,1059],'')


def test_roster_cache_reload_preserves_playable_id_priority(tmp_path,monkeypatch):
    monkeypatch.setattr(chara,'CHARA_NAME',{1900:['爱梅斯','ems']})
    monkeypatch.setattr(chara,'_ROSTER',chara.CharaRoster())
    cache=tmp_path/'characters.json'
    chara.extend_character_roster([{'id':1230,'name':'爱梅斯'}],cache)
    chara._ROSTER=chara.CharaRoster({1900:['爱梅斯','ems']})
    assert chara.parse_team_names('爱梅斯')[0] == [1900]
    chara.load_character_roster(cache)
    assert chara.parse_team_names('爱梅斯 ems') == ([1230,1230],'')
