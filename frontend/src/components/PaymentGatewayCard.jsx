import React from 'react'
import { Wifi, CreditCard, Check } from 'lucide-react'

export function PaymentGatewayCard({ selectedPlan, confirmBookingAndPayment, setShowPaymentGateway, busy }) {
  return (
    <div className="other-message assistant" style={{ marginTop: '12px' }}>
      <span><Wifi size={14} /></span>
      <div className="message-content" style={{ maxWidth: '80%', width: '100%', padding: '16px', background: '#FFFFFF', border: '2px solid #E31B23', borderRadius: '14px', boxShadow: '0 4px 12px rgba(227, 27, 35, 0.08)' }}>
        <div className="customer-form-title" style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#B80E16', fontSize: '13px', fontWeight: '700', marginBottom: '4px' }}>
          <CreditCard size={15} style={{ color: '#E31B23' }} /> Demo Payment Gateway
        </div>
        <p style={{ margin: '4px 0 12px', color: '#6b7280', fontSize: '11px' }}>Please complete payment to finalize your fiber connection booking.</p>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#FFF0F1', padding: '10px 14px', borderRadius: '10px', border: '1px solid #FFCCD0', marginBottom: '12px' }}>
          <span style={{ fontSize: '12px', color: '#374151', fontWeight: '600' }}>Amount Payable:</span>
          <strong style={{ fontSize: '16px', color: '#B80E16', fontWeight: '700' }}>₹{selectedPlan?.price_inr}</strong>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <button className="customer-submit red-btn" style={{ width: '100%', padding: '10px 14px', borderRadius: '10px', fontWeight: '700', fontSize: '12px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }} onClick={confirmBookingAndPayment} disabled={busy}>
            Pay ₹{selectedPlan?.price_inr} Now <Check size={15} />
          </button>
          <button style={{ width: '100%', padding: '8px 12px', borderRadius: '10px', border: '1px solid #e5e7eb', background: '#fff', color: '#6b7280', fontSize: '12px', fontWeight: '600', cursor: 'pointer' }} onClick={() => setShowPaymentGateway(false)} disabled={busy}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
