# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/dcard/adapter.py
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

"""Dcard public URL validation, JSON records, and rendered-page fallbacks."""

import re
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlsplit

PLATFORM = "dcard"
BASE_URL = "https://www.dcard.tw"
COOKIE_DOMAIN = ".dcard.tw"
CONFIG_PREFIX = "DCARD"
# Dcard's anti-bot and analytics cookies do not establish account authentication.
# The shared manual-login flow must use LOGIN_SUCCESS_JS when this tuple is empty.
AUTH_COOKIE_NAMES = ()
_ID = re.compile(r"[1-9][0-9]*\Z")
_HANDLE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,59}\Z")
_POST = re.compile(r"/(?:f/([A-Za-z0-9_.-]+)/)?p/([1-9][0-9]*)(?:-[^/]+)?\Z")


def _path(value: str) -> str:
    value = value.strip()
    if value.startswith(("http://", "https://")):
        parsed = urlsplit(value)
        if (parsed.hostname not in {"dcard.tw", "www.dcard.tw"}
                or parsed.username is not None or parsed.password is not None
                or parsed.port is not None):
            raise ValueError("Expected a dcard.tw URL without credentials or a port")
        return unquote(parsed.path).rstrip("/")
    if "://" in value or value.startswith("//") or "?" in value or "#" in value:
        raise ValueError("Expected a Dcard URL, post ID, or public username")
    return value.rstrip("/")


def normalize_post_url(value: str) -> str:
    path = _path(value)
    if _ID.fullmatch(path):
        return f"{BASE_URL}/p/{path}"
    match = _POST.fullmatch(path)
    if not match:
        raise ValueError("Use a positive Dcard post ID or /f/forum/p/id URL")
    prefix = f"/f/{match[1]}" if match[1] else ""
    return f"{BASE_URL}{prefix}/p/{match[2]}"


def post_id(value: str) -> str:
    return normalize_post_url(value).rsplit("/", 1)[-1]


def normalize_creator_url(value: str) -> str:
    path = _path(value)
    if path.startswith("/@"):
        path = path[2:]
        if path.endswith("/posts"):
            path = path[:-6]
    else:
        path = path.removeprefix("@")
    if not _HANDLE.fullmatch(path):
        raise ValueError("Use a Dcard public username or /@username profile URL")
    return f"{BASE_URL}/@{quote(path, safe='._-')}"


def search_url(keyword: str) -> str:
    return f"{BASE_URL}/search?{urlencode({'query': keyword})}"


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _author(raw: dict) -> tuple[str, str]:
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    persona = author.get("persona") if isinstance(author.get("persona"), dict) else {}
    # A school/profession identity is a display name, never a public account ID.
    user = "" if raw.get("withNickname") is False else (
        _text(raw.get("personaUid")) or _text(author.get("personaUid"))
        or _text(author.get("username")) or _text(persona.get("uid")))
    nickname = (_text(author.get("displayName")) or _text(raw.get("personaNickname"))
                or _text(raw.get("school")))
    return user, nickname


def normalize_post(raw: dict) -> dict:
    """Convert a public v2 post/search record without inventing absent fields."""
    if not isinstance(raw, dict) or not _ID.fullmatch(str(raw.get("id", ""))):
        raise ValueError("Dcard post requires a positive numeric id")
    if not isinstance(raw.get("title"), str) and not isinstance(raw.get("content"), str):
        raise ValueError("Dcard response is not a post record")
    if any(raw.get(key) is True for key in ("hidden", "hiddenByAuthor", "inReview")):
        raise ValueError("Dcard post is hidden or unavailable")
    identity = str(raw["id"])
    forum = _text(raw.get("forumAlias"))
    url = f"{BASE_URL}/f/{forum}/p/{identity}" if re.fullmatch(r"[A-Za-z0-9_.-]+", forum) else f"{BASE_URL}/p/{identity}"
    user, nickname = _author(raw)
    media = []
    sources = [raw.get(key) for key in ("mediaMeta", "media")]
    for item in [item for source in sources if isinstance(source, list) for item in source]:
        value = item.get("url") if isinstance(item, dict) else item
        if isinstance(value, str) and value.startswith(("https://", "http://")) and value not in media:
            media.append(value)
    return {
        "content_id": identity, "content_url": url, "user_id": user,
        "nickname": nickname, "content": raw["content"] if isinstance(raw.get("content"), str) else _text(raw.get("excerpt")),
        "publish_time": _text(raw.get("createdAt")), "liked_count": raw.get("likeCount", ""),
        "comment_count": raw.get("totalCommentCount", raw.get("commentCount", "")),
        "share_count": raw.get("shareCount", ""), "media_urls": media,
        "title": _text(raw.get("title")), "forum_alias": forum,
        "forum_name": _text(raw.get("forumName")), "content_is_excerpt": not isinstance(raw.get("content"), str),
    }


