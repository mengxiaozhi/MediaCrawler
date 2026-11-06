# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_threads_adapter.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

"""URL validation and browser-rendered Threads extraction fixtures."""

import shutil
import unittest
from urllib.parse import parse_qs, urlsplit

from media_platform.threads import adapter


class ThreadsURLTests(unittest.TestCase):
    def test_legacy_permalink_is_canonicalized(self):
        self.assertEqual(
            adapter.normalize_post_url("https://www.threads.net/@alice.name/post/ABC_123/?xmt=1"),
            "https://www.threads.com/@alice.name/post/ABC_123",
        )
        self.assertEqual(adapter.post_id("ABC_123"), "ABC_123")
        self.assertEqual(adapter.post_id("https://threads.com/t/ABC_123"), "ABC_123")

    def test_foreign_and_malformed_urls_are_rejected(self):
        for value in (
            "https://threads.com.evil.example/@alice/post/ABC",
            "https://www.threads.com@evil.example/@alice/post/ABC",
            "https://alice@threads.com/@alice/post/ABC",
            "https://threads.com:8443/@alice/post/ABC",
            "//evil.example/@alice/post/ABC",
            "https://threads.com/@alice/post/ABC/extra",
            "https://threads.com/@alice",
            "javascript:alert(1)",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                adapter.normalize_post_url(value)

    def test_creator_names_and_urls(self):
        for value in ("alice.name", "@alice.name", "https://threads.net/@alice.name/?hl=en"):
            self.assertEqual(adapter.normalize_creator_url(value), "https://www.threads.com/@alice.name")
        with self.assertRaises(ValueError):
            adapter.normalize_creator_url("https://threads.com/@alice/post/ABC")

    def test_search_keyword_is_encoded(self):
        url = urlsplit(adapter.search_url("台灣 & Python#1"))
        self.assertEqual(url.netloc, "www.threads.com")
        self.assertEqual(parse_qs(url.query)["q"], ["台灣 & Python#1"])


class ThreadsDOMTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.skipTest("Playwright is not installed")
        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            executable_path=shutil.which("chromium") or shutil.which("google-chrome"),
        )
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()

    async def test_posts_and_replies_have_distinct_real_ids(self):
        await self.page.set_content("""
            <base href="https://www.threads.com/">
            <link rel="canonical" href="https://www.threads.com/@alice/post/ABC_123">
            <article>
                <a href="/@alice">Alice</a>
                <a href="/@alice/post/ABC_123"><time datetime="2026-11-01T12:00:00Z">2h</time></a>
                <div dir="auto">Original text</div>
                <a href="/@alice/post/ABC_123">Permalink again</a>
                <button aria-label="100 likes">100</button>
            </article>
            <section aria-label="Replies"><article>
                <a href="/@bob">Bob</a>
                <a href="/@bob/post/Reply_4"><time datetime="2026-11-02T12:00:00Z">1h</time></a>
                <div dir="auto">Reply text</div>
            </article></section>
            <section aria-label="Suggested posts"><article>
                <a href="/@carol">Carol</a>
                <a href="/@carol/post/Suggested_8"><time>today</time></a>
                <div dir="auto">Unrelated suggested post</div>
            </article></section>
            <article hidden>
                <a href="/@hidden/post/Hidden_5">Hidden permalink</a>
                <div dir="auto">Not rendered</div>
            </article>
        """)
        posts = await self.page.evaluate(adapter.EXTRACT_POSTS_JS)
        self.assertEqual([post["content_id"] for post in posts], ["ABC_123", "Reply_4", "Suggested_8"])
        self.assertEqual(posts[0]["content"], "Original text")
        self.assertEqual(posts[0]["liked_count"], "100")
        self.assertEqual(posts[1]["liked_count"], "")
        comments = await self.page.evaluate(adapter.EXTRACT_COMMENTS_JS)
        self.assertEqual([comment["comment_id"] for comment in comments], ["Reply_4"])
        self.assertEqual(comments[0]["content"], "Reply text")

    async def test_unmarked_posts_are_not_guessed_as_replies(self):
        await self.page.set_content("""
            <base href="https://www.threads.com/">
            <link rel="canonical" href="https://www.threads.com/@alice/post/ABC">
            <article><a href="/@alice/post/ABC">original</a><div dir="auto">text</div></article>
            <article><a href="/@bob/post/DEF">another post</a><div dir="auto">text</div></article>
        """)
        self.assertEqual(await self.page.evaluate(adapter.EXTRACT_COMMENTS_JS), [])

    async def test_explicit_parent_relationship_is_preserved(self):
        await self.page.set_content("""
            <base href="https://www.threads.com/">
            <link rel="canonical" href="https://www.threads.com/@alice/post/ABC">
            <article><a href="/@alice/post/ABC">original</a><div dir="auto">text</div></article>
            <article data-reply-to="ABC"><a href="/@bob/post/DEF">reply</a><div dir="auto">Reply</div></article>
            <article data-parent-post-id="DEF"><a href="/@carol/post/GHI">nested reply</a><div dir="auto">Nested</div></article>
            <article data-parent-post-id="Unrelated"><a href="/@dave/post/JKL">unrelated</a><div dir="auto">Other</div></article>
        """)
        comments = await self.page.evaluate(adapter.EXTRACT_COMMENTS_JS)
        self.assertEqual([comment["comment_id"] for comment in comments], ["DEF", "GHI"])
        self.assertEqual(comments[0]["parent_comment_id"], "")
        self.assertEqual(comments[1]["parent_comment_id"], "DEF")

    async def test_comments_are_not_guessed_on_search_or_profile_page(self):
        await self.page.set_content("""
            <base href="https://www.threads.com/">
            <link rel="canonical" href="https://www.threads.com/@alice">
            <article><a href="/@alice/post/ABC">post</a><div dir="auto">text</div></article>
        """)
        self.assertEqual(await self.page.evaluate(adapter.EXTRACT_COMMENTS_JS), [])

    async def test_profile_metadata(self):
        await self.page.set_content("""
            <link rel="canonical" href="https://www.threads.com/@alice">
            <meta property="og:description" content="Author bio">
            <meta property="og:image" content="https://cdn.example/avatar.jpg">
            <h1>Alice Example</h1>
        """)
        profile = await self.page.evaluate(adapter.EXTRACT_CREATOR_JS)
        self.assertEqual(profile["user_id"], "alice")
        self.assertEqual(profile["nickname"], "Alice Example")
        self.assertEqual(profile["description"], "Author bio")
