# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/dcard/client.py
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

"""Read-only access to Dcard's public website API, with optional session cookies."""

from urllib.parse import quote, unquote, urlsplit

import httpx

import config
from base.base_crawler import AbstractApiClient

BASE_URL = "https://www.dcard.tw"
API_PREFIX = "/service/api/v2"


class DcardDataError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class DcardClient(AbstractApiClient):
    def __init__(self, proxy=None, transport=None):
        self.http = httpx.AsyncClient(
            base_url=BASE_URL, proxy=proxy, transport=transport,
            timeout=config.DCARD_PAGE_TIMEOUT_MS / 1000,
            headers={"Accept": "application/json", "Referer": BASE_URL + "/"},
            verify=not config.DISABLE_SSL_VERIFY,
        )
        for part in config.COOKIES.split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name:
                self.http.cookies.set(name, value, domain=".dcard.tw", path="/")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.http.aclose()

    async def request(self, method, url, **kwargs):
        parsed = urlsplit(url)
        decoded = unquote(parsed.path)
        if (method.upper() != "GET" or not url.startswith(API_PREFIX + "/")
                or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
                or any(part in (".", "..") for part in decoded.split("/"))
                or "\\" in decoded or any(ord(char) < 33 for char in url)):
            raise ValueError("DcardClient only reads relative public API paths")
        try:
            response = await self.http.get(url, **kwargs)
        except httpx.RequestError as exc:
            raise DcardDataError(f"Dcard request failed: {type(exc).__name__}") from exc
        if response.status_code == 429:
            raise DcardDataError("Dcard rate limit reached. Wait before retrying.", 429)
        if response.status_code in (401, 403) or response.is_redirect:
            raise DcardDataError("Dcard requires a valid session or browser verification. "
                                 "Retry with --lt manual after signing in.", response.status_code)
        if response.status_code >= 400:
            raise DcardDataError(f"Dcard returned HTTP {response.status_code}.", response.status_code)
        try:
            data = response.json()
        except ValueError as exc:
            raise DcardDataError("Dcard returned a non-JSON page; browser verification may be required.") from exc
        if not isinstance(data, (dict, list)):
            raise DcardDataError("Dcard returned an unexpected response format.")
        if isinstance(data, dict) and ("error" in data or "errorMessage" in data):
            raise DcardDataError("Dcard returned an API error.")
        return data

    async def update_cookies(self, browser_context):
        self.http.cookies.clear()
        for cookie in await browser_context.cookies(BASE_URL):
            self.http.cookies.set(cookie["name"], cookie["value"],
                                  domain=cookie.get("domain", ".dcard.tw"),
                                  path=cookie.get("path", "/"))

    async def _list(self, path, params):
        data = await self.request("GET", API_PREFIX + path, params=params)
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise DcardDataError("Expected a list of Dcard records.")
        return data

    async def get_post(self, identity):
        if not str(identity).isdigit():
            raise ValueError("Dcard post ID must be numeric")
        data = await self.request("GET", API_PREFIX + f"/posts/{identity}")
        if not isinstance(data, dict) or str(data.get("id")) != str(identity):
            raise DcardDataError("Dcard returned a different or unrecognized article.")
        return data

    async def search_posts(self, keyword, offset=0, limit=30):
        return await self._list("/search/posts", {"query": keyword, "offset": offset, "limit": limit})

    async def get_comments(self, identity, after=0, limit=30):
        return await self._list(f"/posts/{identity}/comments", {"after": after, "limit": limit})

    async def get_creator(self, handle):
        data = await self.request("GET", API_PREFIX + "/personas/" + quote(handle, safe=""))
        if not isinstance(data, dict):
            raise DcardDataError("Expected a Dcard public profile.")
        return data

    async def get_creator_posts(self, handle, before=None, limit=30):
        params = {"limit": limit}
        if before is not None:
            params["before"] = before
        return await self._list("/personas/" + quote(handle, safe="") + "/posts", params)


# -*- coding: utf-8 -*-
