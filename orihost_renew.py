#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Orihost 自动登录与全真 UI 续期脚本 (React 表单深度适配版)
# ============================================================
import os
import sys
import time
import socket
import requests
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

BASE_URL = "https://panel.orihost.com"
LOGIN_URL = f"{BASE_URL}/auth/login"

ORIHOST_PROXY = os.environ.get("ORIHOST_PROXY", "").strip()
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()

def is_proxy_alive(proxy_str: str) -> bool:
    if not proxy_str:
        return False
    try:
        host_port = proxy_str.split("://")[-1]
        host, port = host_port.split(":")
        with socket.create_connection((host, int(port)), timeout=3):
            return True
    except Exception:
        return False

PLAYWRIGHT_PROXY = None
if ORIHOST_PROXY and is_proxy_alive(ORIHOST_PROXY):
    PLAYWRIGHT_PROXY = {"server": ORIHOST_PROXY}
    print(f"🔗 代理检测正常，已启用: {ORIHOST_PROXY}", flush=True)
else:
    if ORIHOST_PROXY:
        print(f"⚠️ 代理不可达 ({ORIHOST_PROXY})，自动降级为直连模式", flush=True)

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
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ Telegram 未配置，跳过推送", flush=True)
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message}, timeout=15)
        print("  ✅ Telegram 消息推送成功", flush=True)
    except Exception as e:
        print(f"  ❌ Telegram 发送失败: {e}", flush=True)


def process_account(acc):
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

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        try:
            print(f"  🌐 正在打开登录页面: {LOGIN_URL} ...", flush=True)
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("input[type='password']", timeout=30000)
            time.sleep(2)

            # 定位用户名字段
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

            # 聚焦并输入用户名
            user_input.click()
            user_input.fill("")
            user_input.press_sequentially(username, delay=60)
            user_input.evaluate("el => el.dispatchEvent(new Event('blur', { bubbles: true }))")

            # 聚焦并输入密码
            pwd_input = page.locator("input[type='password']").first
            pwd_input.click()
            pwd_input.fill("")
            pwd_input.press_sequentially(password, delay=60)
            pwd_input.evaluate("el => el.dispatchEvent(new Event('blur', { bubbles: true }))")

            # 勾选记住我
            if page.locator("input[type='checkbox']").count() > 0:
                try:
                    page.locator("input[type='checkbox']").first.check(timeout=2000)
                except Exception:
                    pass

            time.sleep(2)
            print("  🔑 正在提交表单...", flush=True)

            # 强制解除可能残留的 disabled 状态并触发真实点击
            page.evaluate("""
                () => {
                    const btn = document.querySelector('button[type="submit"]');
                    if (btn) {
                        btn.removeAttribute('disabled');
                        btn.click();
                    }
                }
            """)

            # 监听页面跳转或表单返回
            time.sleep(8)

            # 判断是否登录成功
            if "/auth/login" in page.url:
                # 再次尝试回车提交
                pwd_input.press("Enter")
                time.sleep(6)

            if "/auth/login" in page.url:
                body_text = page.inner_text("body")
                error_lines = [
                    line.strip() for line in body_text.split("\n")
                    if any(k in line.lower() for k in ["invalid", "incorrect", "credentials", "error", "turnstile", "captcha"])
                ]
                err_hint = " | ".join(error_lines[:3]) if error_lines else "表单未触发跳转"
                print(f"  ❌ 登录未成功跳转，页面提示: {err_hint}", flush=True)
                account_results.append(f"• {label}: ❌ 登录失败 ({err_hint})")
                browser.close()
                return account_results

            print(f"  ✅ 登录成功！进入后台页面: {page.url}", flush=True)

            # 2. 遍历续期
            for sid in server_ids:
                short_id = sid[:8]
                server_url = f"{BASE_URL}/server/{short_id}"
                print(f"\n🔄 [{short_id}] 打开服务器控制台: {server_url} ...", flush=True)
                page.goto(server_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(4)

                renew_btn = page.locator("button:has-text('Renew'), button:has-text('📅 Renew')").first
                if renew_btn.count() == 0:
                    print(f"  ⚠️ 未找到 Renew 按钮", flush=True)
                    account_results.append(f"• 服务器 `{short_id}`: ⚠️ 未找到 Renew 按钮")
                    continue

                print(f"  👉 点击 [Renew] 按钮...", flush=True)
                renew_btn.click()
                time.sleep(2)

                read_btn = page.locator("button:has-text('Read Article')").first
                if read_btn.count() > 0:
                    print(f"  📰 点击 [Read Article] 并监听新标签页...", flush=True)
                    with context.expect_page() as new_page_info:
                        read_btn.click()
                    
                    try:
                        ad_page = new_page_info.value
                        print(f"  ⏳ 模拟阅读等待 16 秒...", flush=True)
                        time.sleep(16)
                        ad_page.close()
                        print(f"  🗞️ 关闭文章页", flush=True)
                    except Exception:
                        print(f"  ⏳ 等待 16 秒...", flush=True)
                        time.sleep(16)
                else:
                    time.sleep(5)

                page.bring_to_front()
                time.sleep(2)

                claim_btn = page.locator("button:has-text('Claim Renewal'), button:has-text('Claim')").first
                print(f"  🛡️ 等待 Cloudflare Turnstile 验证通过...", flush=True)
                for _ in range(15):
                    if claim_btn.count() > 0 and claim_btn.is_enabled():
                        break
                    time.sleep(1)

                if claim_btn.count() > 0 and claim_btn.is_enabled():
                    print(f"  🎉 点击 [Claim Renewal] 完成续期！", flush=True)
                    claim_btn.click()
                    time.sleep(4)
                    print(f"  ✅ 服务器 {short_id} 续期成功！", flush=True)
                    account_results.append(f"• 服务器 `{short_id}`: ✅ 续期成功 (+7天)")
                else:
                    modal_text = page.locator("[role='dialog'], .modal, div").all_inner_texts()
                    full_text = " ".join(modal_text)
                    if "limit" in full_text.lower() or "cooldown" in full_text.lower():
                        print(f"  ⏭️ 该服务器处于冷却期或已达续期上限", flush=True)
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
