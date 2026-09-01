#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Orihost 自动续期脚本 (SeleniumBase UC + 物理点击过盾版)
# ============================================================
import os
import sys
import time
import socket
import requests
from datetime import datetime, timezone, timedelta
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

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

UC_PROXY = None
if ORIHOST_PROXY and is_proxy_alive(ORIHOST_PROXY):
    UC_PROXY = ORIHOST_PROXY
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
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ Telegram 未配置，跳过推送", flush=True)
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message}, timeout=15)
        print("  ✅ Telegram 消息推送成功", flush=True)
    except Exception as e:
        print(f"  ❌ Telegram 发送失败: {e}", flush=True)


def solve_turnstile(driver, max_wait=20):
    """检测并点击过 Cloudflare Turnstile"""
    for i in range(max_wait):
        try:
            token = driver.execute_script("""
                const el = document.querySelector('input[name="cf-turnstile-response"]');
                return el ? el.value : null;
            """)
            if token and len(token) > 20:
                print("  🛡️ Turnstile 验证已顺利通过！", flush=True)
                return True
        except Exception:
            pass

        # 每隔 2 秒尝试一次物理定位点击
        if i % 2 == 0:
            try:
                driver.uc_gui_click_captcha()
            except Exception:
                pass
        time.sleep(1)
    return False


def process_account(acc):
    username = acc["username"]
    password = acc["password"]
    server_ids = acc["server_ids"]
    label = acc["label"]

    print(f"\n{'='*40}\n🚀 正在处理 {label} (用户: {username[:3]}***)\n{'='*40}", flush=True)
    account_results = []

    driver = Driver(uc=True, headless=False, proxy=UC_PROXY)

    try:
        # 1. 打开登录页面
        print(f"  🌐 正在打开登录页面: {LOGIN_URL} ...", flush=True)
        driver.uc_open_with_reconnect(LOGIN_URL, reconnect_time=4)
        time.sleep(3)

        # 定位用户名字段并输入
        user_selector = "input[name='user'], input[name='username'], input[name='email'], input[type='text'], input[type='email']"
        driver.wait_for_element_visible(user_selector, timeout=25)
        
        user_elem = driver.find_element(By.CSS_SELECTOR, user_selector)
        user_elem.click()
        user_elem.clear()
        user_elem.send_keys(username)
        time.sleep(1)

        # 定位密码框并输入
        pwd_elem = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        pwd_elem.click()
        pwd_elem.clear()
        pwd_elem.send_keys(password)
        time.sleep(1)

        print("  🛡️ 正在进行登录页 Turnstile 物理识别与点击...", flush=True)
        solve_turnstile(driver, max_wait=20)
        time.sleep(2)

        print("  🔑 正在提交登录...", flush=True)
        try:
            # 优先点击 Sign In 提交按钮
            driver.click("button[type='submit']")
        except Exception:
            pwd_elem.send_keys(Keys.RETURN)

        # 等待页面离开 /auth/login
        for _ in range(12):
            if "/auth/login" not in driver.current_url:
                break
            time.sleep(1)

        if "/auth/login" in driver.current_url:
            body_text = driver.get_text("body")
            err_hint = "页面未跳转"
            for line in body_text.split("\n"):
                if any(k in line.lower() for k in ["invalid", "incorrect", "credentials", "captcha", "turnstile"]):
                    err_hint = line.strip()
                    break
            print(f"  ❌ 登录未成功跳转，提示: {err_hint}", flush=True)
            account_results.append(f"• {label}: ❌ 登录失败 ({err_hint})")
            return account_results

        print(f"  ✅ 登录成功！当前页面: {driver.current_url}", flush=True)

        # 2. 依次续期服务器
        for sid in server_ids:
            short_id = sid[:8]
            server_url = f"{BASE_URL}/server/{short_id}"
            print(f"\n🔄 [{short_id}] 打开服务器控制台: {server_url} ...", flush=True)
            driver.get(server_url)
            time.sleep(4)

            # 点击 Renew 按钮
            if not driver.is_element_visible("button:contains('Renew')"):
                print(f"  ⚠️ 未找到 Renew 按钮", flush=True)
                account_results.append(f"• 服务器 `{short_id}`: ⚠️ 未找到 Renew 按钮")
                continue

            print(f"  👉 点击 [Renew] 按钮...", flush=True)
            driver.click("button:contains('Renew')")
            time.sleep(2)

            # 点击 Read Article
            if driver.is_element_visible("button:contains('Read Article')"):
                print(f"  📰 点击 [Read Article] ...", flush=True)
                main_window = driver.current_window_handle
                driver.click("button:contains('Read Article')")
                
                print(f"  ⏳ 模拟阅读文章，等待 16 秒...", flush=True)
                time.sleep(16)

                for handle in driver.window_handles:
                    if handle != main_window:
                        driver.switch_to.window(handle)
                        driver.close()
                driver.switch_to.window(main_window)
            else:
                time.sleep(5)

            # 等待 Cloudflare Turnstile 验证
            print(f"  🛡️ 等待弹窗 Turnstile 验证通过...", flush=True)
            solve_turnstile(driver, max_wait=20)

            claim_selector = "button:contains('Claim Renewal'), button:contains('Claim')"
            claim_clicked = False

            for _ in range(15):
                if driver.is_element_visible(claim_selector):
                    try:
                        driver.click(claim_selector)
                        claim_clicked = True
                        break
                    except Exception:
                        pass
                time.sleep(1)

            if claim_clicked:
                time.sleep(4)
                print(f"  🎉 点击 [Claim Renewal] 完成续期！", flush=True)
                account_results.append(f"• 服务器 `{short_id}`: ✅ 续期成功 (+7天)")
            else:
                body_text = driver.get_text("body")
                if "limit" in body_text.lower() or "cooldown" in body_text.lower():
                    print(f"  ⏭️ 该服务器处于冷却期或已达续期上限", flush=True)
                    account_results.append(f"• 服务器 `{short_id}`: ⏭️ 已达上限/冷却中")
                else:
                    print(f"  ❌ 未能成功点击 Claim Renewal", flush=True)
                    account_results.append(f"• 服务器 `{short_id}`: ❌ Claim 按钮未就绪")

    except Exception as e:
        print(f"❌ 流程发生异常: {e}", flush=True)
        account_results.append(f"• {label}: ❌ 执行异常: {str(e)[:60]}")
    finally:
        driver.quit()

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
