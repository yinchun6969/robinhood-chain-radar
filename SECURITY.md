# Security / 安全说明

## 中文

本项目是只读链上监控工具，不需要私钥、助记词或 Robinhood 登录凭据，也不执行交易。`.env` 可能包含 Telegram Bot Token，禁止提交。Dashboard 默认仅绑定 `127.0.0.1`。Token 风险扫描是源码/ABI/Proxy/Owner/权限函数的启发式检查，不等同于完整审计。

## English

This project is read-only. It does not require wallet private keys, seed phrases or Robinhood login credentials and does not submit transactions. Never commit `.env` because it may contain a Telegram Bot Token. The Dashboard binds to `127.0.0.1` by default. Token-risk output is heuristic (source/ABI/proxy/owner/admin interfaces), not a full security audit.
