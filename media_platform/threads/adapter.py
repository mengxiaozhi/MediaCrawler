# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/threads/adapter.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

"""Threads URL handling and extraction of rendered, visible page content."""

import re
from urllib.parse import quote, unquote, urlencode, urlsplit

PLATFORM = "threads"
BASE_URL = "https://www.threads.com"
COOKIE_DOMAIN = ".threads.com"
AUTH_COOKIE_NAMES = ("sessionid",)

_HOSTS = {"threads.com", "www.threads.com", "threads.net", "www.threads.net"}
_USERNAME = re.compile(r"[A-Za-z0-9_.]{1,30}\Z")
_CODE = re.compile(r"[A-Za-z0-9_-]+\Z")


def _path(value: str) -> str:
    value = value.strip()
    if value.startswith(("http://", "https://")):
        parsed = urlsplit(value)
        if (parsed.hostname not in _HOSTS or parsed.username or parsed.password
                or parsed.port is not None):
            raise ValueError("Expected a threads.com or threads.net URL")
        return unquote(parsed.path).rstrip("/")
    if "://" in value or value.startswith("//"):
        raise ValueError("Expected a Threads URL, username, or post shortcode")
    return value.rstrip("/")


def normalize_post_url(value: str) -> str:
    """Accept a permalink, a shared /t/ URL, or a Threads post shortcode."""
    path = _path(value)
    match = re.fullmatch(r"/@([A-Za-z0-9_.]{1,30})/post/([A-Za-z0-9_-]+)", path)
    if match:
        return f"{BASE_URL}/@{match[1]}/post/{match[2]}"
    shared = re.fullmatch(r"/t/([A-Za-z0-9_-]+)", path)
    if shared:
        return f"{BASE_URL}/t/{shared[1]}"
    if _CODE.fullmatch(path):
        return f"{BASE_URL}/t/{path}"
    raise ValueError("Expected a Threads /@username/post/code permalink or shortcode")


def post_id(value: str) -> str:
    return normalize_post_url(value).rsplit("/", 1)[-1]


def normalize_creator_url(value: str) -> str:
    """Accept a username or a complete Threads profile URL."""
    username = _path(value).removeprefix("/").removeprefix("@")
    if not _USERNAME.fullmatch(username):
        raise ValueError("Expected a Threads username or profile URL")
    return f"{BASE_URL}/@{quote(username, safe='._')}"


def search_url(keyword: str) -> str:
    return f"{BASE_URL}/search?{urlencode({'q': keyword, 'serp_type': 'default'})}"


# Threads has changed CSS class names repeatedly. Prefer semantic elements,
# permalink structure, and text direction attributes instead of generated classes.
_DOM_HELPERS = r"""
const visible = el => !!(el && el.getClientRects().length &&
    getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none');
const parseLink = href => {
    try {
        const u = new URL(href, document.baseURI);
        if (!['threads.com', 'www.threads.com', 'threads.net', 'www.threads.net'].includes(u.hostname)) return null;
        const m = u.pathname.match(/^\/@([A-Za-z0-9_.]+)\/post\/([A-Za-z0-9_-]+)\/?$/);
        return m ? {id:m[2], user:m[1], url:'https://www.threads.com/@'+m[1]+'/post/'+m[2]} : null;
    } catch { return null; }
};
const cardFor = link => {
    const semantic = link.closest('article, [role="article"]');
    if (semantic) return semantic;
    let card = link.parentElement;
    for (let parent = card?.parentElement, depth = 0; parent && depth < 10; parent = parent.parentElement, depth++) {
        if (['BODY', 'MAIN', 'HTML'].includes(parent.tagName) || parent.getAttribute('role') === 'main') break;
        const ids = new Set([...parent.querySelectorAll('a[href]')].map(a => parseLink(a.href)?.id).filter(Boolean));
        if (ids.size > 1) break;
        card = parent;
    }
    return card;
};
const count = (card, pattern) => {
    for (const el of card.querySelectorAll('[aria-label], [data-testid]')) {
        const label = el.getAttribute('aria-label') || '';
        if (pattern.test(label)) {
            const n = label.match(/[\d][\d.,\s]*(?:[KMBkmb萬万億亿])?/);
            if (n) return n[0].trim();
            const text = el.textContent.trim();
            if (/^[\d][\d.,\s]*(?:[KMBkmb萬万億亿])?$/.test(text)) return text;
        }
    }
    return '';
};
const rows = [];
const seen = new Set();
const cards = new Map();
for (const link of document.querySelectorAll('a[href]')) {
    const info = parseLink(link.href);
    if (!info || seen.has(info.id) || !visible(link)) continue;
    const card = cardFor(link);
    if (!card || !visible(card)) continue;
    seen.add(info.id);
    cards.set(info.id, card);
    const preferred = [...card.querySelectorAll('[data-testid="post-text"], [data-testid="post-content"]')].filter(visible);
    const candidates = preferred.length ? preferred : [...card.querySelectorAll('[dir="auto"]')].filter(el =>
        visible(el) && !el.querySelector('[dir="auto"]') && !el.closest('a, button, time, [role="button"]'));
    const texts = candidates.map(el => el.innerText.trim()).filter(t => t && t !== info.user && t !== '@'+info.user);
    const profile = [...card.querySelectorAll('a[href]')].find(a => {
        try { return new URL(a.href).pathname.replace(/\/$/, '') === '/@'+info.user; } catch { return false; }
    });
    const time = card.querySelector('time');
    const media = [...card.querySelectorAll('img, video')].filter(el => visible(el) &&
        !el.closest('a[href="/@'+info.user+'"]') && !/avatar|profile picture|大頭貼|头像/i.test(el.alt || ''))
        .map(el => el.currentSrc || el.src || el.poster || '').filter(u => /^https?:/.test(u));
    rows.push({content_id:info.id, content_url:info.url, user_id:info.user,
        nickname:profile?.innerText.trim() || info.user, content:[...new Set(texts)].join('\n'),
        publish_time:time?.getAttribute('datetime') || time?.getAttribute('title') || '',
        liked_count:count(card, /like|讚|赞/i), comment_count:count(card, /repl|comment|回覆|回复|評論|评论/i),
        share_count:count(card, /repost|share|轉發|转发|分享/i), media_urls:[...new Set(media)]});
}
"""

