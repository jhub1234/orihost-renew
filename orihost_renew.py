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
            # 改为 domcontentloaded，不再死等所有后台请求静止
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            print("  🌐 页面 DOM 加载完成，等待登录表单渲染...")

            # 等待密码输入框渲染出来
            page.wait_for_selector("input[type='password']", timeout=30000)

            # 填充用户名/邮箱
            if page.locator("input[name='user']").count() > 0:
                page.fill("input[name='user']", username)
            elif page.locator("input[name='email']").count() > 0:
                page.fill("input[name='email']", username)
            elif page.locator("input[type='text'], input[type='email']").count() > 0:
                page.locator("input[type='text'], input[type='email']").first.fill(username)

            # 填充密码
            page.fill("input[type='password']", password)

            # 勾选记住我（如果有）
            if page.locator("input[type='checkbox']").count() > 0:
                try:
                    page.locator("input[type='checkbox']").first.check(timeout=3000)
                except Exception:
                    pass

            print("  🔑 已输入凭证，正在提交登录...")
            # 点击登录提交
            page.click("button[type='submit']")

            # 等待页面跳转（URL 离开 /auth/login 或到达概览页）
            try:
                page.wait_for_url(lambda u: "/auth/login" not in u, timeout=20000)
            except Exception:
                time.sleep(5)

            cookies_list = context.cookies()
            cookies_dict = {c["name"]: c["value"] for c in cookies_list}

            xsrf_token = cookies_dict.get("XSRF-TOKEN", "")
            if xsrf_token:
                xsrf_token = unquote(xsrf_token)

            if "jexactyl_session" not in cookies_dict and "pterodactyl_session" not in cookies_dict and "session" not in cookies_dict:
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
