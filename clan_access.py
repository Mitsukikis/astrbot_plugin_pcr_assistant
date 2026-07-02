def clan_command_account_qq(sender_id, clan_state=None):
    return str(sender_id or "").strip()


def make_monitor_id(group_key, sender_id):
    seed = f"{group_key}:{sender_id}"
    value = sum((index + 1) * ord(char) for index, char in enumerate(seed)) % 100000
    return f"HN{value:05d}"


def clan_command_needs_account(command_key):
    return command_key in {
        "out_damage_monitor_on",
        "status",
        "current_report",
        "today_report",
        "today_damage",
        "damage_detail",
        "my_report",
        "yesterday_report",
        "yesterday_damage",
    }
