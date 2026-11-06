# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_dcard_adapter.py
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

"""Public record and browser fixture checks, without contacting Dcard."""

import importlib.util
import json
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

_path = Path(__file__).resolve().parents[1] / "media_platform/dcard/adapter.py"
_spec = importlib.util.spec_from_file_location("dcard_adapter", _path)
adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapter)


@pytest.mark.parametrize("value,expected", [
    ("123", "https://www.dcard.tw/p/123"),
    ("https://dcard.tw/p/123?cid=tracking#x", "https://www.dcard.tw/p/123"),
    ("https://www.dcard.tw/f/tech/p/123/", "https://www.dcard.tw/f/tech/p/123"),
    ("https://www.dcard.tw/f/tech/p/123-%E6%B8%AC%E8%A9%A6", "https://www.dcard.tw/f/tech/p/123"),
    ("/f/tech/p/123-title", "https://www.dcard.tw/f/tech/p/123"),
])
def test_post_url_normalization(value, expected):
    assert adapter.normalize_post_url(value) == expected
    assert adapter.post_id(value) == "123"


@pytest.mark.parametrize("value", [
    "0", "00123", "-123", "", "javascript:alert(1)", "//dcard.tw/p/123",
    "https://dcard.tw.evil.test/p/123", "https://dcard.tw@evil.test/p/123",
    "https://user@dcard.tw/p/123", "https://dcard.tw:443/p/123",
    "file://dcard.tw/p/123", "https://dcard.tw/f/tech/p/0", "https://dcard.tw/f/tech",
    "https://dcard.tw/f/tech%2Ffake/p/123", "https://dcard.tw/p/123-title%2Fother",
    "https://dcard.tw/p/123/b/1", "https://dcard.tw/f/tech/p/123-",
])
def test_invalid_post_urls_rejected(value):
    with pytest.raises(ValueError):
        adapter.normalize_post_url(value)


@pytest.mark.parametrize("value", ["alice.name_1", "@alice.name_1", "https://dcard.tw/@alice.name_1/posts?ref=x"])
def test_creator_url_normalization(value):
    assert adapter.normalize_creator_url(value) == "https://www.dcard.tw/@alice.name_1"


@pytest.mark.parametrize("value", ["", "@", "-alice", ".alice", "a" * 61, "https://evil.test/@alice", "https://dcard.tw/@alice/likes", "https://dcard.tw/@alice%2Fbob"])
def test_invalid_profiles_rejected(value):
    with pytest.raises(ValueError):
        adapter.normalize_creator_url(value)


def test_search_url_encodes_unicode_and_punctuation():
    parsed = urlsplit(adapter.search_url("台灣 & Python#1"))
    assert parsed.netloc == "www.dcard.tw"
    assert parse_qs(parsed.query) == {"query": ["台灣 & Python#1"]}


def test_public_post_preserves_real_values_without_inventing_anonymous_identity():
    raw = {"id": 123, "title": "文章標題", "excerpt": "Search preview", "withNickname": False,
           "personaUid": "not-public", "school": "匿名學校", "identityIdV3": "private-pseudonym",
           "author": {"displayName": "某大學"}, "forumAlias": "tech", "forumName": "科技業",
           "createdAt": "2026-11-06T00:00:00Z", "likeCount": 0, "commentCount": 0,
           "shareCount": 0, "mediaMeta": [{"url": "https://megapx-assets.dcard.tw/images/image/full.jpeg"}],
           "media": [{"url": "https://megapx-assets.dcard.tw/images/image/full.jpeg"}, "javascript:bad"]}
    record = adapter.normalize_post(raw)
    assert record["content_id"] == "123" and record["content_url"] == "https://www.dcard.tw/f/tech/p/123"
    assert record["content"] == "Search preview" and record["content_is_excerpt"] is True
    assert record["user_id"] == "" and record["nickname"] == "某大學"
    assert record["liked_count"] == record["comment_count"] == record["share_count"] == 0
    assert record["media_urls"] == ["https://megapx-assets.dcard.tw/images/image/full.jpeg"]
    assert "identityIdV3" not in record
    detailed = adapter.normalize_post({**raw, "content": "Full body", "withNickname": True, "personaUid": "alice"})
    assert detailed["content"] == "Full body" and detailed["content_is_excerpt"] is False
    assert detailed["user_id"] == "alice"
    missing_body = adapter.normalize_post({**raw, "content": None})
    assert missing_body["content"] == "Search preview" and missing_body["content_is_excerpt"] is True


