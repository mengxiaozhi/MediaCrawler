# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/facebook/adapter.py
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

"""Facebook URL normalization and extraction from the browser's rendered DOM.

Only fields exposed in the current page are collected. Missing counters and
timestamps remain empty instead of being inferred from localized UI text.
"""

import re
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

PLATFORM = "facebook"
BASE_URL = "https://www.facebook.com"
COOKIE_DOMAIN = ".facebook.com"
AUTH_COOKIE_NAMES = ("c_user", "xs")
_RESERVED_CREATOR_NAMES = {
    "search", "login", "login.php", "watch", "reel", "reels", "posts", "groups",
    "photo", "photo.php", "permalink.php", "story.php", "profile.php", "help",
    "settings", "marketplace", "pages", "people", "home.php", "notifications",
    "friends", "share", "share.php", "sharer.php", "videos", "stories",
}


def _facebook_url(value: str):
    value = value.strip()
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in ("http", "https")
        or host not in ("facebook.com", "www.facebook.com", "m.facebook.com", "mbasic.facebook.com", "web.facebook.com")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 80, 443)
    ):
        raise ValueError("Expected a Facebook URL on facebook.com")
    return parsed


def normalize_post_url(value: str) -> str:
    """Accept a post/permalink/reel/video/photo URL or ``ownerID_postID``."""
    value = value.strip()
    raw = re.fullmatch(r"(\d+)_(\d+)", value)
    if raw:
        return f"{BASE_URL}/permalink.php?{urlencode({'story_fbid': raw[2], 'id': raw[1]})}"
    parsed = _facebook_url(value)
    path = parsed.path.rstrip("/")
    group_permalink = re.fullmatch(r"/groups/([^/]+)/permalink/([A-Za-z0-9._-]+)", path)
    if group_permalink:
        path = f"/groups/{group_permalink[1]}/posts/{group_permalink[2]}"
    query = parse_qs(parsed.query)
    keep = {}
    if re.fullmatch(r"/(?:[^/]+/|groups/[^/]+/)?posts/[A-Za-z0-9._-]+", path):
        pass
    elif re.fullmatch(r"/reel/\d+", path):
        pass
    elif path in ("/permalink.php", "/story.php"):
        story = query.get("story_fbid", [""])[0]
        owner = query.get("id", [""])[0]
        if not re.fullmatch(r"[A-Za-z0-9._-]+", story) or not owner.isdigit():
            raise ValueError("Facebook story URLs require story_fbid and numeric id")
        keep = {"story_fbid": story, "id": owner}
    elif path == "/watch":
        video = query.get("v", [""])[0]
        if not video.isdigit():
            raise ValueError("Facebook watch URLs require a numeric v parameter")
        path += "/"
        keep = {"v": video}
    elif re.fullmatch(r"/[^/]+/videos/\d+", path):
        pass
    elif path in ("/photo", "/photo.php"):
        photo = query.get("fbid", [""])[0]
        if not photo.isdigit():
            raise ValueError("Facebook photo URLs require a numeric fbid parameter")
        keep = {"fbid": photo}
    else:
        raise ValueError("Use a Facebook post, permalink, reel, watch or photo URL")
    return urlunsplit(("https", "www.facebook.com", path, urlencode(keep), ""))


def post_id(value: str) -> str:
    parsed = urlsplit(normalize_post_url(value))
    query = parse_qs(parsed.query)
    for key in ("story_fbid", "v", "fbid"):
        if key in query:
            return query[key][0]
    return parsed.path.rstrip("/").split("/")[-1]


def normalize_creator_url(value: str) -> str:
    """Accept a profile/Page URL, numeric identifier or username."""
    value = value.strip()
    if not value:
        raise ValueError("Facebook creator cannot be empty")
    if re.fullmatch(r"[A-Za-z0-9.]+", value):
        if value.lower() in _RESERVED_CREATOR_NAMES:
            raise ValueError("Use a Facebook profile or Page URL/username")
        return f"{BASE_URL}/{value}"
    parsed = _facebook_url(value)
    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)
    if path == "/profile.php" and query.get("id", [""])[0].isdigit():
        return f"{BASE_URL}/profile.php?{urlencode({'id': query['id'][0]})}"
    if re.fullmatch(r"/people/[^/]+/\d+", path) or re.fullmatch(r"/pages/[^/]+/\d+", path):
        return f"{BASE_URL}/{path.split('/')[-1]}"
    if not re.fullmatch(r"/[A-Za-z0-9.]+", path) or path[1:].lower() in _RESERVED_CREATOR_NAMES:
        raise ValueError("Use a Facebook profile or Page URL/username")
    return f"{BASE_URL}{path}"


def search_url(keyword: str) -> str:
    return f"{BASE_URL}/search/posts/?q={quote(keyword, safe='')}"


