# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/dcard/core.py
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

"""Dcard public article collection with bounded API pagination."""

import asyncio
from urllib.parse import urlsplit

import config
from media_platform.meta.core import MetaCrawler
from store.dcard import DcardStore
from tools import utils
from var import crawler_type_var, source_keyword_var

from . import adapter
from .client import DcardClient, DcardDataError


class DcardCrawler(MetaCrawler):
    def __init__(self):
        super().__init__(adapter)
        self.client = None

    def _create_store(self):
        return DcardStore()

    def _validate(self):
        super()._validate()
        if not 1 <= config.DCARD_PAGE_SIZE <= 100 or config.DCARD_MAX_PAGES < 1:
            raise ValueError("DCARD_PAGE_SIZE must be 1..100 and DCARD_MAX_PAGES must be positive.")

    async def start(self):
        # Public reading needs no browser or credentials. Manual mode can import
        # the user's browser session without saving any credentials in source.
        crawler_type_var.set(config.CRAWLER_TYPE)
        source_keyword_var.set("")
        self._validate()
        proxy = None
        if config.ENABLE_IP_PROXY:
            from proxy.proxy_ip_pool import create_ip_pool
            pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            _, proxy = utils.format_proxy_info(await pool.get_proxy())
        try:
            async with DcardClient(proxy=proxy) as self.client:
                if config.LOGIN_TYPE == "manual":
                    await super().start()
                elif config.CRAWLER_TYPE == "search":
                    await self.search()
                elif config.CRAWLER_TYPE == "detail":
                    await self.get_specified_notes()
                else:
                    await self.get_creators_and_notes()
        finally:
            self._store.flush()
            self.client = None

    async def _login(self):
        await super()._login()
        await self.client.update_cookies(self.browser_context)

    async def _pause(self):
        await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)

    async def search(self):
        size = config.DCARD_PAGE_SIZE
        for keyword in (word.strip() for word in config.KEYWORDS.split(",")):
            if not keyword:
                continue
            source_keyword_var.set(keyword)
            offset = (config.START_PAGE - 1) * size
            count = 0
            seen = set()
            for _ in range(config.DCARD_MAX_PAGES):
                rows = await self.client.search_posts(keyword, offset=offset, limit=size)
                fresh = [row for row in rows if row.get("id") and str(row["id"]) not in seen]
                if not fresh:
                    break
                for row in fresh:
                    identity = str(row["id"])
                    if identity in seen:
                        continue
                    seen.add(identity)
                    if await self._read_post(identity):
                        count += 1
                    if count >= config.CRAWLER_MAX_NOTES_COUNT:
                        break
                if count >= config.CRAWLER_MAX_NOTES_COUNT or len(rows) < size:
                    break
                offset += len(rows)
                await self._pause()
            if not count:
                utils.logger.warning("[dcard] No accessible articles for this keyword.")

    async def get_specified_notes(self):
        source_keyword_var.set("")
        for value in self._configured_list("SPECIFIED_ID_LIST")[:config.CRAWLER_MAX_NOTES_COUNT]:
            await self._read_post(adapter.post_id(value), required=True)

    async def get_creators_and_notes(self):
        source_keyword_var.set("")
        for value in self._configured_list("CREATOR_ID_LIST"):
            url = adapter.normalize_creator_url(value)
            handle = urlsplit(url).path.lstrip("/@")
            raw = await self.client.get_creator(handle)
            creator = adapter.normalize_creator(raw, handle)
            await self._store.store_creator(creator)
            before = None
            seen = set()
            count = 0
            for page in range(1, config.DCARD_MAX_PAGES + 1):
                rows = await self.client.get_creator_posts(handle, before=before, limit=config.DCARD_PAGE_SIZE)
                fresh = [row for row in rows if row.get("id") and str(row["id"]) not in seen]
                if not fresh:
                    break
                for row in fresh:
                    identity = str(row["id"])
                    if identity in seen:
                        continue
                    seen.add(identity)
                    if page >= config.START_PAGE and await self._read_post(identity):
                        count += 1
                    if count >= config.CRAWLER_MAX_NOTES_COUNT:
                        break
                if count >= config.CRAWLER_MAX_NOTES_COUNT or len(rows) < config.DCARD_PAGE_SIZE:
                    break
                ids = [int(row["id"]) for row in rows if str(row.get("id", "")).isdigit()]
                cursor = min(ids) if ids else None
                if cursor is None or before is not None and cursor >= before:
                    break
                before = cursor
                await self._pause()

    async def _read_post(self, identity, required=False):
        if identity in self._saved_ids:
            return False
        await self._pause()
        try:
            raw = await self.client.get_post(identity)
        except DcardDataError as exc:
            if required or exc.status not in (404, 410):
                raise
            utils.logger.warning("[dcard] Article %s is unavailable.", identity)
            return False
        if any(raw.get(key) for key in ("hidden", "hiddenByAuthor", "inReview")):
            if required:
                raise DcardDataError("The Dcard article is hidden or unavailable.")
            return False
        record = adapter.normalize_post(raw)
        await self._store.store_content(record)
        self._saved_ids.add(identity)
        if config.ENABLE_GET_COMMENTS and config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES:
            await self._get_comments(identity, record["content_url"])
        return True

    async def _get_comments(self, content_id, content_url):
        limit = config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
        after = 0
        seen = set()
        for _ in range(config.DCARD_MAX_PAGES):
            size = min(config.DCARD_PAGE_SIZE, limit - len(seen))
            if size <= 0:
                return
            await self._pause()
            rows = await self.client.get_comments(content_id, after=after, limit=size)
            if not rows:
                return
            for raw in rows:
                item = adapter.normalize_comment(raw, content_id)
                if not item or item["comment_id"] in seen:
                    continue
                if item.get("parent_comment_id") and not config.ENABLE_GET_SUB_COMMENTS:
                    continue
                await self._store.store_comment({**item, "content_url": content_url})
                seen.add(item["comment_id"])
                if len(seen) >= limit:
                    return
            floors = [row["floor"] for row in rows if isinstance(row.get("floor"), int)]
            cursor = max(floors, default=after)
            if len(rows) < size or cursor <= after:
                return
            after = cursor


# -*- coding: utf-8 -*-
