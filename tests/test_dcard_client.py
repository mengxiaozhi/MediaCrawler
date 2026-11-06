# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_dcard_client.py
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

"""Dcard public API request boundaries and response handling, with no network."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

import config
from media_platform.dcard.client import API_PREFIX, BASE_URL, DcardClient, DcardDataError


@pytest.fixture(autouse=True)
def request_options(monkeypatch):
    monkeypatch.setattr(config, "COOKIES", "")
    monkeypatch.setattr(config, "DCARD_PAGE_TIMEOUT_MS", 2000)


@pytest_asyncio.fixture
async def client_factory():
    clients = []

    def factory(handler):
        client = DcardClient(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [
    ("POST", API_PREFIX + "/posts/123"),
    ("DELETE", API_PREFIX + "/posts/123"),
    ("GET", "https://www.dcard.tw" + API_PREFIX + "/posts/123"),
    ("GET", "//evil.example/service/api/v2/posts/123"),
    ("GET", "/login"),
    ("GET", API_PREFIX),
    ("GET", API_PREFIX + "/../../login"),
    ("GET", API_PREFIX + "/%2e%2e/%2e%2e/login"),
    ("GET", API_PREFIX + "/posts/123?redirect=https://evil.example"),
    ("GET", API_PREFIX + "/posts/123#fragment"),
    ("GET", API_PREFIX + "/posts\\123"),
    ("GET", API_PREFIX + "/posts/123\n"),
])
async def test_rejects_writes_and_paths_outside_api_before_transport(client_factory, method, path):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={})

    client = client_factory(handle)
    with pytest.raises(ValueError, match="relative public API paths"):
        await client.request(method, path)
    assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [
    (401, "valid session"), (403, "valid session"), (302, "valid session"),
    (429, "rate limit"), (404, "HTTP 404"), (500, "HTTP 500"),
])
async def test_http_failures_report_actionable_status(client_factory, status, expected):
    client = client_factory(lambda _: httpx.Response(status, headers={"Location": "/login"}))
    with pytest.raises(DcardDataError, match=expected) as error:
        await client.get_post("123")
    assert error.value.status == status


@pytest.mark.asyncio
@pytest.mark.parametrize("body,expected", [
    ("<html>Browser verification</html>", "non-JSON"),
    ('"unexpected string"', "unexpected response format"),
    ("null", "unexpected response format"),
    ('{"error":"bad"}', "API error"),
    ('{"errorMessage":"bad"}', "API error"),
])
async def test_non_json_primitives_and_api_errors_fail_explicitly(client_factory, body, expected):
    client = client_factory(lambda _: httpx.Response(200, text=body))
    with pytest.raises(DcardDataError, match=expected):
        await client.request("GET", API_PREFIX + "/posts/123")


@pytest.mark.asyncio
async def test_transport_errors_do_not_expose_cookie_values(client_factory, monkeypatch):
    monkeypatch.setattr(config, "COOKIES", "private_session=secret-value")

    def fail(request):
        raise httpx.ConnectError("request contains secret-value", request=request)

    client = client_factory(fail)
    with pytest.raises(DcardDataError, match="ConnectError") as error:
        await client.get_post("123")
    assert "secret-value" not in str(error.value)


@pytest.mark.asyncio
async def test_post_id_and_response_identity_are_verified(client_factory):
    client = client_factory(lambda _: httpx.Response(200, json={"id": 999, "title": "Wrong post"}))
    with pytest.raises(ValueError, match="numeric"):
        await client.get_post("123/../private")
    with pytest.raises(DcardDataError, match="different or unrecognized"):
        await client.get_post("123")


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"id": 1}, [1, 2], [None]])
async def test_list_routes_require_lists_of_records(client_factory, payload):
    client = client_factory(lambda _: httpx.Response(200, json=payload))
    with pytest.raises(DcardDataError, match="list of Dcard records"):
        await client.search_posts("test")


@pytest.mark.asyncio
async def test_endpoint_routes_and_encoded_query_cursors(client_factory):
    requests = []

    def handle(request):
        requests.append(request)
        payload = {"id": 123, "title": "Full post"} if request.url.path.endswith("/posts/123") else []
        if request.url.path.endswith("/personas/alice.name"):
            payload = {"uid": "alice.name", "nickname": "Alice"}
        return httpx.Response(200, json=payload)

    client = client_factory(handle)
    assert (await client.get_post("123"))["title"] == "Full post"
    await client.search_posts("台灣 & Python", offset=60, limit=20)
    await client.get_comments("123", after=12, limit=10)
    await client.get_creator("alice.name")
    await client.get_creator_posts("alice.name", before=456, limit=15)
    assert [(r.method, r.url.host) for r in requests] == [("GET", "www.dcard.tw")] * 5
    assert requests[1].url.path == API_PREFIX + "/search/posts"
    assert dict(requests[1].url.params) == {"query": "台灣 & Python", "offset": "60", "limit": "20"}
    assert dict(requests[2].url.params) == {"after": "12", "limit": "10"}
    assert requests[3].url.path == API_PREFIX + "/personas/alice.name"
    assert dict(requests[4].url.params) == {"before": "456", "limit": "15"}


@pytest.mark.asyncio
async def test_cookie_update_scopes_browser_read_and_replaces_old_session(client_factory, monkeypatch):
    monkeypatch.setattr(config, "COOKIES", "stale=old; ignored; equal=abc==")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=[])

    client = client_factory(handle)
    assert client.http.cookies.get("equal") == "abc=="
    browser_context = SimpleNamespace(cookies=AsyncMock(return_value=[
        {"name": "dcard_session", "value": "new==", "domain": ".dcard.tw", "path": "/"},
        {"name": "foreign", "value": "other-site", "domain": ".other.example", "path": "/"},
    ]))
    await client.update_cookies(browser_context)
    browser_context.cookies.assert_awaited_once_with(BASE_URL)
    await client.search_posts("test")
    cookie_header = requests[0].headers.get("cookie", "")
    assert "dcard_session=new==" in cookie_header
    assert "stale" not in cookie_header and "foreign" not in cookie_header
    assert any(cookie.name == "dcard_session" and cookie.domain == ".dcard.tw" for cookie in client.http.cookies.jar)


@pytest.mark.asyncio
async def test_context_manager_closes_http_client():
    client = DcardClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[])))
    async with client:
        assert not client.http.is_closed
        await client.search_posts("test")
    assert client.http.is_closed
