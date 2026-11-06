export interface ParsedId {
  id: string
  type: 'video' | 'creator' | 'unknown'
  original: string
  isValid: boolean
}

// URL patterns for different platforms
const platformPatterns: Record<string, {
  video: RegExp[]
  creator: RegExp[]
}> = {
  xhs: {
    video: [
      /xiaohongshu\.com\/explore\/([a-zA-Z0-9]+)/,
      /xiaohongshu\.com\/discovery\/item\/([a-zA-Z0-9]+)/,
      /xhslink\.com\/([a-zA-Z0-9]+)/,
    ],
    creator: [
      /xiaohongshu\.com\/user\/profile\/([a-zA-Z0-9]+)/,
    ],
  },
  dy: {
    video: [
      /douyin\.com\/video\/(\d+)/,
      /v\.douyin\.com\/([a-zA-Z0-9]+)/,
      /iesdouyin\.com\/share\/video\/(\d+)/,
    ],
    creator: [
      /douyin\.com\/user\/([a-zA-Z0-9_-]+)/,
    ],
  },
  bili: {
    video: [
      /bilibili\.com\/video\/(BV[a-zA-Z0-9]+)/,
      /bilibili\.com\/video\/(av\d+)/,
      /b23\.tv\/([a-zA-Z0-9]+)/,
    ],
    creator: [
      /space\.bilibili\.com\/(\d+)/,
    ],
  },
  wb: {
    video: [
      /weibo\.com\/\d+\/([a-zA-Z0-9]+)/,
      /m\.weibo\.cn\/status\/(\d+)/,
    ],
    creator: [
      /weibo\.com\/u\/(\d+)/,
      /weibo\.com\/([a-zA-Z0-9]+)$/,
    ],
  },
  ks: {
    video: [
      /kuaishou\.com\/short-video\/([a-zA-Z0-9_-]+)/,
      /v\.kuaishou\.com\/([a-zA-Z0-9]+)/,
    ],
    creator: [
      /kuaishou\.com\/profile\/([a-zA-Z0-9_-]+)/,
    ],
  },
}

const FACEBOOK_RESERVED_CREATORS = new Set([
  'search', 'login', 'login.php', 'watch', 'reel', 'posts', 'groups', 'photo', 'photo.php',
  'profile.php', 'permalink.php', 'story.php', 'help', 'settings', 'marketplace', 'pages',
  'people', 'home.php', 'notifications', 'friends', 'share', 'share.php', 'sharer.php',
  'videos', 'reels', 'stories',
])
const DCARD_HANDLE = /^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,59}$/

