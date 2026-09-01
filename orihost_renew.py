#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Orihost 自动登录与续期脚本 (Playwright + 代理版)
# ============================================================
import os
import sys
import time
import requests
from urllib.parse import unquote
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

BASE_URL = "https://panel.orihost.com"
LOGIN_URL = f"{BASE_URL}/auth/login"

# 代理与 Telegram 配置
ORIHOST_PROXY = os.environ.get("ORIHOST_PROXY", "").strip()
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()

# 整理代理配置
REQUESTS_PROXIES = {}
if ORIHOST_PROXY:
    REQUESTS_PROXIES = {"http": ORIHOST_PROXY, "https": ORIHOST_PROXY}
    print(f"🔗 已启用代理: {ORIHOST_PROXY}")

# 账号列表解析 (支持单账号与多账号)
ACCOUNTS = []
for i in range(1, 20):
    u = os.environ.get(f"ORIHOST_USERNAME_{i}")
    p = os.environ.get(f"ORIHOST_PASSWORD_{i}")
    s_ids = os.environ.get(f"ORIHOST_SERVER_IDS_{i}")
    if u and p and s_ids:
        server_ids = [s.strip() for s in s_ids.split(",") if s.strip()]
        ACCOUNTS.append({
            "label": f"账号{i}",
            "username": u.strip(),
            "password": p.strip(),
            "server_ids": server_ids
        })

# 向下兼容单账号
if not ACCOUNTS:
    legacy_u = os.environ.get("ORIHOST_USERNAME", "").strip()
    legacy_p = os.environ.get("ORIHOST_PASSWORD", "").strip()
    legacy_s = os.environ.get("ORIHOST_SERVER_IDS", "").strip()
    if legacy_u and legacy_p and legacy_s:
        server_ids = [s.strip() for s in legacy_s.split(",") if s.strip()]
        ACCOUNTS.append({
            "label": "默认账号",
            "username": legacy_u,
            "password": legacy_p,
            "server_ids": server_ids
        })

if not ACCOUNTS:
    print("❌ 未检测到任何账号配置，请在 Secrets 中配置 ORIHOST_USERNAME 与 ORIHOST_PASSWORD")
    sys.exit(1)


