# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_dcard_store.py
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

"""Round-trip Dcard-specific columns through the shared file exporters."""

import csv
import json
from unittest.mock import AsyncMock

import pytest

import config
from store.dcard import DcardStore
from store.meta import MetaStore
from var import crawler_type_var, source_keyword_var


@pytest.fixture(autouse=True)
def output_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_PATH", str(tmp_path))
    monkeypatch.setattr(config, "ENABLE_GET_WORDCLOUD", False)
    crawler_token = crawler_type_var.set("detail")
    keyword_token = source_keyword_var.set("台灣")
    yield
    crawler_type_var.reset(crawler_token)
    source_keyword_var.reset(keyword_token)


@pytest.mark.asyncio
@pytest.mark.parametrize("option", ["jsonl", "json", "csv"])
async def test_dcard_round_trip_metadata_columns_and_anonymous_authors(tmp_path, monkeypatch, option):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", option)
    store = DcardStore()
    post = {
        "content_id": "237894561", "content": "分享文章", "title": "繁體中文標題",
        "forum_name": "旅遊", "forum_alias": "travel", "custom": {"tag": "照片"},
    }
    await store.store_content(post)
    await store.store_content(post)
    await store.store_content({"content_id": "237894562", "title": "沒有看板資訊"})
    # Anonymous authors remain unknown; separate posts can each contain floor B1.
    for post_id in ("237894561", "237894562"):
        await store.store_comment({"content_id": post_id, "comment_id": "floor:1", "floor": 1, "content": "匿名留言"})
    await store.store_creator({"user_id": "traveler", "nickname": "旅人"})
    output = tmp_path / "dcard" / option

    def read_rows(item_type):
        filename = next(output.glob(f"detail_{item_type}_*.{option}"))
        if option == "csv":
            with filename.open(encoding="utf-8-sig", newline="") as stream:
                return list(csv.DictReader(stream))
        raw = filename.read_text()
        return [json.loads(line) for line in raw.splitlines()] if option == "jsonl" else json.loads(raw)

    articles = read_rows("contents")
    assert len(articles) == 2
    assert articles[0]["title"] == "繁體中文標題"
    assert articles[0]["forum_name"] == "旅遊"
    assert articles[0]["forum_alias"] == "travel"
    assert articles[0]["source_keyword"] == "台灣"
    assert articles[0]["platform"] == "dcard"
    assert "tag" in str(articles[0]["extra_data"])
    assert "platform" not in post
    assert set(articles[0]) == set(articles[1])
    comments = read_rows("comments")
    assert len(comments) == 2
    assert str(comments[0]["floor"]) == "1"
    assert comments[0]["user_id"] == ("" if option == "csv" else None)
    assert read_rows("creators")[0]["user_id"] == "traveler"


@pytest.mark.asyncio
async def test_dcard_excel_flush_keeps_specific_columns(tmp_path, monkeypatch):
    import openpyxl
    from store.excel_store_base import ExcelStoreBase

    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "excel")
    ExcelStoreBase._instances.clear()
    try:
        store = DcardStore()
        await store.store_content({"content_id": "123", "title": "文章", "forum_name": "心情", "forum_alias": "mood"})
        await store.store_comment({"content_id": "123", "comment_id": "123:5", "floor": 5})
        store.flush()
        filename = next((tmp_path / "dcard").glob("*.xlsx"))
        workbook = openpyxl.load_workbook(filename)
        try:
            posts = list(workbook["Contents"].values)
            headers = list(posts[0])
            assert posts[1][headers.index("title")] == "文章"
            assert posts[1][headers.index("forum_alias")] == "mood"
            comments = list(workbook["Comments"].values)
            assert comments[1][list(comments[0]).index("floor")] == 5
        finally:
            workbook.close()
    finally:
        ExcelStoreBase._instances.clear()


@pytest.mark.parametrize("option", ["db", "sqlite", "postgres", "mongodb"])
def test_dcard_rejects_unsupported_storage_without_files(monkeypatch, tmp_path, option):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", option)
    with pytest.raises(ValueError, match="file storage only"):
        DcardStore()
    assert not list(tmp_path.iterdir())


def test_platform_specific_stores_keep_platform_validation(monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "jsonl")
    with pytest.raises(ValueError, match="Unsupported Dcard platform"):
        DcardStore("threads")
    with pytest.raises(ValueError, match="Unsupported Meta platform"):
        MetaStore("dcard")


@pytest.mark.asyncio
async def test_failed_write_can_be_retried(monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "jsonl")
    store = DcardStore()
    store.writer.write_to_jsonl = AsyncMock(side_effect=[OSError("disk full"), None])
    article = {"content_id": "123", "title": "retry"}
    with pytest.raises(OSError, match="disk full"):
        await store.store_content(article)
    await store.store_content(article)
    await store.store_content(article)
    assert store.writer.write_to_jsonl.await_count == 2
