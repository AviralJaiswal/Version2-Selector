import React, { useState } from 'react'
import { Routes, Route, useNavigate, Navigate } from 'react-router-dom'
import { CircleHelp, Sparkles, Home, Wifi, UserRound } from 'lucide-react'
import { LandingView } from './views/LandingView'
import { GeneralChatView } from './views/GeneralChatView'
import { ExistingChatView } from './views/ExistingChatView'
import { useLanguage } from './context/LanguageContext'

export function App() {
  const navigate = useNavigate()
  const [theme, setTheme] = useState('light')
  const { t } = useLanguage()

  const goHome = () => navigate('/home')

  return (
    <div className={`app-shell ${theme === 'dark' ? 'dark-mode' : ''}`}>
      <header className="topbar">
        {/* Brand Container */}
        <div className="brand brand-interactive" onClick={goHome}>
          <div className="prodapt-brand-logo">
            <span className="prodapt-brand-text">Prodapt</span>
            <svg width="10" height="10" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg" className="prodapt-mark-svg">
              <polygon points="0,0 12,0 12,12" fill="#E31B23" />
            </svg>
          </div>
          <span className="brand-divider">|</span>
          <span className="brand-title">Signal Selector</span>
          <span className="brand-ai-badge">
            <Sparkles size={13} /> Telecom AI
          </span>
        </div>

        {/* Live Radar Status Indicator */}
        <div className="top-status">
          <div className="live-status-badge">
            <span className="radar-ping" />
            <span className="status-dot green-dot" />
            <span className="status-text">{t('online')}</span>
          </div>
          <span className="help" title="Telecom AI Assistant Help"><CircleHelp size={16} /></span>
        </div>
      </header>

      <Routes>
        <Route path="/" element={<Navigate to="/home" replace />} />
        <Route path="/home" element={<LandingView setView={(v) => navigate(v === 'landing' ? '/home' : `/${v}`)} theme={theme} setTheme={setTheme} />} />
        <Route path="/general" element={<GeneralChatView onBack={goHome} />} />
        <Route path="/existing" element={<ExistingChatView onBack={goHome} />} />
        <Route path="*" element={<Navigate to="/home" replace />} />
      </Routes>

      <footer>© 2026 Signal Selector <span>•</span> Powered by Prodapt Telecom AI</footer>
    </div>
  )
}

