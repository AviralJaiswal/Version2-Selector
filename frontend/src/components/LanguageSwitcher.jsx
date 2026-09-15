import React, { useState, useRef, useEffect } from 'react'
import { Languages } from 'lucide-react'
import { LANGUAGES, useLanguage } from '../context/LanguageContext'

export function LanguageSwitcher() {
  const { language, setLanguage } = useLanguage()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const onClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  const current = LANGUAGES.find((l) => l.code === language) || LANGUAGES[0]

  return (
    <div className="language-switcher" ref={ref} style={{ position: 'relative' }}>
      <button
        type="button"
        className="lang-switcher-btn"
        onClick={() => setOpen((o) => !o)}
        title="Change language"
        style={{
          display: 'flex', alignItems: 'center', gap: '4px',
          background: 'transparent', border: '1px solid rgba(128,128,128,0.3)',
          borderRadius: '6px', padding: '4px 8px', cursor: 'pointer', fontSize: '13px'
        }}
      >
        <Languages size={14} />
        <span>{current.native}</span>
      </button>
      {open && (
        <div
          className="lang-switcher-dropdown"
          style={{
            position: 'absolute', top: '100%', right: 0, marginTop: '4px',
            background: 'var(--card-bg, white)', border: '1px solid rgba(128,128,128,0.3)',
            borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.15)', zIndex: 50,
            minWidth: '140px', overflow: 'hidden'
          }}
        >
          {LANGUAGES.map((l) => (
            <button
              key={l.code}
              type="button"
              onClick={() => { setLanguage(l.code); setOpen(false) }}
              style={{
                display: 'block', width: '100%', textAlign: 'left', padding: '8px 12px',
                background: l.code === language ? 'rgba(227,27,35,0.08)' : 'transparent',
                border: 'none', cursor: 'pointer', fontSize: '13px'
              }}
            >
              {l.native} <span style={{ opacity: 0.6, fontSize: '11px' }}>({l.label})</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
