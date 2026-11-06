# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_facebook_adapter.py
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

import importlib.util
import shutil
from pathlib import Path

import pytest

# Keep URL/extractor tests independent of the shared browser lifecycle module.
_path = Path(__file__).resolve().parents[1] / "media_platform/facebook/adapter.py"
_spec = importlib.util.spec_from_file_location("facebook_adapter", _path)
adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapter)


@pytest.mark.parametrize(("value", "expected_id", "expected_url"), [
    ("https://m.facebook.com/alice/posts/123?mibextid=tracking#x", "123", "https://www.facebook.com/alice/posts/123"),
    ("https://www.facebook.com/alice/posts/pfbidABC", "pfbidABC", "https://www.facebook.com/alice/posts/pfbidABC"),
    ("https://facebook.com/groups/42/posts/123/", "123", "https://www.facebook.com/groups/42/posts/123"),
    ("https://facebook.com/groups/42/permalink/123/?ref=x", "123", "https://www.facebook.com/groups/42/posts/123"),
    ("https://facebook.com/story.php?story_fbid=123&id=42&ref=x", "123", "https://www.facebook.com/story.php?story_fbid=123&id=42"),
    ("42_123", "123", "https://www.facebook.com/permalink.php?story_fbid=123&id=42"),
    ("https://facebook.com/reel/123/", "123", "https://www.facebook.com/reel/123"),
    ("https://facebook.com/watch/?v=123&ref=x", "123", "https://www.facebook.com/watch/?v=123"),
    ("https://facebook.com/alice/videos/123/", "123", "https://www.facebook.com/alice/videos/123"),
    ("https://facebook.com/photo.php?fbid=123&set=x", "123", "https://www.facebook.com/photo.php?fbid=123"),
])
def test_normalize_post_urls(value, expected_id, expected_url):
    assert adapter.normalize_post_url(value) == expected_url
    assert adapter.post_id(value) == expected_id


@pytest.mark.parametrize("value", [
    "https://facebook.com.evil.test/alice/posts/123",
    "https://evil.test/?url=https://facebook.com/alice/posts/123",
    "https://facebook.com@evil.test/alice/posts/123",
    "https://alice:secret@facebook.com/alice/posts/123",
    "https://facebook.com:9999/alice/posts/123",
    "file://facebook.com/alice/posts/123",
    "https://facebook.com/story.php?story_fbid=123",
    "https://facebook.com/watch/",
    "https://facebook.com/alice",
    "https://facebook.com/groups/123",
    "",
])
def test_reject_invalid_post_urls(value):
    with pytest.raises(ValueError):
        adapter.normalize_post_url(value)


@pytest.mark.parametrize(("value", "expected"), [
    ("alice.smith", "https://www.facebook.com/alice.smith"),
    ("42", "https://www.facebook.com/42"),
    ("https://m.facebook.com/alice?ref=x", "https://www.facebook.com/alice"),
    ("https://facebook.com/profile.php?id=42&ref=x", "https://www.facebook.com/profile.php?id=42"),
    ("https://facebook.com/people/Alice-Smith/42/", "https://www.facebook.com/42"),
])
def test_normalize_creators(value, expected):
    assert adapter.normalize_creator_url(value) == expected


@pytest.mark.parametrize("value", ["", "https://facebook.com/search", "https://facebook.com/alice/posts/123", "https://evil.test/alice"])
def test_reject_invalid_creator_urls(value):
    with pytest.raises(ValueError):
        adapter.normalize_creator_url(value)


@pytest.mark.parametrize("value", ["login", "LOGIN", "search", "watch", "help", "settings", "marketplace", "photo", "profile.php"])
def test_reserved_creator_names_rejected_in_both_forms(value):
    with pytest.raises(ValueError):
        adapter.normalize_creator_url(value)
    with pytest.raises(ValueError):
        adapter.normalize_creator_url(f"https://facebook.com/{value}")


def test_search_url_encodes_keyword():
    assert adapter.search_url("台灣 & travel") == "https://www.facebook.com/search/posts/?q=%E5%8F%B0%E7%81%A3%20%26%20travel"


@pytest.fixture(scope="module")
def browser_page():
    from playwright.sync_api import Error, sync_playwright

    with sync_playwright() as runtime:
        executable = shutil.which("chromium") or shutil.which("google-chrome")
        try:
            browser = runtime.chromium.launch(executable_path=executable, headless=True, args=["--no-sandbox"])
        except Error as exc:
            pytest.skip(f"Chromium is required for DOM fixture tests: {exc}")
        page = browser.new_page()
        page.route("https://www.facebook.com/**", lambda route: route.fulfill(status=200, body="", content_type="text/html"))
        page.goto("https://www.facebook.com/alice/posts/123")
        yield page
        browser.close()