def normalize_comment(raw: dict, post_id: str) -> dict | None:
    """Read a real comment ID, falling back only to its actual article floor."""
    if not isinstance(raw, dict) or not _ID.fullmatch(str(post_id)):
        return None
    if any(raw.get(key) is True for key in ("hidden", "hiddenByAuthor", "inReview", "deleted")):
        return None
    if raw.get("postId") is not None and str(raw["postId"]) != str(post_id):
        return None
    content = _text(raw.get("content"))
    if not content:
        return None
    parent = str(raw.get("parentId") or "")
    identity = raw.get("id")
    floor = raw.get("floor")
    if identity is None or str(identity) == "":
        if not _ID.fullmatch(str(floor or "")):
            return None
        identity = f"{post_id}:{parent + ':' if parent else ''}B{floor}"
    user, nickname = _author(raw)
    return {
        "comment_id": str(identity), "content_id": str(post_id), "content": content,
        "user_id": user, "nickname": nickname, "publish_time": _text(raw.get("createdAt")),
        "parent_comment_id": parent, "liked_count": raw.get("likeCount", ""), "floor": floor,
        "comment_url": f"{BASE_URL}/p/{post_id}/b/{floor}" if _ID.fullmatch(str(floor or "")) and not parent else "",
    }


def normalize_creator(raw: dict, handle: str) -> dict:
    """Normalize a public persona response; anonymous schools are never profiles."""
    url = normalize_creator_url(handle)
    if not isinstance(raw, dict):
        raise ValueError("Dcard persona response must be an object")
    user = _text(raw.get("uid")) or _text(raw.get("personaUid")) or _text(raw.get("username"))
    if not user:
        raise ValueError("Dcard response does not contain a public persona identifier")
    if user.lower() != url.rsplit("/@", 1)[-1].lower():
        raise ValueError("Dcard persona response does not match the requested username")
    avatar = raw.get("avatar") or raw.get("postAvatar")
    if isinstance(avatar, dict):
        avatar = avatar.get("url")
    return {"user_id": user, "nickname": _text(raw.get("nickname")) or _text(raw.get("displayName")),
            "profile_url": url, "description": _text(raw.get("description")), "avatar": _text(avatar)}


LOGIN_SUCCESS_JS = r"""() => [...document.querySelectorAll('a, button, [role="menuitem"]')].some(el => {
    if (!el.getClientRects().length || el.closest('[hidden], [aria-hidden="true"]') ||
        !/^(登出|Log out|Sign out)$/i.test((el.innerText || '').trim())) return false;
    for (let node = el; node instanceof Element; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    }
    return true;
})"""


