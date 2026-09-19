#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Orihost 自动续期与电源巡检 (高清图文卡片推送版)
# ============================================================
import html
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
import requests
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


def tg_send(text: str, photo_path: str = None):
    """支持图文卡片发送"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ 未配置 TG_BOT_TOKEN / TG_CHAT_ID，跳过通知。")
        return
    try:
        if photo_path and os.path.exists(photo_path) and os.path.getsize(photo_path) > 1000:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
            with open(photo_path, "rb") as f:
                requests.post(
                    url,
                    data={"chat_id": TG_CHAT_ID, "caption": text, "parse_mode": "HTML"},
                    files={"photo": f},
                    timeout=30,
                )
        else:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
            requests.post(
                url,
                data={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
                timeout=30,
            )
        print("  ✅ TG 图文通知发送成功", flush=True)
    except Exception as e:
        print(f"  ⚠️ TG 通知异常: {e}", flush=True)


def capture_screenshot(driver, save_path="ori_result.png"):
    """安全截屏"""
    try:
        driver.save_screenshot(save_path)
        if os.path.exists(save_path) and os.path.getsize(save_path) > 15000:
            return True
    except Exception:
        pass
    try:
        subprocess.run(["scrot", "-u", save_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:
        pass
    return True


def solve_turnstile(driver, max_wait=20):
    """检测并点击 Cloudflare Turnstile"""
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


def get_power_status(driver, max_wait=6):
    """精准判定电源状态"""
    for _ in range(max_wait):
        try:
            body = driver.get_text("body")
            if "App is running" in body:
                return "ONLINE"
            if "App is stopped" in body:
                return "STOPPED"

            stop_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Stop')]")
            if stop_btns and stop_btns[0].is_displayed() and stop_btns[0].is_enabled():
                return "ONLINE"

            start_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Start')]")
            if start_btns and start_btns[0].is_displayed() and start_btns[0].is_enabled():
                return "STOPPED"
        except Exception:
            pass
        time.sleep(1)
    return "ONLINE"


def ensure_server_running(driver):
    """如确认关机，自动点 Start"""
    status = get_power_status(driver)
    if status == "STOPPED":
        print("  ⚡ 确认处于停止状态，点击 Start 开机...", flush=True)
        start_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Start')]")
        for btn in start_btns:
            if btn.is_displayed() and btn.is_enabled():
                safe_click(driver, btn)
                print("  👉 已点击 Start 开机按钮！", flush=True)
                time.sleep(4)
                return "STOPPED", "⚡ 已执行开机"
        return "STOPPED", "⚠️ 停止 (开机按钮未就绪)"
    return "ONLINE", "正常运行"


def remove_ad_overlays(driver):
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
    try:
        element.click()
    except Exception:
        remove_ad_overlays(driver)
        driver.execute_script("arguments[0].click();", element)


def process_server(driver, sid, label):
    short_id = sid[:8]
    server_url = f"{BASE_URL}/server/{short_id}"
    print(f"\n🔄 [{short_id}] 打开服务器控制台: {server_url} ...", flush=True)
    driver.get(server_url)

    # 等待页面主容器加载
    renew_xpath = "//button[contains(., 'Renew') or contains(., 'renew')]"
    try:
        driver.wait_for_element_visible(renew_xpath, by=By.XPATH, timeout=25)
    except Exception:
        pass

    # 1. 检测电源并处理
    power_status, power_action = ensure_server_running(driver)
    days_before = get_current_renewal_days(driver)
    days_before_str = f"{days_before} 天" if days_before is not None else "未知"
    print(f"  🖥️ 电源状态: {power_status} ({power_action}) | 当前剩余: {days_before_str}", flush=True)

    renew_elements = driver.find_elements(By.XPATH, renew_xpath)
    action_desc = "⚠️ 未找到控制台 Renew 按钮"
    days_after_str = days_before_str

    if renew_elements:
        print(f"  👉 点击控制台右下角 [Renew] 按钮...", flush=True)
        safe_click(driver, renew_elements[0])
        time.sleep(3)

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
            time.sleep(4)

        # 验证 Turnstile
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
                days_after_str = f"{days_after} 天"
                if days_before is not None and days_after > days_before:
                    action_desc = f"✅ 成功续期 (+7天)"
                else:
                    action_desc = f"⏭️ 当前处于上限，维持满期"
            else:
                action_desc = "✅ 续期动作已触发"
        else:
            cur_text = driver.get_text("body")
            if any(k in cur_text.lower() for k in ["cooldown", "limit", "renewed", "10 days", "3 days"]):
                action_desc = "⏭️ 处于冷却期/维持满期"
            else:
                action_desc = "❌ Claim 按钮未就绪"

    # 截取控制台最新画面
    shot_name = f"ori_{short_id}.png"
    time.sleep(2)
    capture_screenshot(driver, shot_name)

    now_str = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

    # 构建富文本图文消息
    msg = (
        f"📋 <b>Orihost 续期巡检报告</b>\n\n"
        f"🏷️ <b>账号归属：</b><code>{label}</code>\n"
        f"🖥️ <b>实例短 ID：</b><code>{short_id}</code>\n"
        f"🔌 <b>实例电源：</b><code>{power_status}</code>\n"
        f"⚡ <b>电源动作：</b><code>{power_action}</code>\n"
        f"⏳ <b>续期前天数：</b><code>{days_before_str}</code>\n"
        f"⌛ <b>续期后天数：</b><code>{days_after_str}</code>\n"
        f"📊 <b>执行结果：</b><code>{action_desc}</code>\n"
        f"⏰ <b>执行时间：</b><code>{now_str}</code>"
    )

    tg_send(msg, photo_path=shot_name)


def process_account(acc):
    username = acc["username"]
    password = acc["password"]
    server_ids = acc["server_ids"]
    label = acc["label"]

    print(f"\n{'='*40}\n🚀 正在处理 {label} (用户: {username[:3]}***)\n{'='*40}", flush=True)

    driver = Driver(uc=True, headless=False, proxy=UC_PROXY)

    try:
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
            print("  ❌ 登录未成功跳转！", flush=True)
            capture_screenshot(driver, "ori_login_failed.png")
            tg_send(f"🔴 <b>Orihost 登录失败 ({label})</b>", photo_path="ori_login_failed.png")
            return

        print(f"  ✅ 登录成功！当前页面: {driver.current_url}", flush=True)

        for sid in server_ids:
            process_server(driver, sid, label)

    except Exception as e:
        print(f"❌ 流程发生异常: {e}", flush=True)
        capture_screenshot(driver, "ori_error.png")
        tg_send(f"🔴 <b>Orihost 执行异常 ({label})</b>\n\n<code>{html.escape(str(e))}</code>", photo_path="ori_error.png")
    finally:
        driver.quit()


def main():
    print("=" * 45, flush=True)
    print(" Orihost 自动续期巡检启动 (图文推送版)", flush=True)
    print("=" * 45, flush=True)

    for acc in ACCOUNTS:
        process_account(acc)

    print("\n✅ 所有任务执行完毕！", flush=True)


if __name__ == "__main__":
    main()
