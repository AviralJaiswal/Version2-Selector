import React from 'react'

export function FormattedText({ content }) {
  if (!content) return null
  const lines = content.split('\n')

  return (
    <div className="formatted-chat-content" style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
      {lines.map((line, lineIdx) => {
        const trimmed = line.trim()
        if (!trimmed) return null

        const parseInline = (text) => {
          const cleanText = text.replace(/\*\*\s*(.*?)\s*\*\*/g, '**$1**')
          const parts = cleanText.split(/(\*\*.*?\*\*)/g)
          return parts.map((part, pIdx) => {
            if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
              return <strong key={pIdx} style={{ fontWeight: '700', color: 'inherit' }}>{part.slice(2, -2)}</strong>
            }
            return part
          })
        }

        if (trimmed.startsWith('* ') || trimmed.startsWith('- ') || trimmed.startsWith('• ')) {
          const bulletText = trimmed.replace(/^[\*\-\•]\s*/, '')
          return (
            <div key={lineIdx} style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', lineHeight: '1.4' }}>
              <span style={{ fontWeight: 'bold', flexShrink: 0, color: 'inherit' }}>•</span>
              <div style={{ flex: 1 }}>{parseInline(bulletText)}</div>
            </div>
          )
        }

        return (
          <p key={lineIdx} style={{ margin: 0, padding: 0, lineHeight: '1.4', background: 'transparent', border: 'none', color: 'inherit' }}>
            {parseInline(line)}
          </p>
        )
      })}
    </div>
  )
}
