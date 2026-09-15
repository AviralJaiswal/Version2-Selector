import React, { useState, useEffect } from 'react'
import { UserRound, CheckCircle2, ChevronRight, Pencil, AlertCircle } from 'lucide-react'
import { validateCustomerEmail } from '../utils/validation'

export function SavedCustomerCard({ custName, custPhone, custEmail, onSave, busy, readOnly }) {
  const [isEditing, setIsEditing] = useState(false)
  const [editForm, setEditForm] = useState({ name: custName, phone: custPhone, email: custEmail })
  const [err, setErr] = useState('')

  useEffect(() => {
    setEditForm({ name: custName, phone: custPhone, email: custEmail })
  }, [custName, custPhone, custEmail])

  useEffect(() => {
    if (readOnly) {
      setIsEditing(false)
    }
  }, [readOnly])

  const handleSave = (e) => {
    e.preventDefault()
    const trimmedName = editForm.name.trim()
    const trimmedPhone = editForm.phone.trim()
    const trimmedEmail = editForm.email.trim()

    if (!trimmedName || !/^[a-zA-Z\s]+$/.test(trimmedName)) {
      setErr('Name must contain alphabets and spaces only.')
      return
    }
    if (!/^\d{10}$/.test(trimmedPhone) || /^(\d)\1{9}$/.test(trimmedPhone)) {
      setErr('Please enter a valid 10-digit mobile number.')
      return
    }

    const emailVal = validateCustomerEmail(trimmedEmail)
    if (!emailVal.isValid) {
      setErr(emailVal.error)
      return
    }

    setErr('')
    setIsEditing(false)
    if (onSave) {
      onSave({ name: trimmedName, phone: trimmedPhone, email: trimmedEmail })
    }
  }

  if (isEditing) {
    return (
      <div className="other-message assistant" style={{ marginTop: '12px' }}>
        <span><UserRound size={14} /></span>
        <div className="message-content customer-card-content" style={{ width: '540px', maxWidth: '100%', padding: '16px', background: '#FFFFFF', border: '2px solid #E31B23', borderRadius: '14px', boxShadow: '0 4px 14px rgba(227, 27, 35, 0.12)', boxSizing: 'border-box' }}>
          <div className="customer-form-title" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: '#B80E16', fontSize: '13px', fontWeight: '700', marginBottom: '8px' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <UserRound size={15} style={{ color: '#E31B23' }} /> Edit Customer Details
            </span>
            <button
              type="button"
              onClick={() => setIsEditing(false)}
              style={{ background: 'transparent', border: 'none', color: '#64748B', fontSize: '11px', fontWeight: '600', cursor: 'pointer' }}
            >
              Cancel
            </button>
          </div>
          {err && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#DC2626', background: '#FEF2F2', border: '1px solid #FCA5A5', padding: '8px 12px', borderRadius: '8px', fontSize: '11px', fontWeight: '600', marginBottom: '10px' }}>
              <AlertCircle size={14} style={{ flexShrink: 0 }} /> {err}
            </div>
          )}
          <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '11px', fontWeight: '700', color: '#334155' }}>Name</label>
              <input
                value={editForm.name}
                onChange={(e) => {
                  setEditForm({ ...editForm, name: e.target.value.replace(/[^a-zA-Z\s]/g, '') })
                  if (err) setErr('')
                }}
                placeholder="Full name"
                required
                style={{ width: '100%', border: '1px solid #CBD5E1', borderRadius: '10px', padding: '9px 12px', fontSize: '12px', outline: 'none', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '11px', fontWeight: '700', color: '#334155' }}>Phone</label>
              <input
                value={editForm.phone}
                onChange={(e) => {
                  setEditForm({ ...editForm, phone: e.target.value.replace(/\D/g, '').slice(0, 10) })
                  if (err) setErr('')
                }}
                placeholder="10-digit mobile number"
                inputMode="numeric"
                required
                style={{ width: '100%', border: '1px solid #CBD5E1', borderRadius: '10px', padding: '9px 12px', fontSize: '12px', outline: 'none', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '11px', fontWeight: '700', color: '#334155' }}>Email</label>
              <input
                value={editForm.email}
                onChange={(e) => {
                  setEditForm({ ...editForm, email: e.target.value })
                  if (err) setErr('')
                }}
                placeholder="Enter email address"
                type="email"
                required
                style={{
                  width: '100%',
                  border: '1px solid #CBD5E1',
                  borderRadius: '10px',
                  padding: '9px 12px',
                  fontSize: '12px',
                  outline: 'none',
                  boxSizing: 'border-box',
                  background: '#FFFFFF'
                }}
              />
            </div>
            <button
              type="submit"
              disabled={busy}
              style={{
                width: '100%',
                marginTop: '6px',
                padding: '10px 14px',
                borderRadius: '10px',
                fontWeight: '700',
                fontSize: '12px',
                cursor: 'pointer',
                background: 'linear-gradient(135deg, #E31B23 0%, #B80E16 100%)',
                color: '#FFFFFF',
                border: 'none',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
                boxShadow: '0 4px 12px rgba(227, 27, 35, 0.25)'
              }}
            >
              Update Details <CheckCircle2 size={14} />
            </button>
          </form>
        </div>
      </div>
    )
  }

  return (
    <div className="other-message assistant" style={{ marginTop: '12px' }}>
      <span><UserRound size={14} /></span>
      <div className="message-content customer-card-content" style={{ width: '540px', maxWidth: '100%', padding: '16px', background: 'linear-gradient(135deg, #FFF5F5 0%, #FFFFFF 100%)', border: '2px solid #E31B23', borderRadius: '14px', boxShadow: '0 4px 12px rgba(227, 27, 35, 0.08)', boxSizing: 'border-box' }}>
        <div className="customer-form-title" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: '#B80E16', fontSize: '13px', fontWeight: '700', marginBottom: '6px' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <UserRound size={15} style={{ color: '#E31B23' }} /> Customer Details
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ background: '#FFF0F1', color: '#991B1B', border: '1px solid #FECDD3', padding: '3px 10px', borderRadius: '12px', fontSize: '10px', fontWeight: '700', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <CheckCircle2 size={13} style={{ color: '#E31B23' }} /> Saved ✓
            </span>
            {!readOnly && (
              <button
                type="button"
                onClick={() => setIsEditing(true)}
                style={{
                  background: '#FFFFFF',
                  color: '#B80E16',
                  border: '1px solid #FCA5A5',
                  borderRadius: '10px',
                  padding: '3px 9px',
                  fontSize: '11px',
                  fontWeight: '700',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
                }}
              >
                <Pencil size={11} /> Edit
              </button>
            )}
          </div>
        </div>
        <p style={{ margin: '2px 0 10px', color: '#64748B', fontSize: '11px' }}>Your contact information has been verified and recorded.</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#FFFFFF', padding: '8px 12px', borderRadius: '8px', border: '1px solid #FEE2E2' }}>
            <span style={{ fontSize: '11px', color: '#64748B', fontWeight: '700' }}>Name:</span>
            <strong style={{ fontSize: '12px', color: '#1E293B' }}>{editForm.name}</strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#FFFFFF', padding: '8px 12px', borderRadius: '8px', border: '1px solid #FEE2E2' }}>
            <span style={{ fontSize: '11px', color: '#64748B', fontWeight: '700' }}>Phone:</span>
            <strong style={{ fontSize: '12px', color: '#1E293B' }}>{editForm.phone}</strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#FFFFFF', padding: '8px 12px', borderRadius: '8px', border: '1px solid #FEE2E2' }}>
            <span style={{ fontSize: '11px', color: '#64748B', fontWeight: '700' }}>Email:</span>
            <strong style={{ fontSize: '12px', color: '#1E293B', wordBreak: 'break-all' }}>{editForm.email}</strong>
          </div>
        </div>
      </div>
    </div>
  )
}

