# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_meta_e2e.py
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

"""Real browser lifecycle and file export against locally fulfilled page fixtures.

The fixture covers the integration, not the current live Meta site layout or
authentication. Every browser request is intercepted; no platform is contacted.
"""

import json
import re
import shutil
from urllib.parse import urlsplit

import pytest

import config
from media_platform.facebook import FacebookCrawler
from media_platform.threads import ThreadsCrawler
from var import crawler_type_var, source_keyword_var


THREADS_POST = "https://www.threads.com/@alice/post/POST1"
FACEBOOK_POST = "https://www.facebook.com/alice/posts/123"

THREADS_HTML = """
<link rel="canonical" href="https://www.threads.com/@alice/post/POST1">
<article>
  <a href="/@alice">Alice</a>
  <a href="/@alice/post/POST1"><time datetime="2026-11-01T12:00:00Z">2h</time></a>
  <div data-testid="post-text">Fixture original post</div>
</article>
"""
THREADS_COMMENTS = """
<section aria-label="Replies">
  <article>
    <a href="/@bob">Bob</a>
    <a href="/@bob/post/COMMENT1"><time datetime="2026-11-01T13:00:00Z">1h</time></a>
    <div data-testid="post-text">Fixture reply</div>
  </article>
</section>
<section aria-label="Suggested posts">
  <article>
    <a href="/@eve">Eve</a><a href="/@eve/post/UNRELATED">Suggested</a>
    <div data-testid="post-text">Unrelated suggestion</div>
  </article>
</section>
"""
FACEBOOK_HTML = """
<article role="article">
  <h2><a href="/alice">Alice</a></h2>
  <a href="/alice/posts/123"><time datetime="2026-11-01T12:00:00Z">2h</time></a>
  <div data-ad-preview="message">Fixture original post</div>
</article>
"""
FACEBOOK_COMMENTS = """
<article role="article">
  <h3><a href="/bob">Bob</a></h3>
  <a href="/alice/posts/123?comment_id=456">1h</a>
  <div data-testid="comment_message">Fixture reply</div>
</article>
<article role="article">
  <h3><a href="/eve">Eve</a></h3>
  <a href="/eve/posts/999?comment_id=789">1h</a>
  <div data-testid="comment_message">Unrelated suggestion</div>
</article>
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("platform,crawler_class,post_url,identity,comment_identity,html,comments", [
    ("threads", ThreadsCrawler, THREADS_POST, "POST1", "COMMENT1", THREADS_HTML, THREADS_COMMENTS),
    ("facebook", FacebookCrawler, FACEBOOK_POST, "123", "456", FACEBOOK_HTML, FACEBOOK_COMMENTS),
])
@pytest.mark.parametrize("mode", ["detail", "search", "creator"])
async def test_browser_start_extracts_exports_and_closes(
    monkeypatch, tmp_path, platform, crawler_class, post_url,
    identity, comment_identity, html, comments, mode,
):
    profile_url = "https://www.threads.com/@alice" if platform == "threads" else "https://www.facebook.com/alice"
    options = {
        "PLATFORM": platform, "CRAWLER_TYPE": mode, "LOGIN_TYPE": "cookie",
        "COOKIES": "", "SAVE_DATA_OPTION": "jsonl", "SAVE_DATA_PATH": str(tmp_path),
        "ENABLE_GET_MEDIA": False, "ENABLE_GET_COMMENTS": True,
        "ENABLE_GET_SUB_COMMENTS": False, "ENABLE_GET_WORDCLOUD": False,
        "CRAWLER_MAX_NOTES_COUNT": 1, "CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES": 1,
        "START_PAGE": 1, "META_SCROLL_MAX_ROUNDS": 3, "META_SCROLL_IDLE_ROUNDS": 2,
        "META_SCROLL_WAIT_SEC": 0, "CRAWLER_MAX_SLEEP_SEC": 0,
        "META_PAGE_TIMEOUT_MS": 5000, "META_LOGIN_TIMEOUT_SEC": 1,
        "ENABLE_CDP_MODE": False, "HEADLESS": True, "ENABLE_IP_PROXY": False,
        "SAVE_LOGIN_STATE": False, "KEYWORDS": "fixture keyword",
        f"{platform.upper()}_SPECIFIED_ID_LIST": [post_url],
        f"{platform.upper()}_CREATOR_ID_LIST": ["alice"],
    }
    for name, value in options.items():
        monkeypatch.setattr(config, name, value)
    crawler_token = crawler_type_var.set("stale_previous_run")
    keyword_token = source_keyword_var.set("stale_previous_keyword")
    requested_urls = []
    closed = []
    crawler = crawler_class()

    async def launch_local_fixture(chromium, playwright_proxy, user_agent, headless=True):
        crawler._browser = await chromium.launch(
            headless=True, executable_path=shutil.which("chromium") or shutil.which("google-chrome"),
        )
        context = await crawler._browser.new_context()
        context.on("close", lambda _: closed.append(True))

        async def handle(route):
            requested_urls.append(route.request.url)
            page_html = html if "/search" in urlsplit(route.request.url).path else html + comments
            if route.request.url == profile_url:
                page_html = (f'<link rel="canonical" href="{profile_url}"><h1>Alice</h1>'
                             '<meta property="og:description" content="Fixture profile bio">'
                             + re.sub(r'<link rel="canonical"[^>]*>', '', html))
            # Hidden login templates must not block a public/session-visible page.
            page_html += '<input type="password" style="display:none">'
            await route.fulfill(status=200, content_type="text/html", body=page_html)

        await context.route("**/*", handle)
        return context

    monkeypatch.setattr(crawler, "launch_browser", launch_local_fixture)
    try:
        await crawler.start()
    finally:
        crawler_type_var.reset(crawler_token)
        source_keyword_var.reset(keyword_token)

    assert requested_urls
    assert post_url in requested_urls
    if mode == "search":
        assert any("/search" in urlsplit(url).path for url in requested_urls)
    elif mode == "creator":
        assert profile_url in requested_urls
    output = tmp_path / platform / "jsonl"
    post_files = list(output.glob(f"{mode}_contents_*.jsonl"))
    comment_files = list(output.glob(f"{mode}_comments_*.jsonl"))
    assert len(post_files) == 1 and len(comment_files) == 1
    posts = [json.loads(row) for row in post_files[0].read_text().splitlines()]
    replies = [json.loads(row) for row in comment_files[0].read_text().splitlines()]
    assert [(item["content_id"], item["content"]) for item in posts] == [(identity, "Fixture original post")]
    assert [(item["comment_id"], item["content_id"], item["content"]) for item in replies] == [
        (comment_identity, identity, "Fixture reply"),
    ]
    assert posts[0]["source_keyword"] == ("fixture keyword" if mode == "search" else "")
    assert posts[0]["platform"] == platform
    if mode == "creator":
        creator_files = list(output.glob("creator_creators_*.jsonl"))
        assert len(creator_files) == 1
        creators = [json.loads(row) for row in creator_files[0].read_text().splitlines()]
        assert [(item["user_id"], item["nickname"], item["profile_url"]) for item in creators] == [
            ("alice", "Alice", profile_url),
        ]
    assert closed == [True]
    assert crawler.browser_context is None and crawler.context_page is None and crawler._browser is None
