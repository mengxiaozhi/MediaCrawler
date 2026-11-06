# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1; see LICENSE.
"""Dcard integration through the CLI, API, subprocess launcher and data browser."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import config
import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from api.routers import data as data_router
from api.schemas import CrawlerStartRequest
from api.services.crawler_manager import CrawlerManager
from cmd_arg import parse_cmd


@pytest.fixture(autouse=True)
def restore_runtime_config():
    original = {key: value for key, value in vars(config).items() if key.isupper()}
    yield
    for key, value in original.items():
        setattr(config, key, value)


@pytest.mark.asyncio
async def test_cli_routes_full_post_urls_ids_and_creator_handles():
    post_url = "https://www.dcard.tw/f/travel/p/255123456-%E5%8F%B0%E7%81%A3"
    await parse_cmd([
        "--platform", "dcard", "--type", "detail", "--lt", "cookie",
        "--specified_id", f"{post_url}\n255123457", "--get_comment", "false",
    ])
    assert config.PLATFORM == "dcard"
    assert config.DCARD_SPECIFIED_ID_LIST == [post_url, "255123457"]
    assert config.ENABLE_GET_COMMENTS is False

    await parse_cmd([
        "--platform", "dcard", "--type", "creator", "--lt", "manual",
        "--creator_id", "@alice\nhttps://www.dcard.tw/@bob/posts",
        "--save_data_option", "csv",
    ])
    assert config.DCARD_CREATOR_ID_LIST == ["@alice", "https://www.dcard.tw/@bob/posts"]
    assert config.LOGIN_TYPE == "manual"
    assert config.SAVE_DATA_OPTION == "csv"


@pytest.mark.parametrize("mode,field,option,value", [
    ("search", "keywords", "--keywords", "台灣旅遊"),
    ("detail", "specified_ids", "--specified_id", "https://www.dcard.tw/f/travel/p/255123456-title"),
    ("creator", "creator_ids", "--creator_id", "https://www.dcard.tw/@alice/posts"),
])
def test_api_preserves_dcard_input_for_subprocess(mode, field, option, value):
    request = CrawlerStartRequest(
        platform="dcard", login_type="cookie", crawler_type=mode,
        save_option="jsonl", **{field: value},
    )
    command = CrawlerManager()._build_command(request)
    assert command[command.index("--platform") + 1] == "dcard"
    assert command[command.index("--type") + 1] == mode
    assert command[command.index(option) + 1] == value


@pytest.mark.parametrize("unsupported", [
    {"save_option": "sqlite"}, {"save_option": "db"},
    {"save_option": "mongodb"}, {"enable_media": True},
    {"login_type": "qrcode"}, {"login_type": "phone"},
])
@pytest.mark.asyncio
async def test_api_rejects_unsupported_dcard_options_before_launch(monkeypatch, unsupported):
    start = AsyncMock(return_value=True)
    monkeypatch.setattr("api.routers.crawler.crawler_manager.start", start)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/crawler/start", json={
            "platform": "dcard", "login_type": "cookie", **unsupported,
        })
    assert response.status_code == 422
    start.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("save_option,enable_media,reason", [
    ("sqlite", False, "file storage only"),
    ("jsonl", True, "media download is not supported"),
])
async def test_cli_preflight_prevents_unsupported_output_side_effects(
    monkeypatch, save_option, enable_media, reason,
):
    import main

    monkeypatch.setattr(config, "PLATFORM", "dcard")
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", save_option)
    monkeypatch.setattr(config, "ENABLE_GET_MEDIA", enable_media)
    monkeypatch.setattr(main.cmd_arg, "parse_cmd", AsyncMock(return_value=SimpleNamespace(init_db=None)))
    init_db = AsyncMock()
    monkeypatch.setattr(main.db, "init_db", init_db)
    with pytest.raises(ValueError, match=reason):
        await main.main()
    init_db.assert_not_called()


def test_factory_builds_dcard_crawler():
    from main import CrawlerFactory
    from media_platform.dcard import DcardCrawler

    assert isinstance(CrawlerFactory.create_crawler("dcard"), DcardCrawler)


@pytest.mark.asyncio
async def test_api_platform_metadata_includes_dcard():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/config/platforms")
    assert response.status_code == 200
    platforms = response.json()["platforms"]
    assert any(item["value"] == "dcard" and item["label"] == "Dcard" for item in platforms)


@pytest.mark.asyncio
async def test_dcard_jsonl_output_appears_in_platform_data_browser(monkeypatch, tmp_path):
    output = tmp_path / "dcard" / "jsonl" / "detail_contents.jsonl"
    output.parent.mkdir(parents=True)
    output.write_text('{"content_id":"255123456"}\n', encoding="utf-8")
    monkeypatch.setattr(data_router, "DATA_DIR", tmp_path)

    listing = await data_router.list_data_files(platform="dcard")
    assert len(listing["files"]) == 1
    assert listing["files"][0]["record_count"] == 1
    preview = await data_router.get_file_content(str(output.relative_to(tmp_path)), limit=1)
    assert preview == {"data": [{"content_id": "255123456"}], "total": 1}
    stats = await data_router.get_data_stats()
    assert stats["by_platform"] == {"dcard": 1}
