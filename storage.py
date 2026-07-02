import copy
import json
import os
import tempfile
from pathlib import Path


CHANNEL_CN = "\u6e20\u9053\u670d"
BILI_CN_LOWER = "b\u670d"
BILI_CN_UPPER = "B\u670d"

DEFAULT_DATA = {
    "accounts": {},
    "arena": {},
    "groups": {},
    "clan": {},
}

DEFAULT_SECRETS = {
    "accounts": {},
}

DEFAULT_ARENA_ENTRY = {
    "uid": "",
    "nickname": "",
    "settings": "1100",
    "push_target": None,
    "last_jjc_rank": None,
    "last_pjjc_rank": None,
    "last_login_time": None,
    "rank_up_count_today": 0,
    "manual_pause": False,
    "pause_reason": "",
}


def mask_value(value, left=4, right=4):
    text = str(value)
    if len(text) <= left + right:
        return text[:max(len(text) - right, 0)] + "*" * min(right, len(text))
    return text[:left] + "*" * (len(text) - left - right + 1) + text[-right:]


def parse_bind_payload(text):
    parts = text.strip().split(maxsplit=2)
    if len(parts) < 3:
        raise ValueError("bind payload must include server type, uid, and secret")

    kind_text, uid, secret = parts
    kind_map = {
        CHANNEL_CN: "channel",
        "channel": "channel",
        BILI_CN_LOWER: "bili",
        BILI_CN_UPPER: "bili",
        "bili": "bili",
        "bilibili": "bili",
    }
    kind = kind_map.get(kind_text)
    if kind is None:
        raise ValueError(f"unsupported bind payload kind: {kind_text}")

    return {
        "kind": kind,
        "uid": uid,
        "secret": secret,
    }


