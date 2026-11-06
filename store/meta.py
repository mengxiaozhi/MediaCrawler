# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/meta.py
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

"""File storage shared by the Threads and Facebook browser crawlers."""

import asyncio
from copy import deepcopy
from typing import Dict

import config
from base.base_crawler import AbstractStore
from tools import utils
from var import crawler_type_var, source_keyword_var


# Keep a fixed column order even when some cards omit optional DOM fields.
_FIELDS = {
    "contents": (
        "content_id", "content_url", "user_id", "nickname", "content",
        "publish_time", "liked_count", "comment_count", "share_count", "media_urls",
    ),
    "comments": (
        "comment_id", "content_id", "content_url", "comment_url", "content",
        "user_id", "nickname", "publish_time", "parent_comment_id", "liked_count",
    ),
    "creators": (
        "user_id", "nickname", "profile_url", "description", "avatar",
    ),
}
_METADATA = ("platform", "source_keyword", "add_ts", "last_modify_ts", "extra_data")


class MetaStore(AbstractStore):
    """Write a stable schema using MediaCrawler's existing file exporters.

    Deduplication applies to this instance/run. Existing files retain the upstream
    exporters' append behavior; database-style upserts are not implied.
    """

    SUPPORTED_OPTIONS = ("json", "jsonl", "csv", "excel")

    def __init__(self, platform: str):
        if platform not in ("threads", "facebook"):
            raise ValueError(f"Unsupported Meta platform: {platform!r}")
        self.platform = platform
        self.option = config.SAVE_DATA_OPTION
        self.validate()
        self._seen: set[tuple] = set()
        self._lock = asyncio.Lock()
        crawler_type = crawler_type_var.get() or config.CRAWLER_TYPE
        if self.option == "excel":
            from store.excel_store_base import ExcelStoreBase

            self.writer = ExcelStoreBase.get_instance(platform, crawler_type)
        else:
            from tools.async_file_writer import AsyncFileWriter

            self.writer = AsyncFileWriter(platform, crawler_type)

    def validate(self) -> None:
        if self.option not in self.SUPPORTED_OPTIONS:
            supported = ", ".join(self.SUPPORTED_OPTIONS)
            raise ValueError(
                f"{self.platform} currently supports file storage only ({supported}); "
                f"got {self.option!r}. Use --save_data_option jsonl."
            )

    def _normalize(self, item: Dict, item_type: str) -> Dict:
        now = utils.get_current_timestamp()
        fields = _FIELDS[item_type]
        record = {field: deepcopy(item.get(field)) for field in fields}
        if item_type == "contents" and record["media_urls"] is None:
            record["media_urls"] = []
        record.update(
            platform=self.platform,
            source_keyword=item.get("source_keyword", source_keyword_var.get()),
            add_ts=item.get("add_ts", now),
            last_modify_ts=now,
            extra_data={
                key: deepcopy(value) for key, value in item.items()
                if key not in fields and key not in _METADATA
            },
        )
        if item.get("extra_data"):
            record["extra_data"].update(deepcopy(item["extra_data"]))
        return record

    async def _store(self, item: Dict, item_type: str) -> None:
        id_field = {
            "contents": "content_id", "comments": "comment_id", "creators": "user_id"
        }[item_type]
        if not item.get(id_field):
            raise ValueError(f"{self.platform} {item_type} record requires {id_field}")
        if item_type == "comments" and not item.get("content_id"):
            raise ValueError(f"{self.platform} comment record requires content_id")
        key = (item_type, str(item.get("content_id", "")), str(item[id_field]))
        # Mark only successful writes as seen; a failed output can safely be retried.
        async with self._lock:
            if key in self._seen:
                return
            record = self._normalize(item, item_type)
            if self.option == "excel":
                method = {
                    "contents": self.writer.store_content,
                    "comments": self.writer.store_comment,
                    "creators": self.writer.store_creator,
                }[item_type]
                await method(record)
            else:
                method = {
                    "json": self.writer.write_single_item_to_json,
                    "jsonl": self.writer.write_to_jsonl,
                    "csv": self.writer.write_to_csv,
                }[self.option]
                await method(item=record, item_type=item_type)
            self._seen.add(key)

    async def store_content(self, content_item: Dict) -> None:
        await self._store(content_item, "contents")

    async def store_comment(self, comment_item: Dict) -> None:
        await self._store(comment_item, "comments")

    async def store_creator(self, creator: Dict) -> None:
        await self._store(creator, "creators")

    def flush(self) -> None:
        """Persist buffered workbooks even if a later page fails."""
        if self.option == "excel":
            self.writer.flush()
