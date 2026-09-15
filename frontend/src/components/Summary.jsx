import React from 'react'

export function Summary({ icon, label, title, detail }) {
  return (
    <div className="summary-row">
      <span className="summary-icon">{icon}</span>
      <div>
        <small>{label}</small>
        <strong>{title}</strong>
        <span>{detail}</span>
      </div>
    </div>
  )
}