export function CustomerFormCard({ selectedPlanName, customer, setCustomer, submitCustomer, busy }) {
  const [localError, setLocalError] = useState('')

  const handleSubmit = (e) => {
    e.preventDefault()
    
    const trimmedName = customer.name ? customer.name.trim() : ''
    const trimmedPhone = customer.phone ? customer.phone.trim() : ''
    const trimmedEmail = customer.email ? customer.email.trim() : ''

    if (!trimmedName || !/^[a-zA-Z\s]+$/.test(trimmedName)) {
      setLocalError('Name must contain alphabets and spaces only.')
      return
    }
    if (!/^\d{10}$/.test(trimmedPhone) || /^(\d)\1{9}$/.test(trimmedPhone)) {
      setLocalError('Please enter a valid 10-digit mobile number.')
      return
    }

    const emailVal = validateCustomerEmail(trimmedEmail)
    if (!emailVal.isValid) {
      setLocalError(emailVal.error)
      return
    }

    setLocalError('')
    submitCustomer(e)
  }

  return (
    <div className="other-message assistant" style={{ marginTop: '12px' }}>
      <span><UserRound size={14} /></span>
      <div className="message-content customer-card-content" style={{ width: '540px', maxWidth: '100%', padding: '16px', background: '#FFFFFF', border: '2px solid #E31B23', borderRadius: '14px', boxShadow: '0 4px 12px rgba(227, 27, 35, 0.08)', boxSizing: 'border-box' }}>
        <div className="customer-form-title" style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#B80E16', fontSize: '13px', fontWeight: '700', marginBottom: '4px' }}>
          <UserRound size={15} style={{ color: '#E31B23' }} /> Customer Details for {selectedPlanName}
        </div>
        <p style={{ margin: '4px 0 12px', color: '#6b7280', fontSize: '11px' }}>Please enter your contact details to proceed with installation scheduling.</p>
        
        {localError && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#DC2626', background: '#FEF2F2', border: '1px solid #FCA5A5', padding: '8px 12px', borderRadius: '8px', fontSize: '11px', fontWeight: '600', marginBottom: '12px' }}>
            <AlertCircle size={14} style={{ flexShrink: 0 }} /> {localError}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label style={{ fontSize: '11px', fontWeight: '700', color: '#374151' }}>Name</label>
            <input
              value={customer.name}
              onChange={(e) => {
                setCustomer({ ...customer, name: e.target.value.replace(/[^a-zA-Z\s]/g, '') })
                if (localError) setLocalError('')
              }}
              placeholder="Full name"
              required
              style={{ width: '100%', border: '1px solid #e5e7eb', borderRadius: '10px', padding: '9px 12px', fontSize: '12px', outline: 'none', boxSizing: 'border-box' }}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label style={{ fontSize: '11px', fontWeight: '700', color: '#374151' }}>Phone</label>
            <input
              value={customer.phone}
              onChange={(e) => {
                setCustomer({ ...customer, phone: e.target.value.replace(/\D/g, '').slice(0, 10) })
                if (localError) setLocalError('')
              }}
              placeholder="10-digit mobile number"
              inputMode="numeric"
              required
              style={{ width: '100%', border: '1px solid #e5e7eb', borderRadius: '10px', padding: '9px 12px', fontSize: '12px', outline: 'none', boxSizing: 'border-box' }}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label style={{ fontSize: '11px', fontWeight: '700', color: '#374151' }}>Email</label>
            <input
              value={customer.email}
              onChange={(e) => {
                setCustomer({ ...customer, email: e.target.value })
                if (localError) setLocalError('')
              }}
              placeholder="Enter email address"
              type="email"
              required
              style={{
                width: '100%',
                border: '1px solid #e5e7eb',
                borderRadius: '10px',
                padding: '9px 12px',
                fontSize: '12px',
                outline: 'none',
                boxSizing: 'border-box',
                background: '#FFFFFF'
              }}
            />
          </div>
          <button className="customer-submit red-btn" disabled={busy} style={{ width: '100%', marginTop: '6px', padding: '10px 14px', borderRadius: '10px', fontWeight: '700', fontSize: '12px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
            Save Details & Select Slot <ChevronRight size={14} />
          </button>
        </form>
      </div>
    </div>
  )
}
