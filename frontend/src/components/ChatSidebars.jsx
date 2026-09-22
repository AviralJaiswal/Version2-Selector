import React from 'react'
import { BadgeCheck, Bot, Clock3, ShieldCheck, Sparkles, Wifi, Zap } from 'lucide-react'

// Existing-customer workflow states that mean "the customer has not asked for
// anything yet" — verification prompts and the post-verification account
// overview. Anything else after verification counts as a selected request.
const EXISTING_PRE_VERIFY_STATES = ['AWAITING_PHONE_VERIFICATION', 'PHONE_NOT_FOUND']
const EXISTING_IDLE_STATES = ['PLAN_OVERVIEW', 'NO_ACTIVE_PLAN']
// Terminal states: plan change applied, or profile edited successfully.
const EXISTING_COMPLETE_STATES = ['PLAN_CHANGE_CONFIRMED', 'PROFILE_UPDATED']

export function isExistingPreVerifyState(workflow) {
  return EXISTING_PRE_VERIFY_STATES.includes(workflow)
}

export function isExistingIdleState(workflow) {
  return EXISTING_IDLE_STATES.includes(workflow)
}

export function isExistingCompleteState(workflow) {
  return EXISTING_COMPLETE_STATES.includes(workflow)
}

/**
 * Derives the three-step existing-customer timeline from the sticky journey
 * flags tracked by the view (falling back to raw session state so the sidebar
 * still degrades gracefully if no journey is supplied).
 */
function existingTimeline(state, journey) {
  const workflow = journey?.workflow || state.workflow_state || ''
  const verified = Boolean(journey?.verified || state.existing_customer_verified)
  const completed = Boolean(journey?.completed || isExistingCompleteState(workflow))
  const requestSelected = Boolean(
    journey?.requestSelected ||
    completed ||
    (verified && workflow && !isExistingPreVerifyState(workflow) && !isExistingIdleState(workflow))
  )

  const stage = completed
    ? 'COMPLETE'
    : requestSelected
      ? 'SELECT REQUEST'
      : verified
        ? 'ACCOUNT VERIFIED'
        : 'VERIFY ACCOUNT'

  return {
    stage,
    tracker: [
      ['Verify account', verified],
      ['Select request', requestSelected],
      ['Complete', completed]
    ]
  }
}

function generalTimeline(state, journey, messages) {
  const explored = Boolean(journey?.explored || messages.length > 1)
  const addressDone = Boolean(journey?.addressConfirmed || state.address_qualified || state.address_confirmed)
  const planChosen = Boolean(journey?.planSelected || state.selected_plan)
  const booked = Boolean(journey?.booked || state.order_confirmed || state.workflow_state === 'ORDER_CONFIRMED')

  const stage = booked
    ? 'ORDER CONFIRMED'
    : planChosen
      ? 'BOOK INSTALLATION'
      : addressDone
        ? 'CHOOSE PLAN'
        : explored
          ? 'CONFIRM ADDRESS'
          : 'EXPLORE OPTIONS'

  return {
    stage,
    tracker: [
      ['Explore', explored],
      ['Confirm address', addressDone],
      ['Choose plan', planChosen],
      ['Book', booked]
    ]
  }
}

export function ChatSidebars({ mode, state, messages, busy, journey }) {
  const isExisting = mode === 'existing'
  const { stage, tracker } = isExisting
    ? existingTimeline(state, journey)
    : generalTimeline(state, journey, messages)

  // The first incomplete step is the one currently in progress.
  const activeIndex = tracker.findIndex(([, complete]) => !complete)
  const selectedPlan = state.selected_plan || state.current_plan

  return (
    <aside className="assistant-sidebar session-overview" aria-label="Session overview">
      <div className="overview-hero">
        <span className="overview-orb"><Bot size={18} /></span>
        <div><span className="overview-kicker"><Sparkles size={12} /> Live session</span><strong>{isExisting ? 'Account journey' : 'Connection journey'}</strong></div>
      </div>
      <div className="overview-live"><i />{busy ? 'Assistant is working' : 'Session is active'}</div>
      <section className="overview-section">
        <div className="overview-label"><Zap size={14} /> Current stage</div>
        <strong className="overview-stage">{stage}</strong>
        <div className="journey-tracker">
          {tracker.map(([label, complete], index) => (
            <div className={`${complete ? 'complete' : ''}${index === activeIndex ? ' active' : ''}`.trim()} key={label}>
              <b>{complete ? <BadgeCheck size={14} /> : index + 1}</b><span>{label}</span>
            </div>
          ))}
        </div>
      </section>
      {selectedPlan && <section className="overview-plan"><small>{state.current_plan && !state.selected_plan ? 'CURRENT PLAN' : 'SELECTED PLAN'}</small><strong>{selectedPlan.name}</strong><span><Wifi size={13} /> {selectedPlan.speed_mbps || selectedPlan.speed} Mbps {selectedPlan.price_inr ? `· ₹${selectedPlan.price_inr}/mo` : ''}</span></section>}
      <section className="overview-note"><ShieldCheck size={16} /><p><strong>Conversation memory is on.</strong> Your chat context stays connected while you move through this journey.</p></section>
      <div className="overview-time"><Clock3 size={13} /> Updates as you chat</div>
    </aside>
  )
}