# These functions are evaluated inside the user's crawler browser, never against
# private APIs. Attribute names are preferred over translated button labels.
_JS_HELPERS = r"""
const text = el => el ? (el.innerText || el.textContent || '').trim() : '';
const visible = el => {
    if (!el || el.closest('[hidden], [aria-hidden="true"]')) return false;
    if (el.tagName === 'SOURCE') return visible(el.parentElement);
    if (!el.getClientRects().length) return false;
    for (let node = el; node instanceof Element; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse' || style.opacity === '0') return false;
    }
    return true;
};
const absolute = href => { try { return new URL(href, location.href); } catch { return null; } };
const facebook = u => u && /(^|\.)facebook\.com$/.test(u.hostname);
const postLink = a => {
    const u = absolute(a.getAttribute('href'));
    if (!facebook(u) || u.searchParams.has('comment_id') || u.searchParams.has('reply_comment_id')) return null;
    u.pathname = u.pathname.replace(/^(\/groups\/[^/]+)\/permalink\/([A-Za-z0-9._-]+)\/?$/, '$1/posts/$2');
    let id = '';
    if (/\/(?:posts|videos)\/[A-Za-z0-9._-]+\/?$/.test(u.pathname) || /^\/reel\/\d+\/?$/.test(u.pathname)) {
        id = u.pathname.replace(/\/$/, '').split('/').pop();
    } else if (/^\/(?:permalink|story)\.php$/.test(u.pathname)) {
        id = u.searchParams.get('story_fbid') || '';
    } else if (/^\/watch\/?$/.test(u.pathname)) {
        id = u.searchParams.get('v') || '';
    } else if (/^\/(?:photo|photo\.php)\/?$/.test(u.pathname)) {
        id = u.searchParams.get('fbid') || '';
    }
    if (!id) return null;
    const keep = new URLSearchParams();
    for (const key of ['story_fbid', 'id', 'v', 'fbid']) if (u.searchParams.has(key)) keep.set(key, u.searchParams.get(key));
    return {id, url: 'https://www.facebook.com' + u.pathname + (keep.size ? '?' + keep.toString() : '')};
};
const userId = a => {
    const u = a && absolute(a.getAttribute('href'));
    if (!facebook(u)) return '';
    return u.pathname === '/profile.php' ? (u.searchParams.get('id') || '') : u.pathname.replace(/^\/+|\/+$/g, '').split('/').pop();
};
const own = (el, selector) => [...el.querySelectorAll(selector)].filter(node => node.closest('[role="article"]') === el && visible(node));
const author = el => own(el, 'h2 a[href], h3 a[href], h4 a[href], strong a[href], a[data-hovercard]')
    .find(a => facebook(absolute(a.getAttribute('href'))) && !postLink(a));
const timestamp = el => {
    const t = own(el, 'time[datetime], [data-utime]')[0];
    return t ? (t.getAttribute('datetime') || t.getAttribute('data-utime') || '') : '';
};
"""

EXTRACT_POSTS_JS = "() => {" + _JS_HELPERS + r"""
const seen = new Set();
const result = [];
for (const article of document.querySelectorAll('[role="article"]')) {
    if (!visible(article)) continue;
    const message = own(article, '[data-ad-preview="message"], [data-ad-comet-preview="message"], [data-testid="post_message"]')[0];
    const links = own(article, 'a[href]').map(postLink).filter(Boolean);
    const link = links[0];
    if (!link || seen.has(link.id)) continue;
    const by = author(article);
    const media = own(article, 'img[src], video[src], video source[src]')
        .filter(el => el.tagName !== 'IMG' || (el.width > 100 && el.height > 100))
        .map(el => el.currentSrc || el.src).filter(src => /^https?:/.test(src));
    if (!message && !media.length) continue;
    seen.add(link.id);
    result.push({content_id: link.id, content_url: link.url,
        user_id: userId(by), nickname: text(by), content: text(message),
        publish_time: timestamp(article), liked_count: '', comment_count: '', share_count: '',
        media_urls: [...new Set(media)]});
}
return result;
}"""

EXTRACT_COMMENTS_JS = "() => {" + _JS_HELPERS + r"""
const seen = new Set();
const result = [];
const current = postLink({getAttribute: () => location.href});
for (const article of document.querySelectorAll('[role="article"]')) {
    if (!visible(article)) continue;
    const link = own(article, 'a[href]').map(a => absolute(a.getAttribute('href')))
        .find(u => facebook(u) && u.searchParams.has('comment_id'));
    if (!link) continue;
    const postURL = new URL(link.href);
    postURL.searchParams.delete('comment_id');
    postURL.searchParams.delete('reply_comment_id');
    const target = postLink({getAttribute: () => postURL.href});
    if (current && (!target || target.id !== current.id)) continue;
    const top = link.searchParams.get('comment_id');
    const reply = link.searchParams.get('reply_comment_id');
    const id = reply || top;
    if (!id || seen.has(id)) continue;
    const message = own(article, '[data-ad-preview="message"], [data-ad-comet-preview="message"], [data-testid="comment"], [data-testid="comment_message"], div[dir="auto"]')
        .find(el => text(el) && !el.closest('h2,h3,h4,strong') && !el.querySelector('a[href]'));
    if (!message) continue;
    const by = author(article);
    seen.add(id);
    result.push({comment_id: id, content: text(message), user_id: userId(by),
        nickname: text(by), publish_time: timestamp(article),
        parent_comment_id: reply ? top : ''});
}
return result;
}"""

EXTRACT_CREATOR_JS = "() => {" + _JS_HELPERS + r"""
const u = new URL(location.href);
const canonical = document.querySelector('link[rel="canonical"]');
const profile = canonical ? absolute(canonical.getAttribute('href')) : u;
const description = document.querySelector('meta[property="og:description"], meta[name="description"]');
const image = document.querySelector('meta[property="og:image"]');
return {user_id: profile.pathname === '/profile.php' ? (profile.searchParams.get('id') || '') : profile.pathname.replace(/^\/+|\/+$/g, '').split('/').pop(),
    nickname: text(document.querySelector('h1')), profile_url: profile.href,
    description: description ? description.content : '', avatar: image ? image.content : ''};
}"""
