#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Orihost 自动登录与续期脚本 (Playwright 版)
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

USERNAME = os.environ.get("ORIHOST_USERNAME", "").strip()
PASSWORD = os.environ.get("ORIHOST_PASSWORD", "").strip()
SERVER_IDS_RAW = os.environ.get("ORIHOST_SERVER_IDS", "").strip()
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()
ORIHOST_PROXY = os.environ.get("ORIHOST_PROXY", "").strip()

if not USERNAME or not PASSWORD:
    print("❌ 缺少环境变量 ORIHOST_USERNAME 或 ORIHOST_PASSWORD，脚本终止。")
    sys.exit(1)

SERVER_IDS = [s.strip() for s in SERVER_IDS_RAW.split(",") if s.strip()]
if not SERVER_IDS:
    print("❌ 缺少环境变量 ORIHOST_SERVER_IDS，脚本终止。")
    sys.exit(1)


def send_telegram(message: str):
    """发送 Telegram 汇总通知"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ Telegram 未配置，跳过推送")
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message}, timeout=10)
        print("  ✅ Telegram 消息推送成功")
    except Exception as e:
        print(f"  ❌ Telegram 发送失败: {e}")


def get_authenticated_session():
    """使用 Playwright 模拟登录并提取 Session 与 XSRF Token"""
    print("🚀 启动无头浏览器执行自动登录...")
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
            print("  🌐 已载入登录页面，正在输入凭据...")

            # 兼容各类表单 input 命名
            if page.locator("input[name='user']").count() > 0:
                page.fill("input[name='user']", USERNAME)
            elif page.locator("input[type='text'], input[type='email']").count() > 0:
                page.fill("input[type='text'], input[type='email']", USERNAME)

            page.fill("input[type='password']", PASSWORD)
            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle", timeout=60000)
            time.sleep(3)

            cookies_list = context.cookies()
            cookies_dict = {c["name"]: c["value"] for c in cookies_list}

            xsrf_token = cookies_dict.get("XSRF-TOKEN", "")
            if xsrf_token:
                xsrf_token = unquote(xsrf_token)

            if "jexactyl_session" not in cookies_dict and "pterodactyl_session" not in cookies_dict:
                print("❌ 登录失败：未检测到有效 Session Cookie，请确认账号密码或是否存在验证码拦截。")
                browser.close()
                return None, None

            print("✅ 登录成功，已抓取最新实时 Session！")
            browser.close()
            return cookies_dict, xsrf_token

        except Exception as e:
            print(f"❌ 自动化登录流程异常: {e}")
            browser.close()
            return None, None


def renew_server(cookies: dict, xsrf_token: str, server_id: str) -> dict:
    """调用接口完成服务器续期"""
    headers = {
        "accept": "application/json",
        "accept-language": "zh-CN,zh;q=0.9",
        "x-requested-with": "XMLHttpRequest",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": f"{BASE_URL}/server/{server_id[:8]}",
    }
    if xsrf_token:
        headers["x-xsrf-token"] = xsrf_token

    # 步骤 1: 开始续期
    begin_url = f"{BASE_URL}/api/client/servers/{server_id}/renew/begin"
    print(f"\n🔄 [{server_id[:8]}] 请求开始续期...")
    try:
        resp = requests.post(begin_url, headers=headers, cookies=cookies, timeout=30)
    except Exception as e:
        return {"status": "error", "message": f"连接失败: {e}"}

    if resp.status_code != 200:
        return {"status": "error", "message": f"begin 失败 HTTP {resp.status_code}: {resp.text[:100]}"}

    try:
        data = resp.json()
    except Exception:
        return {"status": "error", "message": "响应解析失败"}

    dwell_seconds = data.get("dwell_seconds", 15)
    print(f"  ⏳ 正在模拟阅读文章，等待 {dwell_seconds + 1} 秒...")
    time.sleep(dwell_seconds + 1)

    # 步骤 2: 确认完成续期
    complete_url = f"{BASE_URL}/api/client/renewal/complete"
    try:
        resp2 = requests.get(complete_url, headers=headers, cookies=cookies, timeout=30)
    except Exception as e:
        return {"status": "error", "message": f"complete 请求异常: {e}"}

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
        return {"status": "unknown", "message": f"返回未知数据: {result}"}


def main():
    print("=" * 45)
    print(" Orihost 自动登录与自动续期任务")
    print("=" * 45)

    cookies, xsrf_token = get_authenticated_session()
    if not cookies:
        msg = f"🖥 Orihost 自动续期\n\n❌ 登录失败: 无法获取登录会话"
        send_telegram(msg)
        sys.exit(1)

    results = []
    status_map = {
        "success": "✅ 续期成功",
        "skipped": "⏭️ 已达上限",
        "error": "❌ 续期失败",
        "unknown": "⚠️ 状态异常",
    }

    for sid in SERVER_IDS:
        res = renew_server(cookies, xsrf_token, sid)
        status_text = status_map.get(res["status"], "❌ 续期失败")
        print(f"  📌 结果: {status_text} -> {res.get('message')}")
        results.append(f"• 服务器 `{sid[:8]}`: {status_text}\n  └ 详情: {res.get('message')}")

    now = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    summary_msg = (
        f"🖥 *Orihost 服务器自动续期任务汇总*\n\n"
        + "\n\n".join(results)
        + f"\n\n⏰ 执行时间: `{now}`"
    )
    send_telegram(summary_msg)


if __name__ == "__main__":
    main()