@pytest.mark.parametrize("raw", [{}, {"id": 0, "title": "Invalid"}, {"id": 123, "error": "missing"}, {"id": 123, "title": "Hidden", "hidden": True}])
def test_not_a_post_or_hidden_record_rejected(raw):
    with pytest.raises(ValueError):
        adapter.normalize_post(raw)


def test_comment_real_id_floor_and_parent_relationships():
    raw = {"id": "uuid-comment-1", "postId": 123, "floor": 1, "content": "Public reply",
           "likeCount": 0, "createdAt": "2026-11-06T01:00:00Z", "withNickname": True,
           "author": {"displayName": "Alice", "persona": {"uid": "alice"}}}
    record = adapter.normalize_comment(raw, "123")
    assert record["comment_id"] == "uuid-comment-1" and record["user_id"] == "alice"
    assert record["parent_comment_id"] == "" and record["liked_count"] == 0
    assert record["comment_url"] == "https://www.dcard.tw/p/123/b/1"
    floor_record = adapter.normalize_comment({"floor": 3, "content": "A real floor"}, "123")
    assert floor_record["comment_id"] == "123:B3"
    nested = adapter.normalize_comment({"floor": 1, "content": "Nested", "parentId": "uuid-comment-1"}, "123")
    assert nested["comment_id"] == "123:uuid-comment-1:B1" and nested["parent_comment_id"] == "uuid-comment-1"
    assert nested["comment_url"] == ""


@pytest.mark.parametrize("raw", [{"content": "No ID"}, {"id": "x", "content": "Hidden", "hidden": True}, {"id": "x", "content": "Wrong post", "postId": 999}, {"id": "x", "content": ""}])
def test_unavailable_or_unidentifiable_comment_is_omitted(raw):
    assert adapter.normalize_comment(raw, "123") is None


def test_public_persona_normalization_requires_account_identifier():
    raw = {"uid": "alice", "nickname": "Alice", "description": "Public bio", "avatar": {"url": "https://megapx-assets.dcard.tw/avatar.png"}}
    assert adapter.normalize_creator(raw, "@alice") == {
        "user_id": "alice", "nickname": "Alice", "description": "Public bio",
        "profile_url": "https://www.dcard.tw/@alice", "avatar": "https://megapx-assets.dcard.tw/avatar.png"}
    with pytest.raises(ValueError):
        adapter.normalize_creator({"school": "A school"}, "alice")
    with pytest.raises(ValueError):
        adapter.normalize_creator(raw, "bob")
    assert adapter.normalize_creator({"uid": "alice", "postAvatar": "https://megapx-assets.dcard.tw/avatar.png"}, "alice")["avatar"] == "https://megapx-assets.dcard.tw/avatar.png"


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True, executable_path=shutil.which("chromium") or shutil.which("google-chrome"))
        context = browser.new_context()
        context.route("**/*", lambda route: route.fulfill(status=200, body="", content_type="text/html"))
        value = context.new_page()
        value.goto("https://www.dcard.tw/f/tech/p/123")
        yield value
        browser.close()


def _next_data(queries):
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"dehydratedState": {"queries": queries}}}) + '</script>'


def test_detail_hydration_targets_original_not_recommended_post(page):
    page.set_content(_next_data([
        {"queryKey": ["post", "123"], "state": {"data": {"id": 123, "title": "Original", "content": "Full body", "withNickname": False, "author": {"displayName": "某大學"}, "likeCount": 0}}},
        {"queryKey": ["relatedPosts", "123"], "state": {"data": [{"id": 999, "title": "Recommendation", "content": "Wrong"}]}},
    ]))
    records = page.evaluate(adapter.EXTRACT_POSTS_JS)
    assert [(item["content_id"], item["content"]) for item in records] == [("123", "Full body")]
    assert records[0]["user_id"] == "" and records[0]["liked_count"] == 0


