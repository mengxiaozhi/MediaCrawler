// Copyright (c) 2025 relakkes@gmail.com
// Part of MediaCrawler; licensed under NON-COMMERCIAL LEARNING LICENSE 1.1.

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

// Load the actual TypeScript implementation without adding a test framework.
const source = await readFile(new URL('../src/lib/urlParser.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
})
const { parseUrl, parseMultipleUrls } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`
)

test('Threads accepts current and legacy permalinks and shared shortcodes', () => {
  for (const input of [
    'https://www.threads.com/@alice/post/ABC-123_',
    'https://threads.net/@alice/post/ABC-123_?x=1',
    'https://www.threads.com/t/ABC-123_',
    'https://threads.net/t/ABC-123_/',
    '/t/ABC-123_',
    'ABC-123_',
  ]) {
    const result = parseUrl(input, 'threads')
    assert.equal(result.isValid, true, input)
    assert.equal(result.id, 'ABC-123_', input)
    assert.equal(result.type, 'video', input)
  }
})

test('Threads usernames remain valid without assuming they are posts', () => {
  for (const input of ['@alice', 'alice_name', 'alice.name']) {
    const result = parseUrl(input, 'threads')
    assert.equal(result.isValid, true, input)
    assert.equal(result.type, 'unknown', input)
  }
  assert.equal(parseUrl('https://www.threads.com/@alice', 'threads').type, 'creator')
  assert.equal(parseUrl(`https://www.threads.com/@${'a'.repeat(31)}`, 'threads').isValid, false)
})

test('Facebook keeps owner and query context in post identifiers', () => {
  for (const input of [
    'https://www.facebook.com/page/posts/123',
    'https://m.facebook.com/posts/123',
    'https://www.facebook.com/groups/12/posts/34',
    'https://www.facebook.com/groups/12/permalink/34',
    'https://www.facebook.com/permalink.php?story_fbid=123&id=45',
    'https://www.facebook.com/story.php?story_fbid=pfbid123&id=45',
    'https://www.facebook.com/reel/123',
    'https://web.facebook.com/page/videos/123',
    'https://www.facebook.com/watch/?v=123',
    'https://www.facebook.com/photo.php?fbid=123',
    '123_456',
  ]) {
    const result = parseUrl(input, 'facebook')
    assert.equal(result.isValid, true, input)
    assert.equal(result.type, 'video', input)
    assert.equal(result.id, input, input)
  }
})

test('Facebook accepts profile forms and rejects routes as creators', () => {
  for (const input of [
    'alice.name', '12345', 'https://www.facebook.com/alice.name',
    'https://www.facebook.com/profile.php?id=45',
    'https://www.facebook.com/people/Alice/45',
    'https://www.facebook.com/pages/Page/45',
  ]) assert.equal(parseUrl(input, 'facebook').isValid, true, input)

  for (const name of [
    'search', 'LOGIN', 'login.php', 'watch', 'reel', 'posts', 'groups', 'photo',
    'photo.php', 'profile.php', 'permalink.php', 'story.php', 'help', 'settings',
    'marketplace', 'pages', 'people', 'home.php', 'notifications', 'friends',
    'share', 'share.php', 'sharer.php', 'videos', 'reels', 'stories',
  ]) {
    assert.equal(parseUrl(name, 'facebook').isValid, false, name)
    assert.equal(parseUrl(`https://www.facebook.com/${name}`, 'facebook').isValid, false, name)
  }
})

test('invalid hosts, credential URLs and incomplete Facebook post links are rejected', () => {
  for (const [input, platform] of [
    ['https://threads.com.attacker.test/@alice/post/ABC', 'threads'],
    ['https://evil.test/facebook.com/page/posts/123', 'facebook'],
    ['https://user:secret@www.facebook.com/page/posts/123', 'facebook'],
    ['https://www.threads.com:443/@alice/post/ABC', 'threads'],
    ['https://www.facebook.com:8080/page/posts/123', 'facebook'],
    ['https://www.facebook.com/profile.php?id=alice', 'facebook'],
    ['https://www.facebook.com/watch/?v=abc', 'facebook'],
    ['https://www.facebook.com/permalink.php?story_fbid=123', 'facebook'],
    ['https://www.facebook.com/reel/abc', 'facebook'],
    ['@alice', 'facebook'],
  ]) assert.equal(parseUrl(input, platform).isValid, false, input)
})

test('multiple pasted IDs accept comma and newline separators', () => {
  assert.deepEqual(
    parseMultipleUrls('@alice\n@bob, https://www.threads.com/t/ABC-123_', 'threads').map(row => row.id),
    ['alice', 'bob', 'ABC-123_'],
  )
})

test('Dcard accepts article IDs, forum URLs, and title slugs', () => {
  for (const input of [
    '123456789',
    'https://www.dcard.tw/f/talk/p/123456789',
    'https://dcard.tw/f/talk/p/123456789-文章標題?cid=1',
    'http://www.dcard.tw/p/123456789',
    'https://www.dcard.tw/p/123456789-a-title/',
  ]) {
    const result = parseUrl(input, 'dcard')
    assert.equal(result.isValid, true, input)
    assert.equal(result.type, 'video', input)
    assert.equal(result.id, '123456789', input)
    assert.equal(result.original, input)
  }
})

test('Dcard accepts creator usernames and their posts routes', () => {
  for (const input of [
    'alice.name', '@alice.name', 'https://www.dcard.tw/@alice.name',
    'https://dcard.tw/@alice.name/posts?tab=posts',
  ]) {
    const result = parseUrl(input, 'dcard')
    assert.equal(result.isValid, true, input)
    assert.equal(result.type, 'creator', input)
    assert.equal(result.id, 'alice.name', input)
  }
  assert.equal(parseUrl('@123', 'dcard').type, 'creator')
})

test('Dcard rejects unrelated domains, credential URLs and malformed routes', () => {
  for (const input of [
    '', '0', '000', '-123', '.alice', '@-alice', `@${'a'.repeat(61)}`,
    'https://www.dcard.tw.attacker.test/f/talk/p/123',
    'https://evil.test/?url=https://www.dcard.tw/f/talk/p/123',
    'https://user:secret@www.dcard.tw/f/talk/p/123',
    'https://www.dcard.tw:443/f/talk/p/123',
    'https://www.dcard.tw:8080/f/talk/p/123',
    'https:dcard.tw/p/123',
    'file://www.dcard.tw/f/talk/p/123',
    'https://www.dcard.tw/f/talk',
    'https://www.dcard.tw/f/talk/p/0',
    'https://www.dcard.tw/f/talk/p/not-an-id',
    'https://www.dcard.tw/f/talk/p/123/comments',
    'https://www.dcard.tw/f/talk/p/123-title%2Fcomments',
    'https://www.dcard.tw/@alice/followers',
  ]) assert.equal(parseUrl(input, 'dcard').isValid, false, input)
  assert.deepEqual(
    parseMultipleUrls('123\nhttps://www.dcard.tw/f/talk/p/456, @alice', 'dcard').map(row => row.id),
    ['123', '456', 'alice'],
  )
})
