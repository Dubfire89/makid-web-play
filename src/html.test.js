import test from 'node:test'
import assert from 'node:assert/strict'

import { escapeHtml, textValue } from './html.js'

test('textValue normalizes empty and scalar values', () => {
  assert.equal(textValue(null), '-')
  assert.equal(textValue(undefined), '-')
  assert.equal(textValue(''), '-')
  assert.equal(textValue('', ''), '')
  assert.equal(textValue(120), '120')
  assert.equal(textValue(false), 'false')
})

test('textValue normalizes arrays', () => {
  assert.equal(textValue(['one', '', null, undefined, 'two']), 'one, two')
  assert.equal(textValue([null, '', undefined], 'empty'), 'empty')
})

test('escapeHtml escapes scriptable markup payloads', () => {
  assert.equal(
    escapeHtml('<img src=x onerror=alert(1)>'),
    '&lt;img src=x onerror=alert(1)&gt;'
  )
  assert.equal(
    escapeHtml('<svg><script>alert(1)</script></svg>'),
    '&lt;svg&gt;&lt;script&gt;alert(1)&lt;/script&gt;&lt;/svg&gt;'
  )
})

test('escapeHtml escapes attribute-breaking quotes and ampersands', () => {
  assert.equal(
    escapeHtml('" autofocus onfocus="alert(1)" data-x=\'y\' & done'),
    '&quot; autofocus onfocus=&quot;alert(1)&quot; data-x=&#39;y&#39; &amp; done'
  )
})

test('escapeHtml preserves fallback behavior', () => {
  assert.equal(escapeHtml(null), '-')
  assert.equal(escapeHtml(null, ''), '')
  assert.equal(escapeHtml(['<tag>', 'safe']), '&lt;tag&gt;, safe')
})