def send_telegram(message: str):
    """发送 Telegram 通知"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ Telegram 未配置，跳过推送")
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message}, proxies=REQUESTS_PROXIES or None, timeout=15)
        print("  ✅ Telegram 消息推送成功")
    except Exception as e:
        print(f"  ❌ Telegram 发送失败: {e}")


def get_authenticated_session(username, password):
    """通过 Playwright 登录并提取 Session 与 XSRF-TOKEN"""
    print(f"🚀 启动无头浏览器登录账号: {username} ...")
    
    playwright_proxy = None
    if ORIHOST_PROXY:
        playwright_proxy = {"server": ORIHOST_PROXY}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy=playwright_proxy,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()

        try:
            page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)
            print("  🌐 页面已加载，正在输入凭证...")

            # 填充用户名/邮箱
            if page.locator("input[name='user']").count() > 0:
                page.fill("input[name='user']", username)
            elif page.locator("input[type='text'], input[type='email']").count() > 0:
                page.fill("input[type='text'], input[type='email']", username)

            # 填充密码
            page.fill("input[type='password']", password)

            # 勾选记住我（如果有）
            if page.locator("input[type='checkbox']").count() > 0:
                page.locator("input[type='checkbox']").check()

            # 点击登录
            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle", timeout=60000)
            time.sleep(3)

            cookies_list = context.cookies()
            cookies_dict = {c["name"]: c["value"] for c in cookies_list}

            xsrf_token = cookies_dict.get("XSRF-TOKEN", "")
            if xsrf_token:
                xsrf_token = unquote(xsrf_token)

            if "jexactyl_session" not in cookies_dict and "pterodactyl_session" not in cookies_dict:
                print("❌ 登录失败：未检测到有效 Session Cookie，请确认账号密码是否正确。")
                browser.close()
                return None, None

            print("✅ 登录成功，会话抓取完毕！")
            browser.close()
            return cookies_dict, xsrf_token

        except Exception as e:
            print(f"❌ 浏览器登录流程出现异常: {e}")
            browser.close()
            return None, None


def renew_server(cookies: dict, xsrf_token: str, server_id: str) -> dict:
    """调用 API 完成服务器续期"""
    headers = {
        "accept": "application/json",
        "accept-language": "zh-CN,zh;q=0.9",
        "x-requested-with": "XMLHttpRequest",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": f"{BASE_URL}/server/{server_id[:8]}",
    }
    if xsrf_token:
        headers["x-xsrf-token"] = xsrf_token

    # 1. 发起续期
    begin_url = f"{BASE_URL}/api/client/servers/{server_id}/renew/begin"
    print(f"\n🔄 [{server_id[:8]}] 开始续期流程...")
    try:
        resp = requests.post(begin_url, headers=headers, cookies=cookies, proxies=REQUESTS_PROXIES or None, timeout=30)
    except Exception as e:
        return {"status": "error", "message": f"连接超时: {e}"}

    if resp.status_code != 200:
        return {"status": "error", "message": f"begin 失败 HTTP {resp.status_code}: {resp.text[:100]}"}

    try:
        data = resp.json()
    except Exception:
        return {"status": "error", "message": "响应解析失败"}

    dwell_seconds = data.get("dwell_seconds", 15)
    print(f"  ⏳ 正在模拟阅读文章，等待 {dwell_seconds + 1} 秒...")
    time.sleep(dwell_seconds + 1)

    # 2. 完成续期
    complete_url = f"{BASE_URL}/api/client/renewal/complete"
    try:
        resp2 = requests.get(complete_url, headers=headers, cookies=cookies, proxies=REQUESTS_PROXIES or None, timeout=30)
    except Exception as e:
        return {"status": "error", "message": f"complete 异常: {e}"}

    if resp2.status_code != 200:
        return {"status": "error", "message": f"complete 失败 HTTP {resp2.status_code}"}

    try:
        result = resp2.json()
    except Exception:
        result = {}

    renewed = result.get("renewed_count", 0)
    skipped = result.get("skipped_count", 0)

    if renewed > 0:
        return {"status": "success", "message": f"续期成功 (+{renewed})"}
    elif skipped > 0:
        return {"status": "skipped", "message": "已达续期上限 (Limit Reached)"}
    else:
        return {"status": "unknown", "message": f"未知响应: {result}"}


def main():
    print("=" * 45)
    print(" Orihost 自动登录与续期任务")
    print("=" * 45)

    all_results = []
    status_map = {
        "success": "✅ 续期成功",
        "skipped": "⏭️ 已达上限",
        "error": "❌ 续期失败",
        "unknown": "⚠️ 状态异常",
    }

    for acc in ACCOUNTS:
        print(f"\n--- 正在处理 {acc['label']} ---")
        cookies, xsrf_token = get_authenticated_session(acc["username"], acc["password"])
        if not cookies:
            all_results.append(f"• {acc['label']}: ❌ 登录失败")
            continue

        for sid in acc["server_ids"]:
            res = renew_server(cookies, xsrf_token, sid)
            st_text = status_map.get(res["status"], "❌ 续期失败")
            print(f"  📌 结果: {st_text} ({res.get('message')})")
            all_results.append(f"• 服务器 `{sid[:8]}`: {st_text}\n  └ 详情: {res.get('message')}")

    now = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    summary = f"🖥 *Orihost 服务器自动续期汇总*\n\n" + "\n\n".join(all_results) + f"\n\n⏰ 执行时间: `{now}`"
    send_telegram(summary)


if __name__ == "__main__":
    main()
