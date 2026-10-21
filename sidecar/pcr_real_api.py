import argparse
import asyncio
import json
import os
import sqlite3
from pathlib import Path
from contextlib import asynccontextmanager

from aiohttp import web

from autopcr.core.pcrclient import eLoginStatus
from autopcr.constants import BSDK, CACHE_DIR
from autopcr.model.requests import (
    ClanBattleBossInfoRequest,
    ClanBattleHistoryReportRequest,
    ClanBattleMyLogRequest,
)
from autopcr.module.accountmgr import AccountException, UserException, instance as usermgr


DEFAULT_USER = os.getenv("PCR_REAL_API_DEFAULT_USER", "")
BATCH_ACCOUNT = "BATCH_RUNNER"


def _select_account_alias(requested, accounts, default_alias=""):
    available = [item for item in accounts if item and item != BATCH_ACCOUNT]
    if requested in available:
        return requested
    if requested and requested != "main":
        return None
    return default_alias if default_alias in available else next(iter(available), None)


class PCRRealService:
    def __init__(self):
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def client(self, user: str | None = None, account: str | None = None):
        async with self._lock:
            async with usermgr.load(user or DEFAULT_USER, readonly=True) as mgr:
                accounts = [item for item in mgr.accounts() if item != BATCH_ACCOUNT]
                if not accounts:
                    raise web.HTTPNotFound(text="no autopcr account")
                default_alias = getattr(mgr, "default_account", "")
                if callable(default_alias):
                    default_alias = default_alias()
                alias = _select_account_alias(account, accounts, default_alias)
                if not alias:
                    raise web.HTTPNotFound(text="autopcr account not found")
                async with mgr.load(alias, readonly=True) as acc:
                    client = await acc.get_client()
                    await client.__aenter__()
                    try:
                        await self._ensure_login(client)
                        yield client, acc, alias
                    finally:
                        try:
                            client.deactivate()
                        finally:
                            await client.__aexit__(None, None, None)

    async def _ensure_login(self, client):
        await client.activate()
        if client.logged == eLoginStatus.NOT_LOGGED or not client.data.ready:
            await client.login()
        elif client.logged == eLoginStatus.NEED_REFRESH:
            await client.refresh()


service = PCRRealService()


async def health(request):
    return web.json_response({"ok": True, "service": "pcr_real_api"})


