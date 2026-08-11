# ============================================================
# Orihost 免费服务器自动续期
# ============================================================
# Orihost 免费托管（orihost.com）服务器的自动续期脚本
# 基于 Jexactyl 面板 API 实现，支持多账号多服务器
# 仓库: https://github.com/jacksun-king/orihost-renew

## 功能
- ✅ 自动续期 Orihost 免费服务器
- ✅ 模拟"阅读文章 + 等待"流程（Jexactyl 续期机制）
- ✅ 支持多账号多服务器
- ✅ 续期结果通过 Telegram 通知
- ✅ 可选代理（解决 Cloudflare / 数据中心 IP 拦截）

## 续期原理
Orihost 面板（Jexactyl）的续期需要两步：
1. `POST /api/client/servers/{server}/renew/begin` — 启动续期会话，返回文章链接和等待秒数
2. 等待指定秒数（模拟阅读文章，默认 15 秒）
3. `GET /api/client/renewal/complete` — 完成续期

## 使用方法

### 1. 获取 Cookie
1. 登录 https://panel.orihost.com
2. 打开 DevTools (F12) → Network (网络)
3. 刷新页面，任意点击一个 API 请求（如 `activity`）
4. 复制完整 curl 命令
5. 从中提取 Cookie 字符串（`-b '...'` 里的内容）

### 2. 配置 GitHub Secrets / Variables
在 GitHub 仓库 **Settings → Secrets and variables → Actions** 中配置：

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `ORIHOST_COOKIE` | Secret | Cookie 字符串（整段 `-b` 内容） |
| `ORIHOST_SERVER_IDS` | Variables | 服务器 UUID 列表，逗号分隔（如 `738a4f39-7cdf-4cf5-ac97-f8d866f0cadc`） |
| `TG_BOT_TOKEN` | Secret | Telegram Bot Token（可选） |
| `TG_CHAT_ID` | Secret | Telegram Chat ID（可选） |
| `NODE_LINK` | Secret | 代理节点链接（可选，解决 IP 被拦） |

### 3. 多账号配置
账号通过 `_1`、`_2`、`_3` 后缀区分：

| 配置项 | 说明 |
|--------|------|
| `ORIHOST_COOKIE_1` + `ORIHOST_SERVER_IDS_1` | 账号 1 |
| `ORIHOST_COOKIE_2` + `ORIHOST_SERVER_IDS_2` | 账号 2 |
| `ORIHOST_COOKIE_3` + `ORIHOST_SERVER_IDS_3` | 账号 3 |

### 4. 定时设置
工作流默认每 3 天执行一次（`0 10 */3 * *`，北京时间 18:00）。
如需修改，编辑 `.github/workflows/renew.yml` 中的 cron 表达式。

## 本地测试
```bash
export ORIHOST_COOKIE="你的cookie"
export ORIHOST_SERVER_IDS="738a4f39-7cdf-4cf5-ac97-f8d866f0cadc"
pip install requests
python3 orihost_renew.py
```

## 常见问题
- **CSRF token mismatch (419)**：Cookie 已过期，需重新登录获取
- **401 Unauthenticated**：Cookie 失效，需重新登录
- **服务器被跳过 (skipped)**：该周期内已达续期上限，下次到期前再试
- **被 Cloudflare 拦截**：配置 `NODE_LINK` 或 `ORIHOST_PROXY` 使用代理