#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Orihost 自动登录与续期脚本 (Playwright 强化版)
# ============================================================
import os
import sys
import time
import requests
from urllib.parse import unquote
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

# 基础 URL
BASE_URL = "https://panel.orihost.com"
LOGIN_URL = f"{BASE_URL}/auth/login"

# 读取环境变量
ORIHOST_PROXY = os.environ.get("ORIHOST_PROXY", "").strip()
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()

# 代理检测与配置
REQUESTS_PROXIES = {}
PLAYWRIGHT_PROXY = None

if ORIHOST_PROXY:
    test_proxies = {"http": ORIHOST_PROXY, "https": ORIHOST_PROXY}
    try:
        # 测试代理连通性 (2秒超时)
        requests.get("http://www.google.com/generate_204", proxies=test_proxies, timeout=3)
        REQUESTS_PROXIES = test_proxies
        PLAYWRIGHT_PROXY = {"server": ORIHOST_PROXY}
        print(f"✅ 代理测试成功，已启用代理: {ORIHOST_PROXY}", flush=True)
    except Exception:
        print(f"⚠️ 代理连接失败 ({ORIHOST_PROXY})，自动回退直连模式", flush=True)

# 账号解析 (支持单账号与多账号)
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
    print("❌ 未检测到任何账号配置，请在 Secrets 中添加 ORIHOST_USERNAME 与 ORIHOST_PASSWORD", flush=True)
    sys.exit(1)


