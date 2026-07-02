from dataclasses import dataclass
from datetime import datetime


@dataclass
class ClanMonitorStatus:
    enabled: bool
    account_uid: str | None
    last_poll: str | None
    message: str


def build_status(
    enabled: bool,
    account_uid: str | None,
    last_poll: str | None = None,
) -> ClanMonitorStatus:
    if not enabled:
        return ClanMonitorStatus(
            enabled=False,
            account_uid=account_uid,
            last_poll=last_poll,
            message="\u4f1a\u6218\u76d1\u63a7\u672a\u5f00\u542f",
        )

    return ClanMonitorStatus(
        enabled=True,
        account_uid=account_uid,
        last_poll=last_poll or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        message=(
            "\u4f1a\u6218\u76d1\u63a7\u5df2\u5f00\u542f\uff1b"
            "\u81ea\u52a8\u62a5\u5200\u8bfb\u53d6\u540e\u7aef"
            "\u6b63\u5728\u63a5\u5165\uff0c\u5f53\u524d\u4e0d\u4f1a"
            "\u6267\u884c\u6e38\u620f\u5185\u64cd\u4f5c\u3002"
        ),
    )