class PCRStorage:
    def __init__(self, path):
        self.path = Path(path)
        self.secret_path = self._default_secret_path(self.path)
        self.secrets = self._load_secrets()
        self.data = self._load()
        if self._migrate_account_secrets():
            self.save()
            self._save_secrets()

    @staticmethod
    def _default_secret_path(path):
        return path.with_name(f"{path.stem}.secrets{path.suffix}")

    def _load(self):
        data = copy.deepcopy(DEFAULT_DATA)
        if not self.path.exists():
            return data

        with self.path.open("r", encoding="utf-8") as fp:
            loaded = json.load(fp)
        if isinstance(loaded, dict):
            self._merge_dict(data, loaded)
        self._sanitize_loaded_data(data)
        return data

    def _load_secrets(self):
        data = copy.deepcopy(DEFAULT_SECRETS)
        if not self.secret_path.exists():
            return data

        with self.secret_path.open("r", encoding="utf-8") as fp:
            loaded = json.load(fp)
        if isinstance(loaded, dict):
            self._merge_dict(data, loaded)
        if not isinstance(data.get("accounts"), dict):
            data["accounts"] = {}
        return data

    @staticmethod
    def _merge_dict(target, source):
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                PCRStorage._merge_dict(target[key], value)
            else:
                target[key] = value

    def save(self):
        self._atomic_write_json(self.path, self.data)

    def _save_secrets(self):
        if not isinstance(self.secrets.get("accounts"), dict):
            self.secrets["accounts"] = {}
        self._atomic_write_json(self.secret_path, self.secrets, secure=True)

    @staticmethod
    def _atomic_write_json(path, payload, secure=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False, indent=2)
                fp.write("\n")
            os.replace(tmp_name, path)
            if secure:
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
        except Exception:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise

    def set_account(self, user_id, account):
        account_data = dict(account)
        has_secret = "secret" in account_data
        secret = account_data.pop("secret", None)
        user_key = str(user_id)
        self.data["accounts"][user_key] = account_data
        if has_secret:
            self._set_account_secret(user_key, secret)
            self._save_secrets()
        self.save()

    def get_account(self, user_id):
        return self.data["accounts"].get(str(user_id))

    def get_account_secret(self, user_id):
        secrets = self.secrets.get("accounts", {})
        if not isinstance(secrets, dict):
            return None
        return secrets.get(str(user_id))

    def remove_account(self, user_id):
        user_key = str(user_id)
        removed = self.data["accounts"].pop(user_key, None)
        if isinstance(self.secrets.get("accounts"), dict):
            self.secrets["accounts"].pop(user_key, None)
            self._save_secrets()
        self.save()
        return removed

    def bind_arena_uid(self, user_id, uid, nickname=""):
        user_key = str(user_id)
        uid_value = str(uid)
        bindings = self._arena_bindings(user_key)
        bindings = [item for item in bindings if str(item.get("uid")) != uid_value]
        bindings.insert(0, self._arena_entry(uid_value, nickname))
        self.data["arena"][user_key] = bindings[:8]
        self.save()

    def set_group(self, group_id, settings):
        if not isinstance(self.data.get("groups"), dict):
            self.data["groups"] = {}
        group_key = str(group_id)
        current = self.data["groups"].get(group_key, {})
        merged = dict(current) if isinstance(current, dict) else {}
        merged.update(settings)
        self.data["groups"][group_key] = merged
        self.save()

    @staticmethod
    def _arena_entry(uid, nickname=""):
        entry = dict(DEFAULT_ARENA_ENTRY)
        entry["uid"] = str(uid)
        entry["nickname"] = nickname
        return entry

    @classmethod
    def _normalize_arena_entry(cls, entry):
        if not isinstance(entry, dict):
            return None
        normalized = dict(DEFAULT_ARENA_ENTRY)
        normalized.update(entry)
        normalized["uid"] = str(normalized.get("uid", ""))
        normalized["nickname"] = normalized.get("nickname") or ""
        settings = str(normalized.get("settings", "1100")).strip()
        if len(settings) != 4 or not settings.isdigit():
            settings = "1100"
        elif any(char not in "01" for char in settings[:3]) or settings[3] not in "0123":
            settings = "1100"
        normalized["settings"] = settings
        if normalized.get("rank_up_count_today") is None:
            normalized["rank_up_count_today"] = 0
        return normalized

    @classmethod
    def _normalize_arena_bindings(cls, value):
        if isinstance(value, dict):
            entry = cls._normalize_arena_entry(value)
            return [entry] if entry is not None else []
        if isinstance(value, list):
            bindings = []
            for item in value:
                entry = cls._normalize_arena_entry(item)
                if entry is not None:
                    bindings.append(entry)
            return bindings[:8]
        return []

    @classmethod
    def _sanitize_loaded_data(cls, data):
        for key in ("accounts", "groups", "arena", "clan"):
            if not isinstance(data.get(key), dict):
                data[key] = {}

        normalized_arena = {}
        for user_key, value in data["arena"].items():
            normalized_arena[str(user_key)] = cls._normalize_arena_bindings(value)
        data["arena"] = normalized_arena

    def _set_account_secret(self, user_key, secret):
        if not isinstance(self.secrets.get("accounts"), dict):
            self.secrets["accounts"] = {}
        if secret is None:
            self.secrets["accounts"].pop(user_key, None)
        else:
            self.secrets["accounts"][user_key] = secret

    def _migrate_account_secrets(self):
        migrated = False
        accounts = self.data.get("accounts", {})
        if not isinstance(accounts, dict):
            return False

        for user_key, account in list(accounts.items()):
            if not isinstance(account, dict) or "secret" not in account:
                continue
            secret = account.pop("secret")
            self._set_account_secret(str(user_key), secret)
            migrated = True
        return migrated

    def _arena_bindings(self, user_key):
        if not isinstance(self.data.get("arena"), dict):
            self.data["arena"] = {}
        bindings = self._normalize_arena_bindings(self.data["arena"].get(user_key, []))
        self.data["arena"][user_key] = bindings
        return bindings

    def group_enabled(self, origin):
        if not isinstance(self.data.get("groups"), dict):
            self.data["groups"] = {}
        group_key = str(origin)
        settings = self.data["groups"].get(group_key, {})
        if not isinstance(settings, dict):
            return False
        return bool(settings.get("enabled", False))

    def set_group_enabled(self, origin, enabled):
        if not isinstance(self.data.get("groups"), dict):
            self.data["groups"] = {}
        group_key = str(origin)
        current = self.data["groups"].get(group_key, {})
        merged = dict(current) if isinstance(current, dict) else {}
        merged["enabled"] = bool(enabled)
        self.data["groups"][group_key] = merged
        self.save()

    def set_clan_state(self, origin, values):
        if not isinstance(self.data.get("clan"), dict):
            self.data["clan"] = {}
        clan_key = str(origin)
        current = self.data["clan"].get(clan_key, {})
        merged = dict(current) if isinstance(current, dict) else {}
        merged.update(values)
        self.data["clan"][clan_key] = merged
        self.save()