_JS_HELPERS = r"""
const text = el => el ? (el.innerText || el.textContent || '').trim() : '';
const visible = el => {
    if (!el || el.closest('[hidden], [aria-hidden="true"]') || !el.getClientRects().length) return false;
    for (let node = el; node instanceof Element; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    }
    return true;
};
const linkInfo = href => {
    try {
        if (!href) return null;
        const u = new URL(href, location.href);
        if (!['www.dcard.tw', 'dcard.tw'].includes(u.hostname) || u.username || u.password || u.port) return null;
        const m = decodeURIComponent(u.pathname).match(/^\/(?:f\/([A-Za-z0-9_.-]+)\/)?p\/([1-9][0-9]*)(?:-[^/]+)?\/?$/);
        return m ? {id:m[2], forum:m[1] || '', url:'https://www.dcard.tw'+(m[1] ? '/f/'+m[1] : '')+'/p/'+m[2]} : null;
    } catch { return null; }
};
const current = linkInfo(document.querySelector('link[rel="canonical"]')?.href || location.href);
const json = script => { try { return JSON.parse(script?.textContent || ''); } catch { return null; } };
const next = json(document.getElementById('__NEXT_DATA__'));
const queries = next?.props?.dehydratedState?.queries || next?.props?.pageProps?.dehydratedState?.queries || [];
const postRecord = item => {
    if (!item || !/^[1-9][0-9]*$/.test(String(item.id)) || typeof item.title !== 'string' || item.hidden || item.hiddenByAuthor || item.inReview) return null;
    const forum = /^[A-Za-z0-9_.-]+$/.test(item.forumAlias || '') ? item.forumAlias : '';
    const author = item.author || {};
    return {content_id:String(item.id), content_url:'https://www.dcard.tw'+(forum ? '/f/'+forum : '')+'/p/'+item.id,
        content:typeof item.content === 'string' ? item.content : item.excerpt || '', title:item.title,
        content_is_excerpt:typeof item.content !== 'string', user_id:item.withNickname === false ? '' : item.personaUid || author.personaUid || author.username || author.persona?.uid || '',
        nickname:author.displayName || item.personaNickname || item.school || '', publish_time:item.createdAt || '',
        liked_count:item.likeCount ?? '', comment_count:item.totalCommentCount ?? item.commentCount ?? '',
        share_count:item.shareCount ?? '', media_urls:[...new Set((item.mediaMeta || []).map(m => m.url).filter(u => /^https?:/.test(u || '')))],
        forum_alias:forum, forum_name:item.forumName || ''};
};
const deepPosts = (value, out, depth=0) => {
    if (!value || typeof value !== 'object' || depth > 8) return;
    if (Array.isArray(value)) { for (const item of value) deepPosts(item, out, depth+1); return; }
    const record = postRecord(value);
    if (record) { out.push(record); return; }
    for (const [key, item] of Object.entries(value)) {
        if (!/related|suggest|recommend|adverts/i.test(key)) deepPosts(item, out, depth+1);
    }
};
"""

EXTRACT_POSTS_JS = "() => {" + _JS_HELPERS + r"""
const records = [];
for (const query of queries) {
    const key = query?.queryKey || [];
    if (/related|suggest|recommend/i.test(JSON.stringify(key))) continue;
    if (current && !(key[0] === 'post' && String(key[1]) === current.id)) continue;
    deepPosts(query?.state?.data, records);
}
if (current) {
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
        const data = json(script);
        for (const item of Array.isArray(data) ? data : [data, ...(data?.['@graph'] || [])]) {
            if (!item || !(Array.isArray(item['@type']) ? item['@type'].includes('SocialMediaPosting') : item['@type'] === 'SocialMediaPosting')) continue;
            const url = linkInfo(item.url || item.mainEntityOfPage?.['@id'] || '');
            if (!url || url.id !== current.id) continue;
            const author = Array.isArray(item.author) ? item.author[0] : item.author;
            records.push({content_id:current.id, content_url:current.url, title:item.headline || '',
                content:item.articleBody || item.text || '', user_id:'', nickname:author?.name || '',
                publish_time:item.datePublished || '', liked_count:'', comment_count:item.commentCount ?? '',
                share_count:'', media_urls:[]});
        }
    }
}
for (const link of document.querySelectorAll('a[href]')) {
    const info = linkInfo(link.href);
    if (!info || !visible(link) || (current && current.id !== info.id)) continue;
    const card = link.closest('article, [role="article"], [data-post-id]');
    if (!card || !visible(card) || card.closest('#comment-anchor, [data-testid="comments"], [aria-label="留言"]')) continue;
    const own = selector => [...card.querySelectorAll(selector)].find(el => visible(el) && el.closest('article, [role="article"], [data-post-id]') === card);
    const body = own('[data-testid="post-content"], [data-post-content], [itemprop="articleBody"]');
    const title = own('h1, h2, [data-testid="post-title"]');
    if (!title && !body) continue;
    const profile = own('a[href^="/@"]');
    const user = profile?.getAttribute('href').match(/^\/@([A-Za-z0-9_][A-Za-z0-9_.-]{0,59})(?:\/posts)?\/?$/)?.[1] || '';
    const time = own('time[datetime]');
    records.push({content_id:info.id, content_url:info.url, title:text(title), content:text(body),
        user_id:user, nickname:text(profile), publish_time:time?.getAttribute('datetime') || '',
        liked_count:'', comment_count:'', share_count:'', forum_alias:info.forum,
        media_urls:[...new Set([...card.querySelectorAll('img[src], video[src]')].filter(visible).map(el => el.currentSrc || el.src).filter(u => /^https?:/.test(u)))]});
}
const unique = new Map();
for (const record of records) if (!unique.has(record.content_id)) unique.set(record.content_id, record);
return [...unique.values()];
}"""