def _character_roster(db_dir=None):
    directory = Path(db_dir) if db_dir is not None else Path(CACHE_DIR) / 'db'
    candidates = sorted((p for p in directory.glob('*.db') if p.stem.isdigit()), reverse=True)
    if not candidates:
        raise FileNotFoundError('game database not downloaded')
    with sqlite3.connect(f'file:{candidates[0].as_posix()}?mode=ro', uri=True) as connection:
        rows = connection.execute(
            'select unit_id,unit_name from unit_data '
            'where unit_id between 100000 and 199999 and unit_id % 100 = 1 order by unit_id'
        ).fetchall()
    return {'ok': True, 'database_version': candidates[0].stem,
            'characters': [{'id': int(unit_id) // 100, 'name': str(name)} for unit_id, name in rows if name]}


async def characters(request):
    try:
        return web.json_response(await asyncio.to_thread(_character_roster))
    except (FileNotFoundError, sqlite3.Error) as exc:
        raise web.HTTPServiceUnavailable(text='game character database unavailable') from exc


async def profile(request):
    uid = request.query.get("uid")
    if not uid:
        raise web.HTTPBadRequest(text="uid is required")
    async with service.client(request.query.get("user"), request.query.get("account")) as (client, acc, alias):
        resp = await client.get_profile(int(uid))
        info = resp.user_info
        return web.json_response({
            "ok": True,
            "account": _account_payload(client, acc, alias),
            "profile": {
                "uid": int(uid),
                "user_name": getattr(info, "user_name", None),
                "team_level": getattr(info, "team_level", None),
                "arena_rank": getattr(info, "arena_rank", None),
                "grand_arena_rank": getattr(info, "grand_arena_rank", None),
                "last_login_time": getattr(info, "last_login_time", None),
                "clan_name": getattr(resp, "clan_name", None),
            },
        })


async def arena_history(request):
    kind = request.query.get("kind", "jjc").lower()
    async with service.client(request.query.get("user"), request.query.get("account")) as (client, acc, alias):
        if kind in {"pjjc", "grand"}:
            resp = await client.get_grand_arena_history()
            items = getattr(resp, "grand_arena_history_list", None) or []
            normalized_kind = "pjjc"
        else:
            resp = await client.get_arena_history()
            items = getattr(resp, "versus_result_list", None) or []
            normalized_kind = "jjc"
        return web.json_response({
            "ok": True,
            "account": _account_payload(client, acc, alias),
            "kind": normalized_kind,
            "items": [_model_json(item) for item in items[:20]],
        })


async def arena_ranking(request):
    kind = request.query.get("kind", "jjc").lower()
    page = _query_int(request, "page", 1, minimum=1)
    limit = _query_int(request, "limit", 20, minimum=1, maximum=50)
    async with service.client(request.query.get("user"), request.query.get("account")) as (client, acc, alias):
        if kind in {"pjjc", "grand"}:
            info_resp = await client.get_grand_arena_info()
            ranking_resp = await client.grand_arena_rank(limit, page)
            info = getattr(info_resp, "grand_arena_info", None)
            ranking = getattr(ranking_resp, "ranking", None) or []
            normalized_kind = "pjjc"
        else:
            info_resp = await client.get_arena_info()
            ranking_resp = await client.arena_rank(limit, page)
            info = getattr(info_resp, "arena_info", None)
            ranking = getattr(ranking_resp, "ranking", None) or []
            normalized_kind = "jjc"
        name_by_uid = await _ranking_name_map(client, ranking)
        return web.json_response({
            "ok": True,
            "account": _account_payload(client, acc, alias),
            "kind": normalized_kind,
            "page": page,
            "limit": limit,
            "arena": {
                "rank": getattr(info, "rank", None),
                "group": getattr(info, "group", None),
                "highest_rank": getattr(info, "highest_rank", None),
                "season_highest_rank": getattr(info, "season_highest_rank", None),
            },
            "ranking": [_ranking_item(item, name_by_uid) for item in ranking],
        })


async def clan_status(request):
    async with service.client(request.query.get("user"), request.query.get("account")) as (client, acc, alias):
        top = await client.clan_battle_top()
        clan_info = await _safe_clan_info(client)
        user_clan = getattr(top, "user_clan", None)
        bosses, detail_errors = await _clan_bosses(client, top)
        return web.json_response({
            "ok": True,
            "account": _account_payload(client, acc, alias),
            "clan": {
                "clan_id": getattr(client.data, "clan", None),
                "clan_name": getattr(user_clan, "clan_name", None),
                "clan_role": getattr(user_clan, "clan_role", None),
            },
            "clan_battle": {
                "id": getattr(top, "clan_battle_id", None),
                "period": getattr(top, "period", None),
                "lap_num": getattr(top, "lap_num", None),
                "own_rank": getattr(top, "own_rank", None),
                "period_rank": getattr(top, "period_rank", None),
            },
            "boss_info": bosses,
            "damage_history": [_damage_history(item) for item in (getattr(top, "damage_history", None) or [])],
            "members": _extract_members(clan_info),
            "history_complete": False,
            "history_scope": "游戏最近记录；持续监控后累积",
            "boss_detail_errors": detail_errors,
        })


async def _clan_bosses(client, top):
    bosses = []
    errors = []
    for raw in (getattr(top, "boss_info", None) or [])[:5]:
        item = _model_json(raw)
        if not isinstance(item, dict):
            continue
        item["attacking_count"] = None
        if item.get("order_num") and item.get("lap_num") and item.get("current_hp", 0):
            req = ClanBattleBossInfoRequest()
            req.clan_id = client.data.clan
            req.clan_battle_id = getattr(top, "clan_battle_id", None)
            req.lap_num = item["lap_num"]
            req.order_num = item["order_num"]
            try:
                detail = await client.request(req)
                # attack_count is historical; fighter_num is the live player count.
                item["attacking_count"] = getattr(detail, "fighter_num", None)
                if getattr(detail, "current_hp", None) is not None:
                    item["current_hp"] = detail.current_hp
            except Exception as exc:
                errors.append({"order_num": item["order_num"], "type": type(exc).__name__})
                # A session error must stop the polling pass, not relogin for each boss.
                if "6002" in str(exc) or "登录" in str(exc) or "session" in str(exc).lower():
                    raise
        bosses.append(item)
    return bosses, errors


async def clan_history_detail(request):
    history_id = _query_int(request, "history_id", 0, minimum=0)
    if not history_id:
        raise web.HTTPBadRequest(text="history_id is required")
    async with service.client(request.query.get("user"), request.query.get("account")) as (client, acc, alias):
        req = ClanBattleHistoryReportRequest()
        req.clan_id = client.data.clan
        req.history_id = history_id
        response = await client.request(req)
        return web.json_response({
            "ok": True,
            "account": _account_payload(client, acc, alias),
            "history_id": history_id,
            "units": [_model_json(item) for item in (getattr(response, "history_report", None) or [])],
        })


async def clan_mylog(request):
    async with service.client(request.query.get("user"), request.query.get("account")) as (client, acc, alias):
        req = ClanBattleMyLogRequest()
        req.clan_id = client.data.clan
        resp = await client.request(req)
        return web.json_response({
            "ok": True,
            "account": _account_payload(client, acc, alias),
            "actual_logs": [_mylog(item) for item in (getattr(resp, "actual_logs", None) or [])],
            "rehearsal_logs": [_mylog(item) for item in (getattr(resp, "rehearsal_logs", None) or [])],
            "training_logs": [_mylog(item) for item in (getattr(resp, "training_logs", None) or [])],
        })


async def account_upsert(request):
    payload = await request.json()
    user = str(payload.get("user") or "").strip()
    alias = str(payload.get("account") or "main").strip()
    uid = str(payload.get("uid") or "").strip()
    secret = str(payload.get("secret") or "")
    kind = str(payload.get("kind") or "").strip()
    if not user.isdigit():
        raise web.HTTPBadRequest(text="user is required")
    if not uid or not secret:
        raise web.HTTPBadRequest(text="uid and secret are required")
    if not alias:
        alias = "main"

    try:
        if user in set(usermgr.qids()):
            mgr = usermgr.load(user, readonly=False)
        else:
            mgr = usermgr.create(user, "")
        async with mgr:
            if alias not in set(mgr.accounts()):
                mgr.create_account(alias)
            mgr.set_default_account(alias)
            async with mgr.load(alias, readonly=False) as acc:
                acc.data.username = uid
                acc.data.password = secret
                acc.data.channel = _channel_for_kind(kind)
        return web.json_response({
            "ok": True,
            "user": user,
            "account": alias,
            "uid": uid,
            "channel": _channel_for_kind(kind),
        })
    except (AccountException, UserException) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc


@web.middleware
async def error_middleware(request, handler):
    try:
        return await handler(request)
    except web.HTTPException as exc:
        return web.json_response(
            {"ok": False, "type": type(exc).__name__, "message": exc.text},
            status=exc.status,
        )
    except Exception as exc:
        return web.json_response(
            {"ok": False, "type": type(exc).__name__, "message": str(exc)},
            status=500,
        )


def _account_payload(client, acc, alias):
    return {
        "alias": alias,
        "uid": getattr(client.data, "uid", None),
        "user_name": getattr(client.data, "user_name", None),
        "channel": getattr(acc.data, "channel", None),
        "platform": "channel" if getattr(acc.data, "channel", "") == "\u6e20\u9053\u670d" else "bili",
    }


def _damage_history(item):
    record = _model_json(item)
    record = dict(record) if isinstance(record, dict) else {}
    record.update({
        "history_id": getattr(item, "history_id", None),
        "viewer_id": getattr(item, "viewer_id", None),
        "name": getattr(item, "name", None),
        "enemy_id": getattr(item, "enemy_id", None),
        "lap_num": getattr(item, "lap_num", None),
        "order_num": getattr(item, "order_num", None),
        "damage": getattr(item, "damage", None),
        "score": getattr(item, "score", None),
        "damage_score": getattr(item, "damage_score", None),
        "battle_score": getattr(item, "battle_score", None),
        "score_damage": getattr(item, "score_damage", None),
        "kill": getattr(item, "kill", None),
        "create_time": getattr(item, "create_time", None),
    })
    return record


def _mylog(item):
    enemy = getattr(item, "enemy", None)
    return {
        "mylog_id": getattr(item, "mylog_id", None),
        "battle_log_id": getattr(item, "battle_log_id", None),
        "battle_time": getattr(item, "battle_time", None),
        "lap_num": getattr(item, "lap_num", None),
        "phase_num": getattr(item, "phase_num", None),
        "order_num": getattr(item, "order_num", None),
        "total_damage": getattr(item, "total_damage", None),
        "is_auto": getattr(item, "is_auto", None),
        "clan_battle_mode": getattr(item, "clan_battle_mode", None),
        "enemy": _model_json(enemy) if enemy else None,
        "units": [_model_json(unit) for unit in (getattr(item, "units", None) or [])],
    }


async def _ranking_name_map(client, ranking):
    names = {}
    for item in ranking:
        viewer_id = getattr(item, "viewer_id", None)
        if not viewer_id or str(getattr(item, "user_name", None) or "").strip():
            continue
        try:
            response = await client.get_profile(int(viewer_id))
            name = str(getattr(getattr(response, "user_info", None), "user_name", None) or "").strip()
            if name:
                names[str(viewer_id)] = name
        except Exception:
            continue
    return names


def _ranking_item(item, name_by_uid=None):
    return {
        "viewer_id": getattr(item, "viewer_id", None),
        "rank": getattr(item, "rank", None),
        "user_name": getattr(item, "user_name", None) or (name_by_uid or {}).get(str(getattr(item, "viewer_id", ""))),
        "team_level": getattr(item, "team_level", None),
        "winning_number": getattr(item, "winning_number", None),
    }


def _model_json(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_model_json(item) for item in value]
    if hasattr(value, "json"):
        return json.loads(value.json())
    if hasattr(value, "dict"):
        return _model_json(value.dict())
    if isinstance(value, dict):
        return {key: _model_json(item) for key, item in value.items()}
    return str(value)


async def _safe_clan_info(client):
    try:
        return await client.get_clan_info()
    except Exception:
        return None


def _extract_members(clan_info):
    if clan_info is None:
        return []
    for attr in ("members", "member_list", "clan_member_list"):
        value = getattr(clan_info, attr, None)
        if value:
            return [_model_json(item) for item in value]
    data = _model_json(clan_info)
    if isinstance(data, dict):
        for key in ("members", "member_list", "clan_member_list"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        clan = data.get("clan")
        if isinstance(clan, dict):
            return _extract_members(clan)
    return []


def _channel_for_kind(kind):
    if kind == "channel":
        return "\u6e20\u9053\u670d"
    return BSDK


def _query_int(request, name, default, minimum=None, maximum=None):
    try:
        value = int(request.query.get(name, default))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def create_app():
    app = web.Application(middlewares=[error_middleware])
    app.router.add_get("/health", health)
    app.router.add_get("/characters", characters)
    app.router.add_get("/profile", profile)
    app.router.add_get("/arena/history", arena_history)
    app.router.add_get("/arena/ranking", arena_ranking)
    app.router.add_get("/clan/status", clan_status)
    app.router.add_get("/clan/mylog", clan_mylog)
    app.router.add_get("/clan/history-detail", clan_history_detail)
    app.router.add_post("/account/upsert", account_upsert)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()
    web.run_app(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
