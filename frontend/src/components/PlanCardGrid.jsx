import React from 'react'
import { Sparkles, Wifi, ChevronRight, MapPin, Zap } from 'lucide-react'

export function RecommendedPlanCard({ recommendedPlan, selectedPlan, selectPlan, busy }) {
  if (!recommendedPlan) return null
  const isSelected = selectedPlan && (selectedPlan.plan_id === recommendedPlan.plan_id || selectedPlan.name === recommendedPlan.name)
  const isAnyPlanSelected = Boolean(selectedPlan)

  return (
    <div className="wizard-plan" style={{ marginTop: '12px', textAlign: 'left', background: isSelected ? '#ECFDF5' : '#FFFFFF', border: isSelected ? '2px solid #10B981' : '2px solid #E31B23', borderRadius: '14px', padding: '14px', boxShadow: '0 4px 12px rgba(227, 27, 35, 0.08)' }}>
      <div className="plan-card-head" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
        <span style={{ background: isSelected ? '#D1FAE5' : '#FFF0F1', color: isSelected ? '#059669' : '#E31B23', padding: '3px 10px', borderRadius: '12px', fontWeight: '700', fontSize: '10px' }}>
          <Sparkles size={11} style={{ verticalAlign: 'middle', marginRight: '4px' }} />
          {isSelected ? 'ACTIVE SELECTION' : 'RECOMMENDED MATCH'}
        </span>
        <Wifi size={14} style={{ color: isSelected ? '#059669' : '#E31B23' }} />
      </div>
      <strong style={{ fontSize: '15px', color: isSelected ? '#065F46' : '#1F2937', display: 'block', marginBottom: '2px' }}>{recommendedPlan.name}</strong>
      {recommendedPlan.speed_mbps && (
        <div className="wizard-speed" style={{ color: isSelected ? '#047857' : '#E31B23', fontSize: '13px', fontWeight: '600', marginBottom: '4px' }}>
          {recommendedPlan.speed_mbps} Mbps Speed
        </div>
      )}
      <div className="wizard-price" style={{ color: isSelected ? '#065F46' : '#111827', fontSize: '17px', fontWeight: '700', marginBottom: '6px' }}>
        ₹{recommendedPlan.price_inr}<small style={{ color: isSelected ? '#047857' : '#6B7280', fontSize: '11px', fontWeight: '400' }}>/month</small>
      </div>
      {recommendedPlan.description && (
        <p style={{ fontSize: '11px', color: isSelected ? '#047857' : '#4B5563', margin: '4px 0 10px' }}>{recommendedPlan.description}</p>
      )}
      <button
        className={`customer-submit ${isSelected ? 'green-btn' : 'red-btn'}`}
        style={{ marginTop: '6px', width: '100%', padding: '8px 12px', fontSize: '13px', backgroundColor: isSelected ? '#10B981' : (isAnyPlanSelected ? '#9CA3AF' : undefined), opacity: (!isSelected && isAnyPlanSelected) ? 0.6 : 1, cursor: isAnyPlanSelected ? 'default' : 'pointer' }}
        onClick={() => !isAnyPlanSelected && selectPlan(recommendedPlan)}
        disabled={busy || isAnyPlanSelected}
      >
        {isSelected ? 'Selected ✓' : (isAnyPlanSelected ? 'Plan Selected' : 'Select & Book')} <ChevronRight size={13} />
      </button>
    </div>
  )
}

export function PlanCardGrid({ plans, selectedPlan, selectPlan, activateAddon, busy, isExisting, pincode }) {
  if (!plans || plans.length === 0) return null

  return (
    <div className="chat-card-section" style={{ margin: '15px 0' }}>
      <div style={{ fontSize: '12px', fontWeight: '700', color: '#E31B23', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
        <Sparkles size={14} />
        {plans[0]?.addon_id ? 'Available Add-on Services' : (isExisting ? 'Available Plan Upgrades' : 'Available Plans for Your Region')}
        {pincode && (
          <span style={{ marginLeft: 'auto', background: '#FFF0F1', color: '#E31B23', padding: '3px 8px', borderRadius: '12px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <MapPin size={12} /> Pincode {pincode}
          </span>
        )}
      </div>
      <div className="plan-card-grid">
        {plans.map((plan) => {
          const isSelected = selectedPlan && (selectedPlan.plan_id === plan.plan_id || selectedPlan.name === plan.name)
          const isAnyPlanSelected = Boolean(selectedPlan)
          return (
            <div className="wizard-plan" key={plan.plan_id || plan.addon_id || plan.name} style={{ textAlign: 'left', border: isSelected ? '2px solid #10B981' : undefined, background: isSelected ? '#ECFDF5' : undefined }}>
              <div className="plan-card-head">
                <span style={{ color: isSelected ? '#059669' : undefined, background: isSelected ? '#D1FAE5' : undefined }}>
                  {isSelected ? 'SELECTED' : (plan.addon_id ? 'ADD-ON' : (plan.type || 'FIBER'))}
                </span>
                {plan.addon_id ? <Zap size={13} /> : <Wifi size={13} style={{ color: isSelected ? '#059669' : undefined }} />}
              </div>
              <strong style={{ color: isSelected ? '#065F46' : undefined }}>{plan.name}</strong>
              {plan.speed_mbps && <div className="wizard-speed" style={{ color: isSelected ? '#047857' : undefined }}>{plan.speed_mbps} Mbps</div>}
              <div className="wizard-price" style={{ color: isSelected ? '#065F46' : undefined }}>₹{plan.price_inr}<small style={{ color: isSelected ? '#047857' : undefined }}>/month</small></div>
              {plan.description && <p style={{ fontSize: '11px', color: isSelected ? '#047857' : '#666', margin: '6px 0' }}>{plan.description}</p>}
              <button
                className={`customer-submit ${isSelected ? 'green-btn' : 'red-btn'}`}
                style={{ marginTop: '10px', width: '100%', backgroundColor: isSelected ? '#10B981' : (isAnyPlanSelected ? '#9CA3AF' : undefined), opacity: (!isSelected && isAnyPlanSelected) ? 0.6 : 1, cursor: isAnyPlanSelected ? 'default' : 'pointer' }}
                onClick={() => !isAnyPlanSelected && (plan.addon_id ? activateAddon(plan) : selectPlan(plan))}
                disabled={busy || isAnyPlanSelected}
              >
                {isSelected ? 'Selected ✓' : (plan.addon_id ? 'Activate Add-on' : (isExisting ? 'Upgrade Plan' : 'Select & Book'))} <ChevronRight size={13} />
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
