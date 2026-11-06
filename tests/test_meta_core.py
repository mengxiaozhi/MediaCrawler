# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_meta_core.py
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

"""Behavior checks for bounded Meta crawling and browser/session ownership."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import config
from media_platform.meta import core
from media_platform.meta.core import MetaCrawler, MetaCrawlerError
from media_platform.threads import adapter
from var import crawler_type_var, source_keyword_var


@pytest.fixture(autouse=True)
def runtime_options(monkeypatch):
    options = {
        "PLATFORM": "threads", "CRAWLER_TYPE": "search", "LOGIN_TYPE": "cookie",
        "COOKIES": "", "SAVE_DATA_OPTION": "jsonl", "ENABLE_GET_MEDIA": False,
        "ENABLE_GET_COMMENTS": True, "ENABLE_GET_SUB_COMMENTS": False,
        "CRAWLER_MAX_NOTES_COUNT": 2, "CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES": 2,
        "START_PAGE": 1, "META_SCROLL_MAX_ROUNDS": 5, "META_SCROLL_IDLE_ROUNDS": 2,
        "META_SCROLL_WAIT_SEC": 0, "CRAWLER_MAX_SLEEP_SEC": 0,
        "META_PAGE_TIMEOUT_MS": 1000, "META_LOGIN_TIMEOUT_SEC": 1,
        "ENABLE_CDP_MODE": False, "HEADLESS": False, "CDP_HEADLESS": False,
        "ENABLE_IP_PROXY": False, "KEYWORDS": "test",
    }
    for name, value in options.items():
        monkeypatch.setattr(config, name, value)
    crawler_token = crawler_type_var.set("")
    keyword_token = source_keyword_var.set("")
    yield
    crawler_type_var.reset(crawler_token)
    source_keyword_var.reset(keyword_token)


def post(identity):
    return {"content_id": identity, "content_url": f"https://www.threads.com/@alice/post/{identity}",
            "content": f"Post {identity}"}


@pytest.fixture
def crawler():
    value = MetaCrawler(adapter)
    value.context_page = SimpleNamespace(evaluate=AsyncMock())
    value._scroll = AsyncMock()
    value._navigate = AsyncMock()
    value._check_access = AsyncMock()
    value._store = SimpleNamespace(store_content=AsyncMock(), store_comment=AsyncMock(),
                                   store_creator=AsyncMock(), flush=MagicMock())
    return value


@pytest.mark.asyncio
async def test_skipped_scroll_batch_does_not_reappear_and_count_is_bounded(crawler):
    crawler.context_page.evaluate.side_effect = [
        [post("A"), post("A")], [post("A"), post("B")],
        [post("B"), post("C"), post("D")],
    ]
    records = await crawler._collect_posts(limit=2, start_round=2)
    assert [item["content_id"] for item in records] == ["B", "C"]
    assert crawler._scroll.await_count == 2


@pytest.mark.asyncio
async def test_repeating_feed_stops_after_idle_budget(crawler):
    crawler.context_page.evaluate.return_value = [post("A")]
    records = await crawler._collect_posts(limit=10)
    assert [item["content_id"] for item in records] == ["A"]
    assert crawler.context_page.evaluate.await_count == 3
    assert crawler._scroll.await_count == 2


@pytest.mark.asyncio
async def test_detail_never_substitutes_a_suggested_post_for_target(crawler):
    crawler.context_page.evaluate.return_value = [post("UNRELATED")]
    crawler._get_comments = AsyncMock()
    with pytest.raises(MetaCrawlerError, match="Post TARGET is unavailable"):
        await crawler._get_detail(post("TARGET")["content_url"])
    crawler._store.store_content.assert_not_awaited()
    crawler._get_comments.assert_not_awaited()


@pytest.mark.asyncio
async def test_detail_saves_requested_post_and_respects_comments_disabled(crawler, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", False)
    crawler.context_page.evaluate.return_value = [post("SUGGESTED"), post("TARGET")]
    crawler._get_comments = AsyncMock()
    await crawler._get_detail(post("TARGET")["content_url"])
    assert crawler._store.store_content.await_args.args[0]["content_id"] == "TARGET"
    crawler._get_comments.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,limit", [(False, 2), (True, 0)])
async def test_feed_skips_comment_navigation_when_disabled_or_limit_zero(crawler, monkeypatch, enabled, limit):
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", enabled)
    monkeypatch.setattr(config, "CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES", limit)
    crawler._get_detail = AsyncMock()
    await crawler._save_posts([post("A"), post("A")])
    crawler._store.store_content.assert_awaited_once()
    crawler._get_detail.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("subcomments,expected", [(False, ["C1", "C2"]), (True, ["C1", "R1"])])
async def test_comment_limit_deduplication_and_reply_filter(crawler, monkeypatch, subcomments, expected):
    monkeypatch.setattr(config, "ENABLE_GET_SUB_COMMENTS", subcomments)
    crawler.context_page.get_by_role = MagicMock(return_value=SimpleNamespace(count=AsyncMock(return_value=0)))
    top = {"comment_id": "C1", "content": "first", "parent_comment_id": ""}
    reply = {"comment_id": "R1", "content": "nested", "parent_comment_id": "C1"}
    second = {"comment_id": "C2", "content": "second", "parent_comment_id": ""}
    crawler.context_page.evaluate.side_effect = [[top, reply], [top, reply, second, {"comment_id": "C3"}]]
    await crawler._get_comments("POST", post("POST")["content_url"])
    saved = [call.args[0] for call in crawler._store.store_comment.await_args_list]
    assert [item["comment_id"] for item in saved] == expected
    assert all(item["content_id"] == "POST" for item in saved)


@pytest.mark.asyncio
async def test_cookie_values_keep_equals_signs(crawler, monkeypatch):
    monkeypatch.setattr(config, "COOKIES", "sessionid=abc==; broken; csrftoken=xyz=123")
    crawler.browser_context = SimpleNamespace(add_cookies=AsyncMock())
    await crawler._login()
    cookies = crawler.browser_context.add_cookies.await_args.args[0]
    assert [(item["name"], item["value"]) for item in cookies] == [
        ("sessionid", "abc=="), ("csrftoken", "xyz=123"),
    ]
    assert all(item["domain"] == ".threads.com" for item in cookies)


@pytest.mark.asyncio
async def test_manual_login_stops_at_timeout(crawler, monkeypatch):
    monkeypatch.setattr(config, "LOGIN_TYPE", "manual")
    times = iter([0, 0.1, 2])
    fake_loop = SimpleNamespace(time=lambda: next(times))
    monkeypatch.setattr(core.asyncio, "get_running_loop", lambda: fake_loop)
    sleep = AsyncMock()
    monkeypatch.setattr(core.asyncio, "sleep", sleep)
    crawler.context_page.goto = AsyncMock()
    crawler.browser_context = SimpleNamespace(cookies=AsyncMock(return_value=[]))
    with pytest.raises(MetaCrawlerError, match="Login timed out"):
        await crawler._login()
    crawler.browser_context.cookies.assert_awaited_once_with(adapter.BASE_URL)
    sleep.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_manual_login_accepts_existing_authenticated_session(crawler, monkeypatch):
    monkeypatch.setattr(config, "LOGIN_TYPE", "manual")
    crawler.context_page.goto = AsyncMock()
    crawler.browser_context = SimpleNamespace(cookies=AsyncMock(return_value=[{"name": "sessionid", "value": "valid"}]))
    await crawler._login()
    crawler.browser_context.cookies.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_attached_browser_only_closes_owned_tab(crawler):
    page = SimpleNamespace(is_closed=lambda: False, close=AsyncMock())
    context = SimpleNamespace(close=AsyncMock())
    browser = SimpleNamespace(close=AsyncMock())
    manager = SimpleNamespace(browser_context=context, browser=browser, cleanup=AsyncMock())
    crawler.context_page = page
    crawler.browser_context = context
    crawler.cdp_manager = manager
    crawler._attached = True
    await crawler.close()
    page.close.assert_awaited_once()
    context.close.assert_not_awaited()
    browser.close.assert_not_awaited()
    manager.cleanup.assert_not_awaited()
    assert manager.browser_context is None and manager.browser is None
    assert crawler.context_page is None and crawler.browser_context is None


@pytest.mark.asyncio
async def test_start_closes_context_if_new_page_creation_fails(crawler, monkeypatch):
    playwright = SimpleNamespace(chromium=object())
    runtime = MagicMock()
    runtime.__aenter__ = AsyncMock(return_value=playwright)
    runtime.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(core, "async_playwright", lambda: runtime)
    crawler._validate = MagicMock()
    context = SimpleNamespace(new_page=AsyncMock(side_effect=RuntimeError("page failed")), close=AsyncMock())
    crawler.launch_browser = AsyncMock(return_value=context)
    with pytest.raises(RuntimeError, match="page failed"):
        await crawler.start()
    context.close.assert_awaited_once()
    crawler._store.flush.assert_called_once()
    assert crawler.browser_context is None


@pytest.mark.asyncio
async def test_unrecognized_profile_does_not_invent_creator_record(crawler, monkeypatch):
    monkeypatch.setattr(config, "THREADS_CREATOR_ID_LIST", ["alice"])
    crawler.context_page.evaluate.return_value = {}
    with pytest.raises(MetaCrawlerError, match="Profile is unavailable"):
        await crawler.get_creators_and_notes()
    crawler._store.store_creator.assert_not_awaited()
    crawler._store.store_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_feed_posts_saved_before_detail_and_failed_comments_do_not_abort(crawler):
    events = []

    async def save(record):
        events.append(("save", record["content_id"]))

    async def detail(url, save_post=True):
        identity = adapter.post_id(url)
        events.append(("detail", identity))
        assert save_post is False
        if identity == "A":
            raise MetaCrawlerError("Comments unavailable")

    crawler._store.store_content.side_effect = save
    crawler._get_detail = AsyncMock(side_effect=detail)
    await crawler._save_posts([post("A"), post("B")])
    assert events == [("save", "A"), ("save", "B"), ("detail", "A"), ("detail", "B")]
