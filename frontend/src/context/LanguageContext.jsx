import React, { createContext, useContext, useState } from 'react'

export const LANGUAGES = [
  { code: 'en', label: 'English', native: 'English' },
  { code: 'hi', label: 'Hindi', native: '\u0939\u093f\u0902\u0926\u0940' },
  { code: 'te', label: 'Telugu', native: '\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41' },
  { code: 'ta', label: 'Tamil', native: '\u0ba4\u0bae\u0bbf\u0bb4\u0bcd' },
]

// Small dictionary for static UI chrome (buttons, placeholders, labels).
// The assistant's own responses are translated server-side by the LLM -
// this is only for text that never goes through the backend.
const STRINGS = {
  en: {
    newConnection: 'New Connection',
    existingCustomer: 'Existing Customer',
    typeMessage: 'Type your message...',
    enterPhone: 'Enter your registered 10-digit mobile number...',
    askAboutPlan: 'Ask about your plan, upgrades, downgrades, or billing...',
    send: 'Send',
    back: 'Back',
    online: 'Online',
  },
  hi: {
    newConnection: '\u0928\u092f\u093e \u0915\u0928\u0947\u0915\u094d\u0936\u0928',
    existingCustomer: '\u092e\u094c\u091c\u0942\u0926\u093e \u0917\u094d\u0930\u093e\u0939\u0915',
    typeMessage: '\u0905\u092a\u0928\u093e \u0938\u0902\u0926\u0947\u0936 \u0932\u093f\u0916\u0947\u0902...',
    enterPhone: '\u0905\u092a\u0928\u093e \u092a\u0902\u091c\u0940\u0915\u0943\u0924 10-\u0905\u0902\u0915\u094b\u0902 \u0915\u093e \u092e\u094b\u092c\u093e\u0907\u0932 \u0928\u0902\u092c\u0930 \u0926\u0930\u094d\u091c \u0915\u0930\u0947\u0902...',
    askAboutPlan: '\u0905\u092a\u0928\u0947 \u092a\u094d\u0932\u093e\u0928, \u0905\u092a\u0917\u094d\u0930\u0947\u0921, \u0921\u093e\u0909\u0928\u0917\u094d\u0930\u0947\u0921, \u092f\u093e \u092c\u093f\u0932\u093f\u0902\u0917 \u0915\u0947 \u092c\u093e\u0930\u0947 \u092e\u0947\u0902 \u092a\u0942\u091b\u0947\u0902...',
    send: '\u092d\u0947\u091c\u0947\u0902',
    back: '\u0935\u093e\u092a\u0938',
    online: '\u0911\u0928\u0932\u093e\u0907\u0928',
  },
  te: {
    newConnection: '\u0c15\u0c4a\u0c24\u0c4d\u0c24 \u0c15\u0c28\u0c46\u0c15\u0c4d\u0c37\u0c28\u0c4d',
    existingCustomer: '\u0c07\u0c2a\u0c4d\u0c2a\u0c1f\u0c3f \u0c15\u0c38\u0c4d\u0c1f\u0c2e\u0c30\u0c4d',
    typeMessage: '\u0c2e\u0c40 \u0c38\u0c02\u0c26\u0c47\u0c36\u0c02 \u0c1f\u0c48\u0c2a\u0c4d \u0c1a\u0c47\u0c2f\u0c02\u0c21\u0c3f...',
    enterPhone: '\u0c2e\u0c40 \u0c28\u0c2e\u0c4b\u0c26\u0c46\u0c48\u0c28 10-\u0c05\u0c02\u0c15\u0c46\u0c32 \u0c2e\u0c4a\u0c2c\u0c48\u0c32\u0c4d \u0c28\u0c02\u0c2c\u0c30\u0c4d\u200c\u0c28\u0c41 \u0c28\u0c2e\u0c4b\u0c26\u0c41 \u0c1a\u0c47\u0c2f\u0c02\u0c21\u0c3f...',
    askAboutPlan: '\u0c2e\u0c40 \u0c2a\u0c4d\u0c32\u0c3e\u0c28\u0c4d, \u0c05\u0c2a\u0c4d\u0c17\u0c4d\u0c30\u0c47\u0c21\u0c4d\u0c32\u0c41, \u0c21\u0c4c\u0c28\u0c4d\u200c\u0c17\u0c4d\u0c30\u0c47\u0c21\u0c4d\u0c32\u0c41 \u0c32\u0c47\u0c26\u0c3e \u0c2c\u0c3f\u0c32\u0c4d\u0c32\u0c3f\u0c02\u0c17\u0c4d \u0c17\u0c41\u0c30\u0c3f\u0c02\u0c1a\u0c3f \u0c05\u0c21\u0c17\u0c02\u0c21\u0c3f...',
    send: '\u0c2a\u0c02\u0c2a\u0c41',
    back: '\u0c35\u0c46\u0c28\u0c15\u0c15\u0c3f',
    online: '\u0c06\u0c28\u0c4d\u200c\u0c32\u0c48\u0c28\u0c4d',
  },
  ta: {
    newConnection: '\u0baa\u0bc1\u0ba4\u0bbf\u0baf \u0b87\u0ba3\u0bc8\u0baa\u0bcd\u0baa\u0bc1',
    existingCustomer: '\u0b87\u0baa\u0bcd\u0baa\u0bc7\u0ba4\u0bc7\u0baf\u0bc1\u0bb3\u0bcd\u0bb3 \u0bb5\u0bbe\u0b9f\u0bbf\u0b95\u0bcd\u0b95\u0bc8\u0baf\u0bbe\u0bb3\u0bb0\u0bcd',
    typeMessage: '\u0b89\u0b99\u0bcd\u0b95\u0bb3\u0bcd \u0b9a\u0b9a\u0bc7\u0b9a\u0ba4\u0bcd\u0ba4\u0bc8 \u0b95\u0bcd\u0b95\u0bc1\u0b95\u0bcd\u0b95\u0bc1...',
    enterPhone: '\u0baa\u0ba4\u0bbf\u0bb5\u0bc1 \u0b9a\u0bc6\u0baf\u0bcd\u0baf\u0baa\u0bcd\u0baa\u0b9f\u0bcd\u0b9f 10-\u0b87\u0bb2\u0b95\u0bcd\u0b95 \u0bae\u0bca\u0baa\u0bc8\u0bb2\u0bcd \u0ba8\u0bae\u0bcd\u0baa\u0bb0\u0bc8 \u0b89\u0bb3\u0bcd\u0bb3\u0bbf\u0b9f\u0bb5\u0bc1\u0bae\u0bcd...',
    askAboutPlan: '\u0b89\u0b99\u0bcd\u0b95\u0bb3\u0bcd \u0ba4\u0bbf\u0b9f\u0bcd\u0b9f\u0bae\u0bcd, \u0bae\u0bc7\u0bae\u0bcd\u0baa\u0bcd\u0baa\u0b9f\u0bc1\u0ba4\u0bcd\u0ba4\u0bb2\u0bcd, \u0b95\u0bc0\u0bb4\u0bcd\u0baa\u0bcd\u0baa\u0b9f\u0bc1\u0ba4\u0bcd\u0ba4\u0bb2\u0bcd \u0b85\u0bb2\u0bcd\u0bb2\u0ba4\u0bc1 \u0baa\u0bbf\u0bb2\u0bcd\u0bb2\u0bbf\u0b99\u0bcd \u0baa\u0bb1\u0bcd\u0bb1\u0bbf \u0b95\u0bc7\u0bb3\u0bc1\u0b99\u0bcd\u0b95\u0bb3\u0bcd...',
    send: '\u0b85\u0ba9\u0bc1\u0baa\u0bcd\u0baa\u0bc1',
    back: '\u0baa\u0bbf\u0ba9\u0bcd',
    online: '\u0b87\u0ba3\u0bc8\u0baf\u0ba4\u0bcd\u0ba4\u0bbf\u0bb2\u0bcd',
  },
}

const LanguageContext = createContext(null)

export function LanguageProvider({ children }) {
  const [language, setLanguage] = useState(() => localStorage.getItem('ss_language') || 'en')

  const changeLanguage = (code) => {
    setLanguage(code)
    try { localStorage.setItem('ss_language', code) } catch (e) { /* ignore storage errors */ }
  }

  const t = (key) => (STRINGS[language] && STRINGS[language][key]) || STRINGS.en[key] || key

  return (
    <LanguageContext.Provider value={{ language, setLanguage: changeLanguage, t }}>
      {children}
    </LanguageContext.Provider>
  )
}

export function useLanguage() {
  const ctx = useContext(LanguageContext)
  if (!ctx) throw new Error('useLanguage must be used within a LanguageProvider')
  return ctx
}
