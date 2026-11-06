# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_dcard_core.py
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

"""Bounded Dcard API workflows against httpx fixtures, without live traffic."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio

import config
from media_platform.dcard import core
from media_platform.dcard.client import API_PREFIX, DcardClient, DcardDataError
from media_platform.dcard.core import DcardCrawler
from media_platform.meta import core as meta_core
from media_platform.meta.core import MetaCrawlerError
from var import crawler_type_var, source_keyword_var


@pytest.fixture(autouse=True)
def runtime_options(monkeypatch):
    options = {
        "PLATFORM": "dcard", "CRAWLER_TYPE": "search", "LOGIN_TYPE": "cookie",
        "COOKIES": "", "SAVE_DATA_OPTION": "jsonl", "ENABLE_GET_MEDIA": False,
        "ENABLE_GET_COMMENTS": False, "ENABLE_GET_SUB_COMMENTS": False,
        "ENABLE_GET_WORDCLOUD": False, "CRAWLER_MAX_NOTES_COUNT": 3,
        "CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES": 3, "START_PAGE": 1,
        "DCARD_PAGE_SIZE": 2, "DCARD_MAX_PAGES": 6,
        "DCARD_PAGE_TIMEOUT_MS": 1000, "DCARD_LOGIN_TIMEOUT_SEC": 1,
        "DCARD_SCROLL_MAX_ROUNDS": 5, "DCARD_SCROLL_IDLE_ROUNDS": 2,
        "DCARD_SCROLL_WAIT_SEC": 0, "CRAWLER_MAX_SLEEP_SEC": 0,
        "ENABLE_CDP_MODE": False, "HEADLESS": False, "CDP_HEADLESS": False,
        "ENABLE_IP_PROXY": False, "KEYWORDS": "fixture keyword",
        "DCARD_SPECIFIED_ID_LIST": [], "DCARD_CREATOR_ID_LIST": [],
    }
    for name, value in options.items():
        monkeypatch.setattr(config, name, value)
    crawler_token = crawler_type_var.set("")
    keyword_token = source_keyword_var.set("")
    yield
    crawler_type_var.reset(crawler_token)
    source_keyword_var.reset(keyword_token)


def full_post(identity):
    return {"id": int(identity), "title": f"Title {identity}", "content": f"Complete article {identity}",
            "forumAlias": "tech", "forumName": "科技", "withNickname": False,
            "createdAt": "2026-11-01T12:00:00Z"}


def memory_store():
    return SimpleNamespace(store_content=AsyncMock(), store_comment=AsyncMock(),
                           store_creator=AsyncMock(), flush=MagicMock())


@pytest_asyncio.fixture
async def crawler_factory():
    clients = []

    def factory(handler):
        requests = []

        def wrapped(request):
            requests.append(request)
            payload = handler(request)
            return payload if isinstance(payload, httpx.Response) else httpx.Response(200, json=payload)

        crawler = DcardCrawler()
        crawler.client = DcardClient(transport=httpx.MockTransport(wrapped))
        clients.append(crawler.client)
        crawler._store = memory_store()
        crawler._pause = AsyncMock()
        return crawler, requests

    yield factory
    for client in clients:
        await client.http.aclose()


def saved_content(crawler):
    return [call.args[0] for call in crawler._store.store_content.await_args_list]


@pytest.mark.asyncio
async def test_search_uses_offset_start_page_dedup_and_fetches_full_articles(crawler_factory, monkeypatch):
    monkeypatch.setattr(config, "START_PAGE", 2)

    def handle(request):
        if request.url.path.endswith("/search/posts"):
            page = {"2": [3, 4], "4": [4, 5]}[request.url.params["offset"]]
            return [{"id": identity, "excerpt": "Only a search excerpt"} for identity in page]
        return full_post(request.url.path.rsplit("/", 1)[-1])

    crawler, requests = crawler_factory(handle)
    await crawler.search()
    assert [(item["content_id"], item["content"]) for item in saved_content(crawler)] == [
        ("3", "Complete article 3"), ("4", "Complete article 4"), ("5", "Complete article 5"),
    ]
    searches = [r for r in requests if r.url.path.endswith("/search/posts")]
    assert [r.url.params["offset"] for r in searches] == ["2", "4"]
    assert all(r.url.params["query"] == "fixture keyword" and r.url.params["limit"] == "2" for r in searches)
    assert source_keyword_var.get() == "fixture keyword"


@pytest.mark.asyncio
async def test_search_repeated_page_stops_without_fetching_duplicate_details(crawler_factory, monkeypatch):
    monkeypatch.setattr(config, "CRAWLER_MAX_NOTES_COUNT", 20)

    def handle(request):
        if request.url.path.endswith("/search/posts"):
            return [{"id": 1}, {"id": 2}]
        return full_post(request.url.path.rsplit("/", 1)[-1])

    crawler, requests = crawler_factory(handle)
    await crawler.search()
    assert [item["content_id"] for item in saved_content(crawler)] == ["1", "2"]
    assert len([r for r in requests if r.url.path.endswith("/search/posts")]) == 2
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_search_respects_page_budget_even_when_new_results_continue(crawler_factory, monkeypatch):
    monkeypatch.setattr(config, "DCARD_MAX_PAGES", 2)
    monkeypatch.setattr(config, "CRAWLER_MAX_NOTES_COUNT", 100)

    def handle(request):
        if request.url.path.endswith("/search/posts"):
            offset = int(request.url.params["offset"])
            return [{"id": offset + 1}, {"id": offset + 2}]
        return full_post(request.url.path.rsplit("/", 1)[-1])

    crawler, requests = crawler_factory(handle)
    await crawler.search()
    assert [item["content_id"] for item in saved_content(crawler)] == ["1", "2", "3", "4"]
    assert len([r for r in requests if r.url.path.endswith("/search/posts")]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["hidden", "hiddenByAuthor", "inReview", "404"])
async def test_search_skips_unavailable_articles_without_spending_success_limit(crawler_factory, monkeypatch, unavailable):
    monkeypatch.setattr(config, "CRAWLER_MAX_NOTES_COUNT", 1)

    def handle(request):
        if request.url.path.endswith("/search/posts"):
            return [{"id": 1}, {"id": 2}]
        identity = request.url.path.rsplit("/", 1)[-1]
        if identity == "1":
            return httpx.Response(404) if unavailable == "404" else {**full_post(1), unavailable: True}
        return full_post(identity)

    crawler, _ = crawler_factory(handle)
    await crawler.search()
    assert [item["content_id"] for item in saved_content(crawler)] == ["2"]


@pytest.mark.asyncio
async def test_creator_walks_before_cursor_and_skips_start_pages(crawler_factory, monkeypatch):
    monkeypatch.setattr(config, "START_PAGE", 2)
    monkeypatch.setattr(config, "DCARD_CREATOR_ID_LIST", ["https://www.dcard.tw/@alice"])

    def handle(request):
        if request.url.path == API_PREFIX + "/personas/alice":
            return {"uid": "alice", "nickname": "Alice", "description": "Public bio"}
        if request.url.path.endswith("/personas/alice/posts"):
            ids = {None: [100, 99], "99": [98, 97], "97": [96, 95]}[request.url.params.get("before")]
            return [{"id": identity} for identity in ids]
        return full_post(request.url.path.rsplit("/", 1)[-1])

    crawler, requests = crawler_factory(handle)
    await crawler.get_creators_and_notes()
    creator = crawler._store.store_creator.await_args.args[0]
    assert (creator["user_id"], creator["nickname"]) == ("alice", "Alice")
    assert [item["content_id"] for item in saved_content(crawler)] == ["98", "97", "96"]
    feed_requests = [r for r in requests if r.url.path.endswith("/personas/alice/posts")]
    assert [r.url.params.get("before") for r in feed_requests] == [None, "99", "97"]
    assert all(not r.url.path.endswith(("/posts/100", "/posts/99", "/posts/95")) for r in requests)


@pytest.mark.asyncio
async def test_creator_duplicate_page_stops(crawler_factory, monkeypatch):
    monkeypatch.setattr(config, "CRAWLER_MAX_NOTES_COUNT", 20)
    monkeypatch.setattr(config, "DCARD_CREATOR_ID_LIST", ["alice"])

    def handle(request):
        if request.url.path.endswith("/personas/alice"):
            return {"uid": "alice"}
        if request.url.path.endswith("/personas/alice/posts"):
            return [{"id": 10}, {"id": 9}]
        return full_post(request.url.path.rsplit("/", 1)[-1])

    crawler, requests = crawler_factory(handle)
    await crawler.get_creators_and_notes()
    assert [item["content_id"] for item in saved_content(crawler)] == ["10", "9"]
    assert len([r for r in requests if r.url.path.endswith("/personas/alice/posts")]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("subcomments,expected,after", [
    (False, ["123:B1", "C4", "C6"], ["0", "2", "3", "5"]),
    (True, ["123:B1", "C4", "C5"], ["0", "2", "3"]),
])
async def test_comments_floor_cursor_dedup_hidden_other_post_and_replies(
    crawler_factory, monkeypatch, subcomments, expected, after,
):
    monkeypatch.setattr(config, "ENABLE_GET_SUB_COMMENTS", subcomments)
    first = {"floor": 1, "content": "First comment", "postId": 123}
    pages = {
        "0": [first, {"id": "H2", "floor": 2, "content": "Hidden", "hidden": True}],
        "2": [first, {"id": "OTHER", "floor": 3, "content": "Wrong post", "postId": 999}],
        "3": [{"id": "C4", "floor": 4, "content": "Fourth"},
              {"id": "C5", "floor": 5, "content": "Nested", "parentId": "C4"}],
        "5": [{"id": "C6", "floor": 6, "content": "Sixth"}],
    }
    crawler, requests = crawler_factory(lambda request: pages[request.url.params["after"]])
    await crawler._get_comments("123", "https://www.dcard.tw/p/123")
    saved = [call.args[0] for call in crawler._store.store_comment.await_args_list]
    assert [row["comment_id"] for row in saved] == expected
    assert [r.url.params["after"] for r in requests] == after
    assert all(row["content_id"] == "123" and row["content_url"] == "https://www.dcard.tw/p/123" for row in saved)
    assert requests[-1].url.params["limit"] == ("1" if not subcomments else "2")


@pytest.mark.asyncio
async def test_comment_cursor_that_does_not_advance_stops(crawler_factory, monkeypatch):
    monkeypatch.setattr(config, "DCARD_PAGE_SIZE", 1)
    crawler, requests = crawler_factory(lambda _: [{"id": "C1", "floor": 1, "content": "Repeated"}])
    await crawler._get_comments("123", "https://www.dcard.tw/p/123")
    crawler._store.store_comment.assert_awaited_once()
    assert [r.url.params["after"] for r in requests] == ["0", "1"]


@pytest.mark.asyncio
async def test_required_hidden_detail_is_an_error(crawler_factory):
    crawler, _ = crawler_factory(lambda _: {**full_post(123), "hidden": True})
    with pytest.raises(DcardDataError, match="hidden or unavailable"):
        await crawler._read_post("123", required=True)
    crawler._store.store_content.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 403])
async def test_cookie_start_needs_no_browser_closes_http_and_flushes_on_failure(monkeypatch, status):
    monkeypatch.setattr(config, "CRAWLER_TYPE", "detail")
    monkeypatch.setattr(config, "DCARD_SPECIFIED_ID_LIST", ["123"])
    monkeypatch.setattr(config, "ENABLE_CDP_MODE", True)
    client = DcardClient(transport=httpx.MockTransport(lambda _: httpx.Response(status, json=full_post(123))))
    monkeypatch.setattr(core, "DcardClient", MagicMock(return_value=client))
    crawler = DcardCrawler()
    store = memory_store()
    monkeypatch.setattr(crawler, "_create_store", lambda: store)
    crawler.launch_browser = AsyncMock(side_effect=AssertionError("public API mode opened browser"))
    crawler.launch_browser_with_cdp = AsyncMock(side_effect=AssertionError("public API mode connected browser"))
    if status == 200:
        await crawler.start()
        assert store.store_content.await_args.args[0]["content"] == "Complete article 123"
    else:
        with pytest.raises(DcardDataError, match="valid session"):
            await crawler.start()
        store.store_content.assert_not_awaited()
    crawler.launch_browser.assert_not_awaited()
    crawler.launch_browser_with_cdp.assert_not_awaited()
    assert client.http.is_closed and crawler.client is None
    store.flush.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("page_size,max_pages", [(0, 1), (101, 1), (20, 0)])
async def test_invalid_pagination_fails_before_http_creation(monkeypatch, page_size, max_pages):
    monkeypatch.setattr(config, "DCARD_PAGE_SIZE", page_size)
    monkeypatch.setattr(config, "DCARD_MAX_PAGES", max_pages)
    factory = MagicMock(side_effect=AssertionError("HTTP client opened before validation"))
    monkeypatch.setattr(core, "DcardClient", factory)
    crawler = DcardCrawler()
    monkeypatch.setattr(crawler, "_create_store", memory_store)
    with pytest.raises(ValueError, match="DCARD_PAGE_SIZE"):
        await crawler.start()
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_manual_login_empty_cookie_requirements_still_need_visible_success(monkeypatch):
    monkeypatch.setattr(config, "LOGIN_TYPE", "manual")
    crawler = DcardCrawler()
    crawler.context_page = SimpleNamespace(goto=AsyncMock(), evaluate=AsyncMock(return_value=False))
    crawler.browser_context = SimpleNamespace(cookies=AsyncMock(return_value=[]))
    crawler.client = SimpleNamespace(update_cookies=AsyncMock())
    times = iter([0, 0.1, 2])
    monkeypatch.setattr(meta_core.asyncio, "get_running_loop", lambda: SimpleNamespace(time=lambda: next(times)))
    monkeypatch.setattr(meta_core.asyncio, "sleep", AsyncMock())
    with pytest.raises(MetaCrawlerError, match="Login timed out"):
        await crawler._login()
    crawler.context_page.evaluate.assert_awaited_once_with(crawler.adapter.LOGIN_SUCCESS_JS)
    crawler.client.update_cookies.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_login_copies_browser_session_only_after_success(monkeypatch):
    monkeypatch.setattr(config, "LOGIN_TYPE", "manual")
    crawler = DcardCrawler()
    crawler.context_page = SimpleNamespace(goto=AsyncMock(), evaluate=AsyncMock(return_value=True))
    crawler.browser_context = SimpleNamespace(cookies=AsyncMock(return_value=[]))
    crawler.client = SimpleNamespace(update_cookies=AsyncMock())
    await crawler._login()
    crawler.client.update_cookies.assert_awaited_once_with(crawler.browser_context)
