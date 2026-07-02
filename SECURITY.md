# Security

## 不要提交这些内容

- `data/`
- `state.json`
- `state.secrets.json`
- AutoPCR 账号、密码、`access_key`、渠道服 `<string ...>`
- pcrdfans API Key
- 服务器 SSH Key、Cookie、token

## 部署建议

- `pcr-real-api` 只监听 `127.0.0.1:18081`。
- 只开放 AutoPCR Web 需要的公网端口。
- 管理员配置只写真实 QQ 号。
- 不要把 `monitor_interval_seconds` 设置得过低。
- 如果本人正在游戏内，建议关闭竞技场/会战监控，避免顶号。

## 报告问题

如果发现会导致账号泄露、越权使用、误用他人账号的问题，请优先私下联系仓库维护者，不要在公开 issue 中贴账号数据或 token。
