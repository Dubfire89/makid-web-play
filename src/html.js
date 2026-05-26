export function textValue(value, emptyText = '-') {
  if (value === null || value === undefined || value === '') return emptyText

  if (Array.isArray(value)) {
    const text = value
      .filter(item => item !== null && item !== undefined && item !== '')
      .map(String)
      .join(', ')

    return text || emptyText
  }

  return String(value)
}

export function escapeHtml(value, emptyText = '-') {
  return textValue(value, emptyText).replace(/[&<>"']/g, character => {
    if (character === '&') return '&amp;'
    if (character === '<') return '&lt;'
    if (character === '>') return '&gt;'
    if (character === '"') return '&quot;'
    return '&#39;'
  })
}
