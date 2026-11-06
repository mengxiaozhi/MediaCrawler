# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/meta/core.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

"""Bounded, rendered-page crawling without hard-coded private API signatures."""

import asyncio
import re
from pathlib import Path
from types import ModuleType
from typing import Dict, Optional
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, BrowserType, Playwright, async_playwright

import config
from base.base_crawler import AbstractCrawler
from store.meta import MetaStore
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var


class MetaCrawlerError(RuntimeError):
    """A login wall, inaccessible post, or unsupported page layout."""


class MetaCrawler(AbstractCrawler):
    def __init__(self, adapter: ModuleType):
        self.adapter = adapter
        self.platform = adapter.PLATFORM
        self.browser_context = None
        self.context_page = None
        self.cdp_manager = None
        self._browser = None
        self._attached = False
        self._store = None
        self._saved_ids = set()

    def _validate(self):
        # Validate before opening a browser, including options inherited from the UI.
        self._store = MetaStore(self.platform)
        if config.LOGIN_TYPE not in ("cookie", "manual"):
            raise ValueError(f"{self.platform} supports --lt cookie (public/existing session) "
                             "or --lt manual (sign in in the browser).")
        if config.ENABLE_GET_MEDIA:
            raise ValueError(f"{self.platform} saves media URLs only; use --get_media false.")
        if config.CRAWLER_TYPE not in ("search", "detail", "creator"):
            raise ValueError(f"Unsupported crawler type: {config.CRAWLER_TYPE}")
        if config.CRAWLER_MAX_NOTES_COUNT < 1 or config.START_PAGE < 1:
            raise ValueError("Post limit and starting page must be positive.")
        if config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES < 0:
            raise ValueError("Comment limit cannot be negative.")
        for name in ("META_PAGE_TIMEOUT_MS", "META_SCROLL_MAX_ROUNDS", "META_SCROLL_IDLE_ROUNDS", "META_LOGIN_TIMEOUT_SEC"):
            if getattr(config, name) <= 0:
                raise ValueError(f"{name} must be positive.")
        if config.META_SCROLL_WAIT_SEC < 0 or config.CRAWLER_MAX_SLEEP_SEC < 0:
            raise ValueError("Crawl delays cannot be negative.")
        if config.CRAWLER_TYPE == "detail":
            values = self._configured_list("SPECIFIED_ID_LIST")
            if not values:
                raise ValueError("Specify post URLs with --specified_id or the platform config.")
            for value in values:
                self.adapter.normalize_post_url(value)
        elif config.CRAWLER_TYPE == "creator":
            values = self._configured_list("CREATOR_ID_LIST")
            if not values:
                raise ValueError("Specify profiles with --creator_id or the platform config.")
            for value in values:
                self.adapter.normalize_creator_url(value)
        elif not any(word.strip() for word in config.KEYWORDS.split(",")):
            raise ValueError("Specify at least one search keyword.")

    def _configured_list(self, suffix):
        return getattr(config, f"{self.platform.upper()}_{suffix}")

    async def start(self):
        crawler_type_var.set(config.CRAWLER_TYPE)
        source_keyword_var.set("")
        self._validate()
        proxy = None
        if config.ENABLE_IP_PROXY:
            from proxy.proxy_ip_pool import create_ip_pool
            pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            proxy, _ = utils.format_proxy_info(await pool.get_proxy())
        async with async_playwright() as playwright:
            try:
                if config.ENABLE_CDP_MODE:
                    self.browser_context = await self.launch_browser_with_cdp(
                        playwright, proxy, None, headless=config.CDP_HEADLESS)
                else:
                    self.browser_context = await self.launch_browser(
                        playwright.chromium, proxy, None, headless=config.HEADLESS)
                self.context_page = await self.browser_context.new_page()
                self.context_page.set_default_timeout(config.META_PAGE_TIMEOUT_MS)
                await self._login()
                if config.CRAWLER_TYPE == "search":
                    await self.search()
                elif config.CRAWLER_TYPE == "detail":
                    await self.get_specified_notes()
                else:
                    await self.get_creators_and_notes()
            finally:
                try:
                    await self.close()
                finally:
                    self._store.flush()

    async def _login(self):
        if config.COOKIES:
            cookies = []
            for part in config.COOKIES.split(";"):
                name, sep, value = part.strip().partition("=")
                if sep and name:
                    cookies.append({"name": name, "value": value,
                                    "domain": self.adapter.COOKIE_DOMAIN, "path": "/",
                                    "secure": True})
            await self.browser_context.add_cookies(cookies)
        if config.LOGIN_TYPE == "cookie":
            return  # Public detail pages may work without an authenticated session.
        if not self._attached and ((config.ENABLE_CDP_MODE and config.CDP_HEADLESS)
                                   or (not config.ENABLE_CDP_MODE and config.HEADLESS)):
            raise ValueError("Manual login requires --headless false.")
        await self.context_page.goto(self.adapter.BASE_URL, wait_until="domcontentloaded")
        utils.logger.info("[%s] Sign in in the browser (timeout: %ss).",
                          self.platform, config.META_LOGIN_TIMEOUT_SEC)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + config.META_LOGIN_TIMEOUT_SEC
        while loop.time() < deadline:
            cookies = await self.browser_context.cookies(self.adapter.BASE_URL)
            present = {cookie["name"] for cookie in cookies if cookie.get("value")}
            if set(self.adapter.AUTH_COOKIE_NAMES).issubset(present):
                return
            await asyncio.sleep(1)
        raise MetaCrawlerError("Login timed out. Finish signing in and retry with --lt cookie.")

    async def _navigate(self, url):
        response = await self.context_page.goto(url, wait_until="domcontentloaded",
                                                timeout=config.META_PAGE_TIMEOUT_MS)
        if response is not None and response.status >= 400:
            raise MetaCrawlerError(f"{self.platform} returned HTTP {response.status}.")
        await asyncio.sleep(config.META_SCROLL_WAIT_SEC)
        await self._check_access()

    async def _check_access(self):
        path = urlparse(self.context_page.url).path.lower()
        blocked_paths = ("/login", "/checkpoint", "/challenge", "/accounts/login", "/two_step_verification")
        if any(path == value or path.startswith(value + "/") or path.startswith(value + ".")
               for value in blocked_paths):
            raise MetaCrawlerError("Login or verification is required. Sign in manually and retry.")
        if await self.context_page.locator('input[type="password"]:visible').count():
            raise MetaCrawlerError("A login wall is visible. Retry with --lt manual or valid cookies.")

    async def _scroll(self):
        await self.context_page.evaluate("window.scrollBy(0, Math.max(window.innerHeight, 800))")
        await asyncio.sleep(max(config.META_SCROLL_WAIT_SEC, config.CRAWLER_MAX_SLEEP_SEC))
        await self._check_access()

    async def _collect_posts(self, limit, start_round=1):
        results = {}
        observed = set()
        idle = 0
        for round_number in range(1, config.META_SCROLL_MAX_ROUNDS + 1):
            records = await self.context_page.evaluate(self.adapter.EXTRACT_POSTS_JS)
            new_ids = set()
            for record in records:
                try:
                    url = self.adapter.normalize_post_url(record["content_url"])
                    identity = self.adapter.post_id(url)
                except (ValueError, KeyError, TypeError):
                    continue
                # A skipped scroll batch must not reappear in subsequent batches.
                if identity in observed:
                    continue
                new_ids.add(identity)
                if round_number >= start_round:
                    results[identity] = {**record, "content_id": identity, "content_url": url}
                    if len(results) >= limit:
                        return list(results.values())
            observed.update(new_ids)
            idle = 0 if new_ids else idle + 1
            if idle >= config.META_SCROLL_IDLE_ROUNDS:
                break
            if round_number < config.META_SCROLL_MAX_ROUNDS:
                await self._scroll()
        if not results:
            utils.logger.warning("[%s] No recognizable posts. The page may be empty, restricted, "
                                 "or its layout may have changed.", self.platform)
        return list(results.values())

    async def search(self):
        for keyword in (word.strip() for word in config.KEYWORDS.split(",")):
            if not keyword:
                continue
            source_keyword_var.set(keyword)
            await self._navigate(self.adapter.search_url(keyword))
            records = await self._collect_posts(config.CRAWLER_MAX_NOTES_COUNT, config.START_PAGE)
            await self._save_posts(records)

    async def get_specified_notes(self):
        source_keyword_var.set("")
        for value in self._configured_list("SPECIFIED_ID_LIST")[:config.CRAWLER_MAX_NOTES_COUNT]:
            await self._get_detail(self.adapter.normalize_post_url(value))

    async def get_creators_and_notes(self):
        source_keyword_var.set("")
        for value in self._configured_list("CREATOR_ID_LIST"):
            url = self.adapter.normalize_creator_url(value)
            await self._navigate(url)
            creator = await self.context_page.evaluate(self.adapter.EXTRACT_CREATOR_JS)
            if not creator or not creator.get("user_id"):
                raise MetaCrawlerError("Profile is unavailable or its layout is not recognized.")
            # Profiles can use numeric IDs or names; retain the validated profile URL.
            creator["profile_url"] = url
            await self._store.store_creator(creator)
            records = await self._collect_posts(config.CRAWLER_MAX_NOTES_COUNT, config.START_PAGE)
            await self._save_posts(records)

    async def _save_posts(self, records):
        pending = []
        for record in records:
            if record["content_id"] in self._saved_ids:
                continue
            await self._store.store_content(record)
            self._saved_ids.add(record["content_id"])
            pending.append(record)
        if config.ENABLE_GET_COMMENTS and config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES:
            for record in pending:
                try:
                    await self._get_detail(record["content_url"], save_post=False)
                except MetaCrawlerError as exc:
                    utils.logger.warning("[%s] Post %s saved; comments unavailable: %s",
                                         self.platform, record["content_id"], exc)

    async def _get_detail(self, url, save_post=True):
        await self._navigate(url)
        target = self.adapter.post_id(url)
        record = None
        # Wait for hydration without treating related/suggested posts as the target.
        for _ in range(config.META_SCROLL_IDLE_ROUNDS):
            records = await self.context_page.evaluate(self.adapter.EXTRACT_POSTS_JS)
            for item in records:
                try:
                    item_url = self.adapter.normalize_post_url(item["content_url"])
                    if self.adapter.post_id(item_url) == target:
                        record = {**item, "content_id": target, "content_url": item_url}
                        break
                except (ValueError, KeyError, TypeError):
                    continue
            if record:
                break
            await asyncio.sleep(config.META_SCROLL_WAIT_SEC)
            await self._check_access()
        if not record:
            raise MetaCrawlerError(f"Post {target} is unavailable or its layout is not recognized.")
        if save_post and target not in self._saved_ids:
            await self._store.store_content(record)
            self._saved_ids.add(target)
        if config.ENABLE_GET_COMMENTS:
            await self._get_comments(target, record["content_url"])
        await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)

    async def _get_comments(self, content_id, content_url):
        limit = config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
        if not limit:
            return
        seen = set()
        idle = 0
        # Only expand explicit comment/reply controls, never submit a form or react.
        expand = re.compile(r"^(?:View more comments|View previous comments|View more replies|"
                            r"View replies|See more comments|查看更多留言|查看先前的留言|"
                            r"查看更多回复|查看更多評論|查看回覆)(?:\s*\(?.*\)?)?$", re.I)
        for round_number in range(config.META_SCROLL_MAX_ROUNDS):
            rows = await self.context_page.evaluate(self.adapter.EXTRACT_COMMENTS_JS)
            before = len(seen)
            for item in rows:
                identity = str(item.get("comment_id") or "")
                if not identity or identity == content_id or identity in seen:
                    continue
                if item.get("parent_comment_id") and not config.ENABLE_GET_SUB_COMMENTS:
                    continue
                await self._store.store_comment({**item, "comment_id": identity,
                                                 "content_id": content_id, "content_url": content_url})
                seen.add(identity)
                if len(seen) >= limit:
                    return
            buttons = self.context_page.get_by_role("button", name=expand)
            clicked = False
            for index in range(min(await buttons.count(), 3)):
                button = buttons.nth(index)
                if await button.is_visible():
                    await button.click(timeout=config.META_PAGE_TIMEOUT_MS)
                    clicked = True
                    break
            idle = 0 if len(seen) > before or clicked else idle + 1
            if idle >= config.META_SCROLL_IDLE_ROUNDS:
                break
            if round_number + 1 < config.META_SCROLL_MAX_ROUNDS:
                await self._scroll()

    async def launch_browser(self, chromium: BrowserType, playwright_proxy: Optional[Dict],
                             user_agent: Optional[str], headless: bool = True) -> BrowserContext:
        options = {"headless": headless, "proxy": playwright_proxy}
        context_options = {"viewport": {"width": 1440, "height": 1000}}
        if user_agent:
            context_options["user_agent"] = user_agent
        if config.SAVE_LOGIN_STATE:
            directory = Path.cwd() / "browser_data" / (config.USER_DATA_DIR % self.platform)
            return await chromium.launch_persistent_context(str(directory), **options, **context_options)
        self._browser = await chromium.launch(**options)
        return await self._browser.new_context(**context_options)

    async def launch_browser_with_cdp(self, playwright: Playwright, playwright_proxy: Optional[Dict],
                                      user_agent: Optional[str], headless: bool = True) -> BrowserContext:
        self.cdp_manager = CDPBrowserManager()
        context = await self.cdp_manager.launch_and_connect(
            playwright=playwright, playwright_proxy=playwright_proxy,
            user_agent=user_agent, headless=headless)
        self._attached = config.CDP_CONNECT_EXISTING
        return context

    async def close(self):
        if self.cdp_manager:
            if self._attached:
                # Leave an existing browser's context and unrelated user tabs intact.
                if self.context_page and not self.context_page.is_closed():
                    await self.context_page.close()
                self.cdp_manager.browser_context = None
                self.cdp_manager.browser = None
            else:
                await self.cdp_manager.cleanup()
            self.cdp_manager = None
        elif self.browser_context:
            await self.browser_context.close()
        if self._browser:
            await self._browser.close()
            self._browser = None
        self.browser_context = None
        self.context_page = None