def test_rendered_posts_and_comments_keep_real_identity(browser_page):
    browser_page.set_content('''
        <base href="https://www.facebook.com/">
        <article role="article">
          <h2><a href="https://www.facebook.com/alice">Alice</a></h2>
          <a href="https://www.facebook.com/alice/posts/123?ref=tracking"><time datetime="2026-10-01T12:00:00Z">Oct 1</time></a>
          <div data-ad-preview="message">A public post</div>
          <article role="article">
            <h3><a href="https://www.facebook.com/bob">Bob</a></h3>
            <div data-testid="comment_message">A reply</div>
            <a href="https://www.facebook.com/alice/posts/123?comment_id=456">1h</a>
            <article role="article">
              <h3><a href="https://www.facebook.com/carol">Carol</a></h3>
              <div dir="auto">A nested reply</div>
              <a href="https://www.facebook.com/alice/posts/123?comment_id=456&reply_comment_id=789">1m</a>
            </article>
          </article>
        </article>
        <article role="article">
          <h2><a href="https://www.facebook.com/alice">Alice</a></h2>
          <a href="https://www.facebook.com/alice/posts/123">Repeated post</a>
          <div data-ad-preview="message">A public post</div>
        </article>
        <article role="article"><div dir="auto">Missing permalink: cannot assign a real ID</div></article>
        <article role="article">
          <h3><a href="https://www.facebook.com/dan">Dan</a></h3>
          <div data-testid="comment_message">Comment on a suggested post</div>
          <a href="https://www.facebook.com/another/posts/999?comment_id=333">1h</a>
        </article>
    ''')
    posts = browser_page.evaluate(adapter.EXTRACT_POSTS_JS)
    assert len(posts) == 1
    assert posts[0]["content_id"] == "123"
    assert posts[0]["content_url"] == "https://www.facebook.com/alice/posts/123"
    assert posts[0]["content"] == "A public post"
    assert posts[0]["nickname"] == "Alice"
    assert posts[0]["publish_time"] == "2026-10-01T12:00:00Z"
    comments = browser_page.evaluate(adapter.EXTRACT_COMMENTS_JS)
    assert [(c["comment_id"], c["content"], c["parent_comment_id"]) for c in comments] == [
        ("456", "A reply", ""), ("789", "A nested reply", "456")
    ]


def test_creator_extracts_profile_not_entire_feed(browser_page):
    browser_page.set_content('''
       <link rel="canonical" href="https://www.facebook.com/profile.php?id=42">
       <meta property="og:description" content="Alice's public bio">
       <meta property="og:image" content="https://example.com/avatar.jpg">
       <h1>Alice</h1><article role="article">Unrelated feed post</article>
    ''')
    assert browser_page.evaluate(adapter.EXTRACT_CREATOR_JS) == {
        "user_id": "42", "nickname": "Alice", "profile_url": "https://www.facebook.com/profile.php?id=42",
        "description": "Alice's public bio", "avatar": "https://example.com/avatar.jpg",
    }


def test_group_permalink_dom_normalizes_to_posts(browser_page):
    browser_page.set_content('''
        <article role="article">
            <a href="https://www.facebook.com/groups/42/permalink/123/?ref=x">Date</a>
            <div data-ad-preview="message">Group post</div>
        </article>
    ''')
    rows = browser_page.evaluate(adapter.EXTRACT_POSTS_JS)
    assert [(row["content_id"], row["content_url"]) for row in rows] == [
        ("123", "https://www.facebook.com/groups/42/posts/123")
    ]


def test_hidden_cards_and_hidden_messages_are_excluded(browser_page):
    browser_page.set_content('''
        <article role="article" hidden>
            <a href="https://www.facebook.com/alice/posts/111">Date</a>
            <div data-ad-preview="message">Hidden post</div>
        </article>
        <article role="article">
            <a href="https://www.facebook.com/alice/posts/222">Date</a>
            <div data-ad-preview="message" style="visibility:hidden">Hidden message</div>
        </article>
        <div aria-hidden="true"><article role="article">
            <a href="https://www.facebook.com/alice/posts/333">Date</a>
            <div data-ad-preview="message">Hidden accessibility subtree</div>
        </article></div>
        <div style="opacity:0"><article role="article">
            <a href="https://www.facebook.com/alice/posts/444">Date</a>
            <div data-ad-preview="message">Transparent subtree</div>
        </article></div>
        <article role="article" style="display:none">
            <div data-testid="comment_message">Hidden comment</div>
            <a href="https://www.facebook.com/alice/posts/123?comment_id=555">Date</a>
        </article>
        <article role="article">
            <div data-testid="comment_message" hidden>Hidden comment message</div>
            <a href="https://www.facebook.com/alice/posts/123?comment_id=666">Date</a>
        </article>
    ''')
    assert browser_page.evaluate(adapter.EXTRACT_POSTS_JS) == []
    assert browser_page.evaluate(adapter.EXTRACT_COMMENTS_JS) == []
