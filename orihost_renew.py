#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Orihost 自动登录与全自动 UI 交互续期脚本 (支持 Cloudflare Turnstile)
# ============================================================
import os
import sys
import time
import requests
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

BASE_URL = "https://panel.orihost.com"
LOGIN_URL = f"{BASE_URL}/auth/login"

ORIHOST_PROXY = os.environ.get("ORIHOST_PROXY", "").strip()
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()

REQUESTS_PROXIES = {}
PLAYWRIGHT_PROXY = None

if ORIHOST_PROXY:
    REQUESTS_PROXIES = {"http": ORIHOST_PROXY, "https": ORIHOST_PROXY}
    PLAYWRIGHT_PROXY = {"server": ORIHOST_PROXY}
    print(f"🔗 已配置代理: {ORIHOST_PROXY}", flush=True)

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
    print("❌ 未检测到任何账号配置，请在 Secrets 中配置 ORIHOST_USERNAME 与 ORIHOST_PASSWORD", flush=True)
    sys.exit(1)


def send_telegram(message: str):
    """发送 Telegram 通知"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ Telegram 未配置，跳过推送", flush=True)
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message}, proxies=REQUESTS_PROXIES or None, timeout=15)
        print("  ✅ Telegram 消息推送成功", flush=True)
    except Exception as e:
        print(f"  ❌ Telegram 发送失败: {e}", flush=True)


def process_account(acc):
    """处理单个账号的登录及每个服务器的全真 UI 续期"""
    username = acc["username"]
    password = acc["password"]
    server_ids = acc["server_ids"]
    label = acc["label"]

    print(f"\n{'='*40}\n🚀 正在处理 {label} (用户: {username[:3]}***)\n{'='*40}", flush=True)
    account_results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy=PLAYWRIGHT_PROXY,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()

        try:
            # 1. 登录
            print(f"  🌐 正在打开登录页面: {LOGIN_URL} ...", flush=True)
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("input[type='password']", timeout=30000)
            time.sleep(2)

            # 输入用户名
            user_input = None
            for sel in ["input[name='user']", "input[name='username']", "input[name='email']", "input[type='text']", "input[type='email']"]:
                if page.locator(sel).count() > 0:
                    user_input = page.locator(sel).first
                    break

            if not user_input:
                print("  ❌ 未找到用户名输入框", flush=True)
                account_results.append(f"• {label}: ❌ 找不到用户名输入框")
                browser.close()
                return account_results

            user_input.click()
            user_input.press_sequentially(username, delay=50)

            # 输入密码
            pwd_input = page.locator("input[type='password']").first
            pwd_input.click()
            pwd_input.press_sequentially(password, delay=50)

            # 记住我
            if page.locator("input[type='checkbox']").count() > 0:
                try:
                    page.locator("input[type='checkbox']").first.check(timeout=2000)
                except Exception:
                    pass

            time.sleep(1)
            print("  🔑 正在提交登录...", flush=True)

            submit_btn = page.locator("button[type='submit']").first
            if submit_btn.is_enabled():
                submit_btn.click()
            else:
                pwd_input.press("Enter")

            # 等待离开登录页
            try:
                page.wait_for_url(lambda u: "/auth/login" not in u, timeout=25000)
                print(f"  ✅ 登录成功！进入后台页面", flush=True)
            except Exception:
                print(f"  ❌ 登录未成功跳转，当前 URL: {page.url}", flush=True)
                account_results.append(f"• {label}: ❌ 登录失败（未离开登录页）")
                browser.close()
                return account_results

            # 2. 遍历续期每个服务器
            for sid in server_ids:
                short_id = sid[:8]
                server_url = f"{BASE_URL}/server/{short_id}"
                print(f"\n🔄 [{short_id}] 正在打开服务器控制台: {server_url} ...", flush=True)
                page.goto(server_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(4)

                # 寻找 Renew 按钮
                renew_btn = page.locator("button:has-text('Renew'), button:has-text('📅 Renew')").first
                if renew_btn.count() == 0:
                    print(f"  ⚠️ 未找到 Renew 按钮，可能非免费服务器或页面结构变动", flush=True)
                    account_results.append(f"• 服务器 `{short_id}`: ⚠️ 未找到 Renew 按钮")
                    continue

                print(f"  👉 点击控制台右下角 [Renew] 按钮...", flush=True)
                renew_btn.click()
                time.sleep(2)

                # 弹窗中点击 [Read Article]
                read_btn = page.locator("button:has-text('Read Article')").first
                if read_btn.count() > 0:
                    print(f"  📰 捕获到 [Read Article] 弹窗，准备点击并监听新标签页...", flush=True)
                    with context.expect_page() as new_page_info:
                        read_btn.click()
                    
                    # 捕获弹出的文章新标签页
                    try:
                        ad_page = new_page_info.value
                        print(f"  ⏳ 已打开文章标签页，模拟阅读等待 16 秒...", flush=True)
                        time.sleep(16)
                        ad_page.close()
                        print(f"  🗞️ 文章阅读完毕，已关闭文章标签页", flush=True)
                    except Exception:
                        print(f"  ⏳ 未能捕获新标签页，直接等待 16 秒...", flush=True)
                        time.sleep(16)
                else:
                    print(f"  ℹ️ 未出现 Read Article 按钮，直接等待 5 秒...", flush=True)
                    time.sleep(5)

                # 切回主页面，处理 Cloudflare 验证 & 点击 Claim Renewal
                page.bring_to_front()
                time.sleep(2)

                # 等待 Claim Renewal 按钮出现或变为可用
                claim_btn = page.locator("button:has-text('Claim Renewal'), button:has-text('Claim')").first
                
                # 等待可能存在的 Cloudflare Turnstile 验证完毕 (最多等 15 秒)
                print(f"  🛡️ 正在等待 Cloudflare Turnstile 人机验证通过...", flush=True)
                for _ in range(15):
                    if claim_btn.count() > 0 and claim_btn.is_enabled():
                        break
                    time.sleep(1)

                if claim_btn.count() > 0 and claim_btn.is_enabled():
                    print(f"  🎉 验证通过，点击 [Claim Renewal] 完成续期！", flush=True)
                    claim_btn.click()
                    time.sleep(4)
                    print(f"  ✅ 服务器 {short_id} 续期流程已顺利执行！", flush=True)
                    account_results.append(f"• 服务器 `{short_id}`: ✅ 续期成功 (+7天)")
                else:
                    # 检查是否已达上限
                    modal_text = page.locator("[role='dialog'], .modal, div").all_inner_texts()
                    full_text = " ".join(modal_text)
                    if "limit" in full_text.lower() or "cooldown" in full_text.lower():
                        print(f"  ⏭️ 该服务器当前处于冷却期或已达续期上限", flush=True)
                        account_results.append(f"• 服务器 `{short_id}`: ⏭️ 已达上限/冷却中")
                    else:
                        print(f"  ❌ 未能成功点击 Claim Renewal", flush=True)
                        account_results.append(f"• 服务器 `{short_id}`: ❌ Claim 按钮未就绪")

        except Exception as e:
            print(f"❌ 流程发生异常: {e}", flush=True)
            account_results.append(f"• {label}: ❌ 执行异常: {str(e)[:60]}")
        finally:
            browser.close()

    return account_results


def main():
    print("=" * 45, flush=True)
    print(" Orihost 自动登录与全真 UI 续期任务", flush=True)
    print("=" * 45, flush=True)

    all_summary = []
    for acc in ACCOUNTS:
        results = process_account(acc)
        all_summary.extend(results)

    now = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    summary_text = (
        f"🖥 *Orihost 服务器自动续期汇总*\n\n"
        + "\n".join(all_summary)
        + f"\n\n⏰ 执行时间: `{now}`"
    )
    send_telegram(summary_text)
    print("\n✅ 所有任务执行完毕！", flush=True)


if __name__ == "__main__":
    main()