def test_structured_comments_scope_article_and_keep_nested_parent(page):
    page.set_content(_next_data([
        {"queryKey": ["comments", "123"], "state": {"data": {"items": [
            {"id": "uuid-1", "postId": 123, "floor": 1, "content": "Top", "withNickname": True, "personaUid": "alice"},
            {"id": "uuid-2", "postId": 123, "floor": 1, "parentId": "uuid-1", "content": "Nested"},
            {"id": "hidden", "postId": 123, "floor": 4, "content": "Hidden", "hidden": True},
            {"id": "unrelated", "postId": 999, "floor": 5, "content": "Suggested"},
        ]}}},
        {"queryKey": ["comments", "999"], "state": {"data": [{"id": "other", "floor": 1, "content": "Other post"}]}},
    ]))
    rows = page.evaluate(adapter.EXTRACT_COMMENTS_JS)
    assert [(row["comment_id"], row["parent_comment_id"]) for row in rows] == [("uuid-1", ""), ("uuid-2", "uuid-1")]


def test_dom_fallback_excludes_hidden_and_unscoped_comments(page):
    page.set_content('''
        <article><h1>Visible title</h1><a href="/f/tech/p/123">post</a>
          <div data-post-content>Visible body</div><a href="/@alice">Alice</a>
          <time datetime="2026-11-06T00:00:00Z">today</time></article>
        <article hidden><h1>Hidden</h1><a href="/p/999">Other</a><div data-post-content>Hidden</div></article>
        <section id="comment-anchor">
          <div data-comment-id="uuid-top" data-floor="1"><div data-comment-content>Top reply</div><a href="/@bob">Bob</a></div>
          <div data-floor="2"><div data-comment-content>Anonymous real floor</div></div>
          <div data-comment-id="uuid-hidden" hidden><div data-comment-content>Hidden reply</div></div>
        </section>
        <aside><div data-comment-id="unrelated"><div data-comment-content>Suggested comment</div></div></aside>
    ''')
    records = page.evaluate(adapter.EXTRACT_POSTS_JS)
    assert len(records) == 1 and records[0]["content"] == "Visible body" and records[0]["user_id"] == "alice"
    comments = page.evaluate(adapter.EXTRACT_COMMENTS_JS)
    assert [row["comment_id"] for row in comments] == ["uuid-top", "123:B2"]
    assert comments[1]["user_id"] == ""


def test_ld_json_requires_matching_article_url(page):
    structured = [{"@type": "SocialMediaPosting", "url": "https://www.dcard.tw/p/999", "headline": "Wrong", "articleBody": "Wrong"},
                  {"@type": "SocialMediaPosting", "url": "https://www.dcard.tw/p/123", "headline": "Right", "articleBody": "Full body", "author": {"name": "A school"}}]
    page.set_content('<script type="application/ld+json">' + json.dumps(structured) + '</script>')
    records = page.evaluate(adapter.EXTRACT_POSTS_JS)
    assert [(row["content_id"], row["content"]) for row in records] == [("123", "Full body")]


def test_creator_hydration_and_hidden_login_marker(page):
    page.goto("https://www.dcard.tw/@alice")
    page.set_content(_next_data([{"queryKey": ["persona", "alice"], "state": {"data": {"uid": "alice", "nickname": "Alice", "description": "Bio"}}}]) + '<button hidden>登出</button>')
    record = page.evaluate(adapter.EXTRACT_CREATOR_JS)
    assert record["user_id"] == "alice" and record["nickname"] == "Alice"
    assert page.evaluate(adapter.LOGIN_SUCCESS_JS) is False
    page.set_content('<div style="visibility: hidden"><button>登出</button></div>')
    assert page.evaluate(adapter.LOGIN_SUCCESS_JS) is False
    page.set_content('<button>登出</button>')
    assert page.evaluate(adapter.LOGIN_SUCCESS_JS) is True
    page.goto("https://www.dcard.tw/f/tech/p/123")


def test_search_hydration_lists_post_previews_and_skips_recommendations(page):
    page.goto("https://www.dcard.tw/search?query=fixture")
    page.set_content(_next_data([
        {"queryKey": ["searchPosts", "fixture"], "state": {"data": {"pages": [[
            {"id": 123, "title": "First", "excerpt": "Preview", "forumAlias": "tech"},
            {"id": 456, "title": "Second", "excerpt": "Other", "forumAlias": "job"},
        ]]}}},
        {"queryKey": ["recommendedPosts"], "state": {"data": [{"id": 999, "title": "Advertisement"}]}},
    ]))
    records = page.evaluate(adapter.EXTRACT_POSTS_JS)
    assert [(row["content_id"], row["content"]) for row in records] == [("123", "Preview"), ("456", "Other")]
    assert all(row["content_is_excerpt"] for row in records)
    page.goto("https://www.dcard.tw/f/tech/p/123")