EXTRACT_COMMENTS_JS = "() => {" + _JS_HELPERS + r"""
if (!current) return [];
const rows = [];
const seen = new Set();
const append = (item, parent='') => {
    if (!item || item.hidden || item.hiddenByAuthor || item.inReview || item.deleted) return;
    if (item.postId !== undefined && String(item.postId) !== current.id) return;
    const floor = /^[1-9][0-9]*$/.test(String(item.floor)) ? String(item.floor) : '';
    const parentId = String(item.parentId || parent || '');
    const id = item.id !== undefined && item.id !== null ? String(item.id) : (floor ? current.id+':'+(parentId ? parentId+':' : '')+'B'+floor : '');
    if (!id || seen.has(id) || typeof item.content !== 'string' || !item.content) return;
    seen.add(id);
    const author = item.author || {};
    rows.push({comment_id:id, content:item.content, user_id:item.withNickname === false ? '' : item.personaUid || author.personaUid || author.username || author.persona?.uid || '',
        nickname:author.displayName || item.personaNickname || item.school || '', publish_time:item.createdAt || '',
        parent_comment_id:parentId, liked_count:item.likeCount ?? '', floor:item.floor ?? '',
        comment_url:floor && !parentId ? current.url+'/b/'+floor : ''});
};
const walk = (value, depth=0) => {
    if (!value || typeof value !== 'object' || depth > 8) return;
    if (Array.isArray(value)) { for (const item of value) walk(item, depth+1); return; }
    if (typeof value.content === 'string' && (value.floor !== undefined || value.parentId !== undefined)) { append(value); return; }
    for (const item of Object.values(value)) walk(item, depth+1);
};
for (const query of queries) {
    const key = query?.queryKey || [];
    if (!/comment/i.test(String(key[0])) || !key.some(value => String(value) === current.id)) continue;
    walk(query?.state?.data);
}
for (const el of document.querySelectorAll('#comment-anchor [data-comment-id], #comment-anchor [data-floor], [data-testid="comments"] [data-comment-id], [data-testid="comments"] [data-floor]')) {
    if (!visible(el)) continue;
    const scopedPost = el.closest('[data-post-id]')?.getAttribute('data-post-id');
    if (scopedPost && scopedPost !== current.id) continue;
    const body = [...el.querySelectorAll('[data-testid="comment-content"], [data-comment-content], [itemprop="text"]')].find(visible);
    if (!body) continue;
    const profile = [...el.querySelectorAll('a[href^="/@"]')].find(visible);
    const time = el.querySelector('time[datetime]');
    append({id:el.getAttribute('data-comment-id') || undefined, floor:el.getAttribute('data-floor'),
        parentId:el.getAttribute('data-parent-comment-id') || '', content:text(body),
        author:{displayName:text(profile), username:profile?.getAttribute('href').match(/^\/@([A-Za-z0-9_.-]+)/)?.[1] || ''},
        createdAt:time?.getAttribute('datetime') || ''});
}
return rows;
}"""

EXTRACT_CREATOR_JS = "() => {" + _JS_HELPERS + r"""
const path = new URL(document.querySelector('link[rel="canonical"]')?.href || location.href).pathname;
const handle = path.match(/^\/@([A-Za-z0-9_][A-Za-z0-9_.-]{0,59})(?:\/posts)?\/?$/)?.[1];
if (!handle) return {};
for (const query of queries) {
    if (!/persona|profile/i.test(String(query?.queryKey?.[0]))) continue;
    const item = query?.state?.data;
    if (!item || (item.uid && item.uid !== handle) || (item.username && item.username !== handle)) continue;
    const id = item.uid || item.personaUid || item.username;
    if (id) return {user_id:String(id), nickname:item.nickname || item.displayName || '',
        description:item.description || '', avatar:typeof (item.avatar || item.postAvatar) === 'string' ? (item.avatar || item.postAvatar) : (item.avatar || item.postAvatar)?.url || '',
        profile_url:'https://www.dcard.tw/@'+handle};
}
const heading = [...document.querySelectorAll('main h1, [data-testid="profile-name"]')].find(visible);
if (!heading || /404|找不到|不存在/.test(text(heading))) return {};
return {user_id:handle, nickname:text(heading), profile_url:'https://www.dcard.tw/@'+handle,
    description:document.querySelector('meta[property="og:description"]')?.content || '',
    avatar:document.querySelector('meta[property="og:image"]')?.content || ''};
}"""
