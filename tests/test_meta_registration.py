# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1; see LICENSE.
"""Exercise the new platforms through the CLI, API, and output browser."""

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
@pytest.mark.parametrize("platform", ["threads", "facebook"])
async def test_cli_routes_detail_and_creator_inputs(platform):
    post_url = (
        "https://www.threads.com/@alice/post/ABC123"
        if platform == "threads"
        else "https://www.facebook.com/alice/posts/123456"
    )
    await parse_cmd([
        "--platform", platform, "--type", "detail", "--lt", "cookie",
        "--specified_id", post_url, "--get_comment", "false",
    ])
    assert config.PLATFORM == platform
    assert getattr(config, f"{platform.upper()}_SPECIFIED_ID_LIST") == [post_url]
    assert config.ENABLE_GET_COMMENTS is False

    await parse_cmd([
        "--platform", platform, "--type", "creator", "--lt", "manual",
        "--creator_id", "alice\nbob", "--save_data_option", "csv",
    ])
    assert getattr(config, f"{platform.upper()}_CREATOR_ID_LIST") == ["alice", "bob"]
    assert config.LOGIN_TYPE == "manual"
    assert config.SAVE_DATA_OPTION == "csv"


@pytest.mark.parametrize("platform", ["threads", "facebook"])
def test_api_forwards_new_platform_and_full_url_to_subprocess(platform):
    post_url = "https://www.facebook.com/story.php?story_fbid=123&id=456"
    request = CrawlerStartRequest(
        platform=platform, login_type="cookie", crawler_type="detail",
        specified_ids=post_url, save_option="jsonl",
    )
    command = CrawlerManager()._build_command(request)
    assert command[command.index("--platform") + 1] == platform
    assert command[command.index("--specified_id") + 1] == post_url
    assert command[command.index("--lt") + 1] == "cookie"


@pytest.mark.parametrize("platform", ["threads", "facebook"])
@pytest.mark.parametrize("unsupported", [
    {"save_option": "sqlite"}, {"save_option": "db"},
    {"save_option": "mongodb"}, {"enable_media": True},
    {"login_type": "qrcode"},
])
@pytest.mark.asyncio
async def test_api_rejects_unsupported_meta_options_before_start(monkeypatch, platform, unsupported):
    start = AsyncMock(return_value=True)
    monkeypatch.setattr("api.routers.crawler.crawler_manager.start", start)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/crawler/start", json={
            "platform": platform, "login_type": "cookie", **unsupported,
        })
    assert response.status_code == 422
    start.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["threads", "facebook"])
async def test_cli_rejects_unsupported_storage_before_database_init(monkeypatch, platform):
    import main

    monkeypatch.setattr(config, "PLATFORM", platform)
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "sqlite")
    monkeypatch.setattr(main.cmd_arg, "parse_cmd", AsyncMock(return_value=SimpleNamespace(init_db=None)))
    init_db = AsyncMock()
    monkeypatch.setattr(main.db, "init_db", init_db)
    with pytest.raises(ValueError, match="file storage only"):
        await main.main()
    init_db.assert_not_called()


@pytest.mark.asyncio
async def test_api_platform_metadata_lists_new_platforms():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/config/platforms")
    assert response.status_code == 200
    values = {item["value"] for item in response.json()["platforms"]}
    assert {"threads", "facebook"} <= values


@pytest.mark.asyncio
async def test_jsonl_outputs_are_listed_previewed_and_counted(monkeypatch, tmp_path):
    output = tmp_path / "threads" / "jsonl" / "search_contents.jsonl"
    output.parent.mkdir(parents=True)
    output.write_text('{"content_id":"1"}\n\n{"content_id":"2"}\n', encoding="utf-8")
    monkeypatch.setattr(data_router, "DATA_DIR", tmp_path)

    listing = await data_router.list_data_files(platform="threads")
    assert len(listing["files"]) == 1
    assert listing["files"][0]["record_count"] == 2
    preview = await data_router.get_file_content(str(output.relative_to(tmp_path)), limit=1)
    assert preview == {"data": [{"content_id": "1"}], "total": 2}
    stats = await data_router.get_data_stats()
    assert stats["by_platform"] == {"threads": 1}
    assert stats["by_type"] == {"jsonl": 1}
