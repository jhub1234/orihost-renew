#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Orihost 自动续期脚本 (JS 穿透点击 + 遮罩层清除版)
# ============================================================
import os
import re
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

        if i % 2 == 0:
            try:
                driver.uc_gui_click_captcha()
            except Exception:
                pass
        time.sleep(1)
    return False


def get_current_renewal_days(driver):
    """从控制台页面提取当前剩余天数"""
    try:
        text = driver.get_text("body")
        match = re.search(r"RENEWAL\s+IN\s+(\d+)\s+Days?", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return None


def remove_ad_overlays(driver):
    """清除可能阻挡点击的广告全屏遮罩 iframe"""
    try:
        driver.execute_script("""
            const iframes = document.querySelectorAll('iframe[style*="z-index"], iframe[style*="fixed"]');
            iframes.forEach(el => {
                if (!el.src.includes('turnstile') && !el.src.includes('challenges.cloudflare')) {
                    el.remove();
                }
            });
        """)
    except Exception:
        pass


def safe_click(driver, element):
    """先尝试常规点击，遇到拦截则自动回退为 JS 穿透点击"""
    try:
        element.click()
    except Exception:
        remove_ad_overlays(driver)
        driver.execute_script("arguments[0].click();", element)


def process_account(acc):
    username = acc["username"]
    password = acc["password"]
    server_ids = acc["server_ids"]
    label = acc["label"]

    print(f"\n{'='*40}\n🚀 正在处理 {label} (用户: {username[:3]}***)\n{'='*40}", flush=True)
    account_results = []

    driver = Driver(uc=True, headless=False, proxy=UC_PROXY)

    try:
        # 1. 登录
        print(f"  🌐 正在打开登录页面: {LOGIN_URL} ...", flush=True)
        driver.uc_open_with_reconnect(LOGIN_URL, reconnect_time=4)
        time.sleep(3)

        user_selector = "input[name='user'], input[name='username'], input[name='email'], input[type='text'], input[type='email']"
        driver.wait_for_element_visible(user_selector, timeout=25)
        
        user_elem = driver.find_element(By.CSS_SELECTOR, user_selector)
        user_elem.click()
        user_elem.clear()
        user_elem.send_keys(username)
        time.sleep(1)

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
            submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            safe_click(driver, submit_btn)
        except Exception:
            pwd_elem.send_keys(Keys.RETURN)

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

            # 显式等待 Renew 按钮渲染
            renew_xpath = "//button[contains(., 'Renew') or contains(., 'renew')]"
            try:
                driver.wait_for_element_visible(renew_xpath, by=By.XPATH, timeout=25)
            except Exception:
                pass

            days_before = get_current_renewal_days(driver)
            if days_before is not None:
                print(f"  📊 当前服务器剩余续期天数: {days_before} 天", flush=True)

            renew_elements = driver.find_elements(By.XPATH, renew_xpath)
            if not renew_elements:
                print(f"  ⚠️ 控制台未加载出 Renew 按钮", flush=True)
                account_results.append(f"• 服务器 `{short_id}`: ⚠️ 未找到 Renew 按钮")
                continue

            print(f"  👉 点击控制台右下角 [Renew] 按钮...", flush=True)
            safe_click(driver, renew_elements[0])
            time.sleep(3)

            # 点击 Read Article
            read_xpath = "//button[contains(., 'Read Article') or contains(., 'Article')]"
            read_elements = driver.find_elements(By.XPATH, read_xpath)
            if read_elements and read_elements[0].is_displayed():
                print(f"  📰 点击 [Read Article] 弹窗...", flush=True)
                main_window = driver.current_window_handle
                safe_click(driver, read_elements[0])
                
                print(f"  ⏳ 模拟阅读新闻文章，等待 17 秒...", flush=True)
                time.sleep(17)

                for handle in driver.window_handles:
                    if handle != main_window:
                        try:
                            driver.switch_to.window(handle)
                            driver.close()
                        except Exception:
                            pass
                driver.switch_to.window(main_window)
                time.sleep(2)
            else:
                time.sleep(5)

            # 等待 Cloudflare Turnstile 验证通过
            print(f"  🛡️ 等待弹窗 Turnstile 人机验证通过...", flush=True)
            solve_turnstile(driver, max_wait=20)
            time.sleep(2)

            claim_xpath = "//button[contains(., 'Claim') or contains(., 'claim') or contains(., 'Renewal')]"
            claim_clicked = False

            for _ in range(15):
                claim_elements = driver.find_elements(By.XPATH, claim_xpath)
                for btn in claim_elements:
                    if btn.is_displayed():
                        safe_click(driver, btn)
                        claim_clicked = True
                        break
                if claim_clicked:
                    break
                time.sleep(1)

            if claim_clicked:
                time.sleep(4)
                driver.refresh()
                time.sleep(4)
                days_after = get_current_renewal_days(driver)
                
                if days_after is not None:
                    if days_before is not None and days_after > days_before:
                        print(f"  🎉 续期成功！天数由 {days_before} 天增加至 {days_after} 天", flush=True)
                        account_results.append(f"• 服务器 `{short_id}`: ✅ 续期成功 ({days_before}天 ➜ {days_after}天)")
                    else:
                        print(f"  ⏭️ 当前已处于上限 (剩余 {days_after} 天)", flush=True)
                        account_results.append(f"• 服务器 `{short_id}`: ⏭️ 维持满期 ({days_after}天)")
                else:
                    print(f"  ✅ 续期动作已触发完成", flush=True)
                    account_results.append(f"• 服务器 `{short_id}`: ✅ 续期动作已完成")
            else:
                cur_text = driver.get_text("body")
                if any(k in cur_text.lower() for k in ["cooldown", "limit", "renewed", "10 days", "3 days"]):
                    print(f"  ⏭️ 该服务器处于冷却期或已达上限（无需重复续期）", flush=True)
                    account_results.append(f"• 服务器 `{short_id}`: ⏭️ 维持满期/冷却中")
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
