# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_meta_store.py
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

"""Round-trip tests for the Meta file exporters."""

import csv
import json

import pytest

import config
from store.meta import MetaStore
from var import crawler_type_var, source_keyword_var


@pytest.fixture(autouse=True)
def output_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_PATH", str(tmp_path))
    monkeypatch.setattr(config, "ENABLE_GET_WORDCLOUD", False)
    crawler_token = crawler_type_var.set("detail")
    keyword_token = source_keyword_var.set("測試")
    yield
    crawler_type_var.reset(crawler_token)
    source_keyword_var.reset(keyword_token)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["threads", "facebook"])
@pytest.mark.parametrize("option", ["jsonl", "json", "csv"])
async def test_round_trip_and_stable_columns(tmp_path, monkeypatch, platform, option):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", option)
    store = MetaStore(platform)
    item = {"content_id": "post1", "content": "繁體中文", "media_urls": ["https://example.com/a.jpg"]}
    await store.store_content(item)
    await store.store_content(item)  # one run may encounter a card more than once
    await store.store_content({"content_id": "post2", "liked_count": "1.2K", "new_field": "extra"})
    await store.store_comment({"content_id": "post1", "comment_id": "c1", "content": "reply"})
    await store.store_creator({"user_id": "alice", "nickname": "Alice"})
    path = next((tmp_path / platform / option).glob(f"detail_contents_*.{option}"))
    if option == "csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert rows[1]["liked_count"] == "1.2K"
        assert "extra" in rows[1]["extra_data"]
    else:
        raw = path.read_text()
        rows = [json.loads(line) for line in raw.splitlines()] if option == "jsonl" else json.loads(raw)
        assert rows[0]["media_urls"] == item["media_urls"]
        assert rows[1]["extra_data"] == {"new_field": "extra"}
        assert rows[0]["liked_count"] is None  # unknown does not become a fabricated zero
    assert len(rows) == 2
    assert rows[0]["content"] == "繁體中文"
    assert rows[0]["source_keyword"] == "測試"
    assert rows[0]["platform"] == platform
    assert "platform" not in item  # input owned by the caller remains untouched
    assert len(list((tmp_path / platform / option).glob(f"*.{option}"))) == 3


@pytest.mark.asyncio
async def test_excel_export(tmp_path, monkeypatch):
    import openpyxl
    from store.excel_store_base import ExcelStoreBase

    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "excel")
    ExcelStoreBase._instances.clear()
    try:
        store = MetaStore("threads")
        await store.store_content({"content_id": "first", "content": "文本"})
        await store.store_content({"content_id": "second", "liked_count": "3"})
        await store.store_comment({"content_id": "first", "comment_id": "reply"})
        await store.store_creator({"user_id": "creator"})
        ExcelStoreBase.flush_all()
        filename = next((tmp_path / "threads").glob("*.xlsx"))
        workbook = openpyxl.load_workbook(filename)
        try:
            assert workbook.sheetnames == ["Contents", "Comments", "Creators"]
            contents = list(workbook["Contents"].values)
            headers = list(contents[0])
            assert contents[1][headers.index("content")] == "文本"
            assert contents[2][headers.index("liked_count")] == "3"
            assert contents[2][headers.index("content_id")] == "second"
        finally:
            workbook.close()
    finally:
        ExcelStoreBase._instances.clear()


@pytest.mark.parametrize("option", ["db", "sqlite", "postgres", "mongodb"])
def test_unsupported_storage_fails_before_output(monkeypatch, tmp_path, option):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", option)
    with pytest.raises(ValueError, match="file storage only"):
        MetaStore("facebook")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_comments_need_parent_content_id(monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "jsonl")
    with pytest.raises(ValueError, match="requires content_id"):
        await MetaStore("facebook").store_comment({"comment_id": "one"})
