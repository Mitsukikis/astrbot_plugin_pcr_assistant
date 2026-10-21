from contextlib import aclosing
from functools import wraps


def require_pcr_access(*, allow_private=False, manage_group=False):
    def decorate(handler):
        @wraps(handler)
        async def guarded(self, event, *args, **kwargs):
            if not self._pcr_event_allowed(
                event, allow_private=allow_private, manage_group=manage_group
            ):
                return
            async with aclosing(handler(self, event, *args, **kwargs)) as results:
                while self._pcr_event_allowed(
                    event, allow_private=allow_private, manage_group=manage_group
                ):
                    try:
                        result = await anext(results)
                    except StopAsyncIteration:
                        return
                    if not self._pcr_event_allowed(
                        event, allow_private=allow_private, manage_group=manage_group
                    ):
                        return
                    yield result

        return guarded

    return decorate


def is_allowed_qq(sender_id, owner_qq, allowed_qqs=(), blocked_qqs=()) -> bool:
    sender = str(sender_id or "").strip()
    if not sender.isascii() or not sender.isdigit():
        return False
    if sender in parse_qq_list(blocked_qqs):
        return False
    return sender in (parse_qq_list(owner_qq) | parse_qq_list(allowed_qqs))


def parse_qq_list(value) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        result = set()
        for item in value:
            result.update(parse_qq_list(item))
        return result
    text = str(value or "")
    for separator in (",", ";", "\uff0c", "\uff1b", "\n", "\t"):
        text = text.replace(separator, " ")
    return {part for part in text.split() if part.isascii() and part.isdigit()}


def numeric_sender_id_from_event(event) -> str:
    message_obj = getattr(event, "message_obj", None)
    sender = getattr(message_obj, "sender", None)
    candidates = (
        getattr(sender, "user_id", None),
        getattr(sender, "id", None),
        getattr(sender, "qq", None),
        getattr(message_obj, "user_id", None),
        getattr(event, "sender_id", None),
        _call_sender_getter(event),
    )
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text.isdigit():
            return text
    return ""


def is_admin_qq(sender_id: str, admin_qqs, blocked_qqs=()) -> bool:
    sender = str(sender_id or "").strip()
    if not sender or sender in set(blocked_qqs or ()):
        return False
    return sender in set(admin_qqs or ())


def _call_sender_getter(event):
    getter = getattr(event, "get_sender_id", None)
    if callable(getter):
        return getter()
    return None