EXTRACT_POSTS_JS = "() => {" + _DOM_HELPERS + "return rows;}"

EXTRACT_COMMENTS_JS = "() => {" + _DOM_HELPERS + r"""
const canonical = document.querySelector('link[rel="canonical"]')?.href || location.href;
const current = parseLink(canonical);
// A reply is itself a Threads post, as are suggested/related posts. A permalink
// page alone is insufficient evidence that another card is a reply. Require a
// labelled reply region or an explicit reply relationship, otherwise return no
// comments for an unrecognized layout.
if (!current) return [];
const replyRegion = '[data-testid="post-replies"], [data-testid="replies"], '+
    '[aria-label="Replies" i], [aria-label="Comments" i], [aria-label="回覆"], '+
    '[aria-label="回复"], [aria-label="留言"], [aria-label="評論"], [aria-label="评论"]';
const replyMarker = '[data-testid="reply"], [data-testid="thread-reply"], '+
    '[data-testid="post-reply"], [data-reply-to], [data-parent-post-id]';
const suggestionRegion = '[data-testid="suggested-posts"], [data-testid="related-posts"], '+
    '[aria-label="Suggested posts" i], [aria-label="Related posts" i], '+
    '[aria-label="推薦貼文"], [aria-label="推荐帖子"]';
const comments = [];
for (const row of rows) {
    if (row.content_id === current.id) continue;
    const card = cards.get(row.content_id);
    if (!card || card.closest(suggestionRegion)) continue;
    const marker = card.closest(replyMarker);
    const region = card.closest(replyRegion);
    if (!marker && !region) continue;
    // Only explicit parent IDs are reliable; nested quoted posts are also
    // articles and must not be mistaken for nested replies.
    const parent = marker?.getAttribute('data-reply-to') || marker?.getAttribute('data-parent-post-id') || '';
    if (parent && parent !== current.id && !rows.some(candidate => candidate.content_id === parent)) continue;
    if (card.parentElement?.closest('article, [role="article"]') && !marker) continue;
    comments.push({comment_id:row.content_id, content:row.content, user_id:row.user_id,
        nickname:row.nickname, publish_time:row.publish_time,
        parent_comment_id:parent === current.id ? '' : parent, comment_url:row.content_url});
}
return comments;
}"""

EXTRACT_CREATOR_JS = r"""() => {
    const canonical = document.querySelector('link[rel="canonical"]')?.href || location.href;
    let user = '';
    try { user = new URL(canonical).pathname.match(/^\/@([A-Za-z0-9_.]+)\/?$/)?.[1] || ''; } catch {}
    if (!user) return {};
    const meta = property => document.querySelector('meta[property="'+property+'"]')?.content || '';
    const heading = document.querySelector('h1, [role="heading"][aria-level="1"]');
    return {user_id:user, nickname:heading?.innerText.trim() || user,
        profile_url:'https://www.threads.com/@'+user,
        description:meta('og:description') || document.querySelector('meta[name="description"]')?.content || '',
        avatar:meta('og:image')};
}"""