function parseMetaUrl(input: string, platform: string): ParsedId {
  const invalid: ParsedId = { id: input, type: 'unknown', original: input, isValid: false }
  if (!input.includes('/') && !input.includes(':') && !input.includes('?')) {
    if (platform === 'threads') {
      const handle = input.replace(/^@/, '')
      if (/^[a-zA-Z0-9._]{1,30}$/.test(handle)) {
        return { id: handle, type: 'unknown', original: input, isValid: true }
      }
      return /^[a-zA-Z0-9_-]+$/.test(input)
        ? { id: input, type: 'video', original: input, isValid: true }
        : invalid
    }
    if (/^\d+_\d+$/.test(input)) {
      return { id: input, type: 'video', original: input, isValid: true }
    }
    return /^[a-zA-Z0-9.]+$/.test(input) && !FACEBOOK_RESERVED_CREATORS.has(input.toLowerCase())
      ? { id: input, type: 'unknown', original: input, isValid: true }
      : invalid
  }

  let url: URL
  try {
    url = platform === 'threads' && input.startsWith('/') && !input.startsWith('//')
      ? new URL(input, 'https://www.threads.com')
      : new URL(input)
  } catch {
    return invalid
  }
  if ((url.protocol !== 'https:' && url.protocol !== 'http:') || url.username || url.password) return invalid
  if (platform === 'threads' ? /:\d+(?:[/?#]|$)/.test(input) : !['', '80', '443'].includes(url.port)) return invalid

  if (platform === 'threads') {
    if (!['threads.net', 'www.threads.net', 'threads.com', 'www.threads.com'].includes(url.hostname)) return invalid
    const post = url.pathname.match(/^\/@([a-zA-Z0-9._]{1,30})\/post\/([a-zA-Z0-9_-]+)\/?$/)
    if (post) return { id: post[2], type: 'video', original: input, isValid: true }
    const shared = url.pathname.match(/^\/t\/([a-zA-Z0-9_-]+)\/?$/)
    if (shared) return { id: shared[1], type: 'video', original: input, isValid: true }
    const creator = url.pathname.match(/^\/@([a-zA-Z0-9._]{1,30})\/?$/)
    return creator ? { id: creator[1], type: 'creator', original: input, isValid: true } : invalid
  }

  if (!['facebook.com', 'www.facebook.com', 'm.facebook.com', 'mbasic.facebook.com', 'web.facebook.com'].includes(url.hostname)) return invalid
  const isPost = /^\/(?:posts\/[a-zA-Z0-9._-]+|[^/]+\/posts\/[a-zA-Z0-9._-]+|groups\/[^/]+\/(?:posts|permalink)\/[a-zA-Z0-9._-]+|[^/]+\/videos\/\d+|reel\/\d+)\/?$/.test(url.pathname)
    || (/^\/(?:permalink|story)\.php$/.test(url.pathname) && /^[a-zA-Z0-9._-]+$/.test(url.searchParams.get('story_fbid') || '') && /^\d+$/.test(url.searchParams.get('id') || ''))
    || (/^\/watch\/?$/.test(url.pathname) && /^\d+$/.test(url.searchParams.get('v') || ''))
    || (/^\/photo(?:\.php)?\/?$/.test(url.pathname) && /^\d+$/.test(url.searchParams.get('fbid') || ''))
  if (isPost) return { id: input, type: 'video', original: input, isValid: true }
  if (url.pathname === '/profile.php' && /^\d+$/.test(url.searchParams.get('id') || '')) {
    return { id: url.searchParams.get('id')!, type: 'creator', original: input, isValid: true }
  }
  const namedProfile = url.pathname.match(/^\/(?:people|pages)\/[^/]+\/(\d+)\/?$/)
  if (namedProfile) return { id: namedProfile[1], type: 'creator', original: input, isValid: true }
  const creator = url.pathname.match(/^\/([a-zA-Z0-9.]+)\/?$/)
  return creator && !FACEBOOK_RESERVED_CREATORS.has(creator[1].toLowerCase())
    ? { id: creator[1], type: 'creator', original: input, isValid: true }
    : invalid
}

function parseDcardUrl(input: string): ParsedId {
  const invalid: ParsedId = { id: input, type: 'unknown', original: input, isValid: false }
  if (/^[1-9]\d*$/.test(input)) {
    return { id: input, type: 'video', original: input, isValid: true }
  }
  if (input.startsWith('@') && DCARD_HANDLE.test(input.slice(1))) {
    return { id: input.slice(1), type: 'creator', original: input, isValid: true }
  }
  if (DCARD_HANDLE.test(input) && !/^\d+$/.test(input)) {
    return { id: input, type: 'creator', original: input, isValid: true }
  }

  let url: URL
  try {
    url = new URL(input)
  } catch {
    return invalid
  }
  const authority = input.match(/^https?:\/\/([^/?#]*)/i)?.[1] || ''
  if (!authority || (url.protocol !== 'https:' && url.protocol !== 'http:') || url.username || url.password
    || authority.includes(':') || !['dcard.tw', 'www.dcard.tw'].includes(url.hostname)) return invalid

  let path: string
  try {
    path = decodeURIComponent(url.pathname)
  } catch {
    return invalid
  }
  const post = path.match(/^\/(?:f\/[a-zA-Z0-9_.-]+\/)?p\/([1-9]\d*)(?:-[^/]+)?\/?$/)
  if (post) return { id: post[1], type: 'video', original: input, isValid: true }
  const creator = path.match(/^\/@([a-zA-Z0-9_][a-zA-Z0-9_.-]{0,59})(?:\/posts)?\/?$/)
  return creator ? { id: creator[1], type: 'creator', original: input, isValid: true } : invalid
}

export function parseUrl(input: string, platform: string): ParsedId {
  const trimmed = input.trim()
  if (platform === 'threads' || platform === 'facebook') return parseMetaUrl(trimmed, platform)
  if (platform === 'dcard') return parseDcardUrl(trimmed)

  // If it's just an ID (no URL structure), return as unknown type
  if (!trimmed.includes('/') && !trimmed.includes('.')) {
    return {
      id: trimmed,
      type: 'unknown',
      original: trimmed,
      isValid: trimmed.length > 0,
    }
  }

  const patterns = platformPatterns[platform]
  if (!patterns) {
    return {
      id: trimmed,
      type: 'unknown',
      original: trimmed,
      isValid: false,
    }
  }

  // Try video patterns
  for (const pattern of patterns.video) {
    const match = trimmed.match(pattern)
    if (match && match[1]) {
      return {
        id: match[1],
        type: 'video',
        original: trimmed,
        isValid: true,
      }
    }
  }

  // Try creator patterns
  for (const pattern of patterns.creator) {
    const match = trimmed.match(pattern)
    if (match && match[1]) {
      return {
        id: match[1],
        type: 'creator',
        original: trimmed,
        isValid: true,
      }
    }
  }

  // Fallback: try to extract any ID-like segment
  const urlMatch = trimmed.match(/([a-zA-Z0-9_-]{6,})/)
  if (urlMatch) {
    return {
      id: urlMatch[1],
      type: 'unknown',
      original: trimmed,
      isValid: false,
    }
  }

  return {
    id: trimmed,
    type: 'unknown',
    original: trimmed,
    isValid: false,
  }
}

export function parseMultipleUrls(input: string, platform: string): ParsedId[] {
  if (!input.trim()) return []

  const items = input
    .split(/[,\n]+/)
    .map(s => s.trim())
    .filter(Boolean)

  return items.map(item => parseUrl(item, platform))
}
