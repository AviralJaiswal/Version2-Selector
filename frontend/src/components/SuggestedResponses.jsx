import React from 'react'
import { Sparkles, Bot } from 'lucide-react'

export function SuggestedResponses({ followups, onSelect, busy }) {
  if (!followups || followups.length === 0) return null

  return (
    <div className="dynamic-llm-suggestions" style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px dashed #FECDD3' }}>
      <div style={{ fontSize: '11px', fontWeight: '700', color: '#94A3B8', display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '6px' }}>
        <Sparkles size={12} style={{ color: '#E31B23' }} /> Suggested Responses:
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
        {followups.map((sug, sIdx) => (
          <button
            key={sIdx}
            type="button"
            disabled={busy}
            onClick={() => onSelect(sug)}
            style={{
              background: '#FFFFFF',
              border: '1px solid #FECDD3',
              color: '#991B1B',
              borderRadius: '16px',
              padding: '6px 12px',
              fontSize: '11px',
              fontWeight: '600',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              boxShadow: '0 1px 3px rgba(227,27,35,0.06)',
              transition: 'all 0.2s ease'
            }}
            onMouseOver={(e) => {
              e.currentTarget.style.borderColor = '#E31B23'
              e.currentTarget.style.background = '#FFF1F2'
            }}
            onMouseOut={(e) => {
              e.currentTarget.style.borderColor = '#FECDD3'
              e.currentTarget.style.background = '#FFFFFF'
            }}
          >
            <Bot size={12} style={{ color: '#E31B23' }} /> {sug}
          </button>
        ))}
      </div>
    </div>
  )
}