def send_telegram(message: str):
    """发送 Telegram 消息通知"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ 未配置 TG_BOT_TOKEN 或 TG_CHAT_ID，跳过通知", flush=True)
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message}, proxies=REQUESTS_PROXIES or None, timeout=15)
        if resp.status_code == 200:
            print("  ✅ Telegram 消息推送成功", flush=True)
        else:
            print(f"  ❌ Telegram 推送返回异常 HTTP {resp.status_code}: {resp.text}", flush=True)
    except Exception as e:
        print(f"  ❌ Telegram 发送失败: {e}", flush=True)


def get_authenticated_session(username, password):
    """使用 Playwright 自动登录并捕获会话"""
    print(f"🚀 启动无头浏览器登录账号: {username} ...", flush=True)

    with sync_playwright() as p:
        launch_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled"
        ]
        browser = p.chromium.launch(
            headless=True,
            proxy=PLAYWRIGHT_PROXY,
            args=launch_args
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()

        try:
            print(f"  🌐 正在打开登录页: {LOGIN_URL} ...", flush=True)
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)

            # 等待输入框出现
            page.wait_for_selector("input", timeout=20000)

            # 填充用户名/邮箱 (尝试多种选择器)
            user_filled = False
            for selector in ["input[name='user']", "input[name='email']", "input[type='text']", "input[type='email']"]:
                if page.locator(selector).count() > 0:
                    page.locator(selector).first.fill(username)
                    user_filled = True
                    break
            
            if not user_filled:
                print("  ❌ 未找到用户名/邮箱输入框", flush=True)
                browser.close()
                return None, None

            # 填充密码
            if page.locator("input[type='password']").count() > 0:
                page.locator("input[type='password']").first.fill(password)
            else:
                print("  ❌ 未找到密码输入框", flush=True)
                browser.close()
                return None, None

            # 勾选记住我
            if page.locator("input[type='checkbox']").count() > 0:
                try:
                    page.locator("input[type='checkbox']").first.check(timeout=2000)
                except Exception:
                    pass

            print("  🔑 凭据输入完毕，点击登录...", flush=True)
            if page.locator("button[type='submit']").count() > 0:
                page.locator("button[type='submit']").first.click()
            else:
                page.keyboard.press("Enter")

            # 等待跳转或登录完成
            time.sleep(6)

            # 获取 Cookie
            cookies_list = context.cookies()
            cookies_dict = {c["name"]: c["value"] for c in cookies_list}
            xsrf_token = cookies_dict.get("XSRF-TOKEN", "")
            if xsrf_token:
                xsrf_token = unquote(xsrf_token)

            # 验证是否获取到关键 Session
            has_session = any(k in cookies_dict for k in ["jexactyl_session", "pterodactyl_session", "session", "remember_web_"])
            if not has_session:
                print("❌ 登录失败：未检测到有效 Session Cookie，可能密码错误或触发了人机验证拦截。", flush=True)
                browser.close()
                return None, None

            print("✅ 登录成功，已获取有效 Session 与 XSRF Token！", flush=True)
            browser.close()
            return cookies_dict, xsrf_token

        except Exception as e:
            print(f"❌ 登录流程发生异常: {e}", flush=True)
            browser.close()
            return None, None


def renew_server(cookies: dict, xsrf_token: str, server_id: str) -> dict:
    """调用 API 完成服务器续期"""
    headers = {
        "accept": "application/json",
        "accept-language": "zh-CN,zh;q=0.9",
        "x-requested-with": "XMLHttpRequest",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "referer": f"{BASE_URL}/server/{server_id[:8]}",
    }
    if xsrf_token:
        headers["x-xsrf-token"] = xsrf_token

    # 1. 发起续期
    begin_url = f"{BASE_URL}/api/client/servers/{server_id}/renew/begin"
    print(f"\n🔄 [{server_id[:8]}] 开始续期会话...", flush=True)
    try:
        resp = requests.post(begin_url, headers=headers, cookies=cookies, proxies=REQUESTS_PROXIES or None, timeout=30)
    except Exception as e:
        return {"status": "error", "message": f"连接超时: {e}"}

    if resp.status_code != 200:
        return {"status": "error", "message": f"begin 响应异常 HTTP {resp.status_code}: {resp.text[:100]}"}

    try:
        data = resp.json()
    except Exception:
        return {"status": "error", "message": "JSON 解析失败"}

    dwell_seconds = data.get("dwell_seconds", 15)
    print(f"  ⏳ 正在模拟阅读文章，等待 {dwell_seconds + 1} 秒...", flush=True)
    time.sleep(dwell_seconds + 1)

    # 2. 确认完成续期
    complete_url = f"{BASE_URL}/api/client/renewal/complete"
    try:
        resp2 = requests.get(complete_url, headers=headers, cookies=cookies, proxies=REQUESTS_PROXIES or None, timeout=30)
    except Exception as e:
        return {"status": "error", "message": f"complete 请求异常: {e}"}

    if resp2.status_code != 200:
        return {"status": "error", "message": f"complete 响应异常 HTTP {resp2.status_code}"}

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
        return {"status": "unknown", "message": f"返回响应: {result}"}


def main():
    print("=" * 45, flush=True)
    print(" Orihost 自动登录与自动续期任务", flush=True)
    print("=" * 45, flush=True)

    all_results = []
    status_map = {
        "success": "✅ 续期成功",
        "skipped": "⏭️ 已达上限",
        "error": "❌ 续期失败",
        "unknown": "⚠️ 状态异常",
    }

    for acc in ACCOUNTS:
        print(f"\n--- 正在处理 {acc['label']} ---", flush=True)
        cookies, xsrf_token = get_authenticated_session(acc["username"], acc["password"])
        if not cookies:
            all_results.append(f"• {acc['label']}: ❌ 登录失败（未能获取会话）")
            continue

        for sid in acc["server_ids"]:
            res = renew_server(cookies, xsrf_token, sid)
            st_text = status_map.get(res["status"], "❌ 续期失败")
            print(f"  📌 结果: {st_text} ({res.get('message')})", flush=True)
            all_results.append(f"• 服务器 `{sid[:8]}`: {st_text}\n  └ 详情: {res.get('message')}")

    now = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    summary = f"🖥 *Orihost 服务器自动续期汇总*\n\n" + "\n\n".join(all_results) + f"\n\n⏰ 执行时间: `{now}`"
    send_telegram(summary)
    print("\n✅ 所有任务处理完毕！", flush=True)


if __name__ == "__main__":
    main()
