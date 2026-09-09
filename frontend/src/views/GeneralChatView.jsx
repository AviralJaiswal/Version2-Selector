import React, { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, Check, CheckCircle2, Send, Sparkles, UserRound, Wifi, MapPin, Zap, Bot, ShieldCheck, Clock } from 'lucide-react'
import { request, dateKey, loadRazorpay } from '../utils/api'
import { validateCustomerEmail } from '../utils/validation'
import { FormattedText } from '../components/FormattedText'
import { Summary } from '../components/Summary'
import { AppointmentPicker } from '../components/AppointmentPicker'
import { SavedCustomerCard, CustomerFormCard } from '../components/CustomerCard'
import { PaymentGatewayCard } from '../components/PaymentGatewayCard'
import { RecommendedPlanCard, PlanCardGrid } from '../components/PlanCardGrid'
import { SuggestedResponses } from '../components/SuggestedResponses'
import { MicButton } from '../components/MicButton'
import { useVoiceMode } from '../hooks/useVoiceMode'
import { useLanguage } from '../context/LanguageContext'

export function GeneralChatView({ onBack }) {
  const mode = "general";
  const isExisting = mode === 'existing'
  const { t } = useLanguage()
  const voice = useVoiceMode()
  const [sessionId, setSessionId] = useState(() => {
    try {
      let key = isExisting ? 'qcom_session_id_existing' : 'qcom_session_id_general'
      sessionStorage.removeItem(key)
    } catch { }
    return (typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : 'sess-' + Math.random().toString(36).substring(2, 11) + Date.now())
  })
  const [messages, setMessages] = useState([])
  const [state, setState] = useState({})
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [customer, setCustomer] = useState({ name: '', phone: '', email: '' })
  const [addressForm, setAddressForm] = useState({ house_no: '', street: '', landmark: '' })
  const [chosenDate, setChosenDate] = useState(null)
  const [order, setOrder] = useState(null)
  const [showPaymentGateway, setShowPaymentGateway] = useState(false)
  const initializedSessionIdRef = useRef(null)
  const messagesEndRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy, state, showPaymentGateway, order])

  async function send(message = '', quickAction = null, structuredFields = null, overrideSessionId = null, viaVoice = false) {
    if (busy && !overrideSessionId) return
    setBusy(true)
    setError('')
    if (message && !message.startsWith('[')) {
      setMessages((items) => [...items, { role: 'user', content: message }])
    }
    const mergedFields = {
      ...(isExisting ? { is_existing_customer: true } : {}),
      ...(structuredFields || {})
    }
    try {
      const response = await request('/chat', {
        session_id: overrideSessionId || sessionId,
        message,
        ...(quickAction ? { quick_action: quickAction } : {}),
        structured_fields: Object.keys(mergedFields).length > 0 ? mergedFields : null
      })

      const rawPlans = (response.sources && Array.isArray(response.sources) && response.sources.length > 0 && response.sources[0]?.price_inr !== undefined)
        ? response.sources
        : ((response.updated_state?.plans_shown && response.updated_state?.address_qualified && response.updated_state?.address_confirmed)
          ? (response.updated_state?.catalog_plans || response.updated_state?.recommended_plans || [])
          : [])

      const isPlanDiscovery =
        (response.intent === 'PLANS_DISCOVERED' || response.workflow_state === 'PLAN_SELECTION' || response.workflowState === 'PLAN_SELECTION') &&
        rawPlans.length > 0

      const followups = response.recommended_followups || response.recommendedFollowups || (response.data && (response.data.recommended_followups || response.data.recommendedFollowups)) || []

      setMessages((items) => {
        const alreadyHasPlans = items.some((m) => m.plans && m.plans.length > 0)
        const shouldAttachPlans = (isPlanDiscovery && !alreadyHasPlans) || (rawPlans.length > 0 && !alreadyHasPlans && (response.answer?.includes('plans for') || response.answer?.includes('plans available') || response.answer?.includes('suits you best')))
        const newAssistantMsg = {
          role: 'assistant',
          content: response.answer,
          followups: followups,
          ...(shouldAttachPlans ? { plans: rawPlans } : {}),
          ...(response.recommended_plan ? { recommended_plan: response.recommended_plan } : {})
        }
        if (overrideSessionId) {
          return [newAssistantMsg]
        }
        return [...items, newAssistantMsg]
      })

      if (response.updated_state) {
        setState(response.updated_state)
      }
      if (viaVoice && response.answer) {
        voice.speak(response.answer)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function fetchWelcomeGreeting(sid) {
    if (!sid || initializedSessionIdRef.current === sid) return
    initializedSessionIdRef.current = sid
    setBusy(true)
    try {
      const res = await request('/api/v1/assistant/welcome', { sessionId: sid, profile: 'general' })
      const welcomeMsg = res.response || res.welcome_message || res.message
      const followups = res.recommended_followups || res.recommendedFollowups || (res.data && (res.data.recommended_followups || res.data.recommendedFollowups)) || []
      if (welcomeMsg) {
        setMessages([{ role: 'assistant', content: isExisting ? `📌 **Existing Customer Portal**\n\n${welcomeMsg}` : welcomeMsg, followups: followups }])
        return
      }
    } catch (e) {
      console.warn("Welcome API fallback", e)
      send('', 'general', null, sid)
    } finally {
      setBusy(false)
    }
  }

  const resetSession = () => {
    try {
      let key = isExisting ? 'qcom_session_id_existing' : 'qcom_session_id_general'
      sessionStorage.removeItem(key)
    } catch { }
    const freshId = (typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : 'sess-' + Math.random().toString(36).substring(2, 11) + Date.now())
    initializedSessionIdRef.current = null
    setSessionId(freshId)
    setMessages([])
    setState({})
    setCustomer({ name: '', phone: '', email: '' })
    setAddressForm({ house_no: '', street: '', landmark: '' })
    setChosenDate(null)
    setOrder(null)
    setShowPaymentGateway(false)
    setError('')
    fetchWelcomeGreeting(freshId)
  }

  useEffect(() => {
    if (sessionId && initializedSessionIdRef.current !== sessionId) {
      fetchWelcomeGreeting(sessionId)
    }
  }, [sessionId])

  const selectPlan = (plan) => {
    send(`Selected plan: ${plan.name}`, null, { action: 'PLAN_SELECTED', selected_plan: plan })
  }

  const handleSaveEditedCustomer = (updatedCustomer) => {
    setCustomer(updatedCustomer)
    setMessages((prev) =>
      prev.filter((m) => !(m.role === 'assistant' && (m.content?.includes('Contact details saved') || m.content?.includes('installation appointment slot'))))
    )
    send('', null, { customer: updatedCustomer })
  }

  const submitCustomer = (e) => {
    e.preventDefault()
    const trimmedName = customer.name.trim()
    const trimmedPhone = customer.phone.trim()
    const trimmedEmail = customer.email.trim()

    if (!trimmedName || !/^[a-zA-Z\s]+$/.test(trimmedName)) {
      setError('Name must contain alphabets and spaces only.')
      return
    }
    if (!/^\d{10}$/.test(trimmedPhone) || /^(\d)\1{9}$/.test(trimmedPhone)) {
      setError('Please enter a valid 10-digit mobile number.')
      return
    }
    const emailVal = validateCustomerEmail(trimmedEmail)
    if (!emailVal.isValid) {
      setError(emailVal.error)
      return
    }
    setError('')
    const customerMsg = `Name: ${trimmedName}\nPhone: ${trimmedPhone}\nEmail: ${trimmedEmail}`
    send(customerMsg, null, { customer: { name: trimmedName, phone: trimmedPhone, email: trimmedEmail } })
  }

  const today = useMemo(() => {
    const d = new Date()
    d.setHours(0, 0, 0, 0)
    return d
  }, [])

  const selectSlot = async (slot) => {
    setBusy(true)
    setError('')
    const dateObj = new Date(slot.date + 'T00:00:00')
    const dateFormatted = !isNaN(dateObj)
      ? dateObj.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
      : slot.date

    const userMsg = `📅 Selected Installation Slot: ${dateFormatted} (${slot.time_window})`
    setMessages((items) => [...items, { role: 'user', content: userMsg }])

    try {
      const apptData = await request('/select-appointment', { session_id: sessionId, slot_id: slot.slot_id })
      setState((prev) => ({ ...prev, appointment: apptData }))
      setMessages((items) => [...items, {
        role: 'assistant',
        content: `Great! Your installation appointment on **${dateFormatted}** (${slot.time_window}) is reserved.\n\n**Booking Summary:**\n- **Plan:** ${state.selected_plan?.name} (${state.selected_plan?.speed_mbps} Mbps) at ₹${state.selected_plan?.price_inr}/month\n- **Customer:** ${state.customer?.name} | ${state.customer?.phone} | ${state.customer?.email}\n\nPlease select a payment method below to complete your booking.`
      }])
      setShowPaymentGateway(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const confirmBookingAndPayment = async () => {
    setShowPaymentGateway(false)
    setBusy(true)
    setError('')
    try {
      const planId = state.selected_plan?.plan_id
      const paymentData = await request('/payment', { session_id: sessionId, plan_id: planId })

      if (paymentData.razorpay_order_id) {
        const resLoaded = await loadRazorpay()
        if (!resLoaded) {
          setError('Failed to load Razorpay SDK')
          setBusy(false)
          return
        }

        const options = {
          key: paymentData.razorpay_key_id,
          amount: paymentData.amount_inr * 100,
          currency: 'INR',
          name: 'Signal Selector',
          description: 'Plan Subscription',
          order_id: paymentData.razorpay_order_id,
          prefill: {
            name: state.customer?.name || '',
            email: state.customer?.email || '',
            contact: state.customer?.phone || ''
          },
          handler: async function (response) {
            try {
              setBusy(true)
              await request('/payment/confirm', { session_id: sessionId, confirmation_code: response.razorpay_payment_id })
              const orderData = await request('/create-order', { session_id: sessionId })
              setOrder(orderData)
              setMessages((items) => [...items, {
                role: 'assistant',
                content: `🎉 **Booking Confirmed!**\n\nCongratulations ${state.customer?.name}! Your order **${orderData.order_id || 'SIG-ORD-CONFIRMED'}** has been confirmed successfully.\n\n**Plan Details:**\n• Plan: ${state.selected_plan?.name} (${state.selected_plan?.speed_mbps} Mbps)\n• Price: ₹${state.selected_plan?.price_inr}/month\n\n**Customer Details:**\n• Name: ${state.customer?.name}\n• Contact: ${state.customer?.phone} | ${state.customer?.email}\n\n**Installation Details:**\n• Date: ${state.appointment?.date || 'Tomorrow'}\n• Time: ${state.appointment?.time_window || 'Morning'}\n\nOur technician will contact you prior to arrival.`
              }])
            } catch (err) {
              setError(err.message)
            } finally {
              setBusy(false)
            }
          },
          modal: {
            ondismiss: function () {
              setBusy(false)
            }
          }
        }
        const rzp = new window.Razorpay(options)
        rzp.open()
      } else {
        await request('/payment/confirm', { session_id: sessionId, confirmation_code: 'DEMO-PAID' })
        const orderData = await request('/create-order', { session_id: sessionId })
        setOrder(orderData)
        setMessages((items) => [...items, {
          role: 'assistant',
          content: `🎉 **Booking Confirmed!**\n\nCongratulations ${state.customer?.name}! Your order **${orderData.order_id || 'SIG-ORD-CONFIRMED'}** has been confirmed successfully.\n\n**Plan Details:**\n• Plan: ${state.selected_plan?.name} (${state.selected_plan?.speed_mbps} Mbps)\n• Price: ₹${state.selected_plan?.price_inr}/month\n\n**Customer Details:**\n• Name: ${state.customer?.name}\n• Contact: ${state.customer?.phone} | ${state.customer?.email}\n\n**Installation Details:**\n• Date: ${state.appointment?.date || 'Tomorrow'}\n• Time: ${state.appointment?.time_window || 'Morning'}\n\nOur technician will contact you prior to arrival.`
        }])
        setBusy(false)
      }
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  const activateAddon = (addon) => {
    send(`I would like to activate the ${addon.name} add-on service for ₹${addon.price_inr}/month.`)
  }

  const submitForm = (e) => {
    e.preventDefault()
    if (!input.trim() || busy) return
    const txt = input.trim()
    setInput('')
    send(txt)
  }

  const missingCustomer = (state.missing_fields || []).filter((f) => f.startsWith('customer.'))
  const showCustomerForm = !isExisting && state.selected_plan && (missingCustomer.length > 0 || !state.customer)
  const availablePlans = ((state.plans_shown && state.address_qualified && state.address_confirmed) || isExisting) ? (state.catalog_plans || state.recommended_plans || []) : []

  const isInOrderFlow = Boolean(
    state.pincode ||
    state.address_qualified ||
    state.address_confirmed ||
    state.selected_plan ||
    showCustomerForm ||
    state.customer ||
    state.appointment ||
    showPaymentGateway ||
    order ||
    state.workflow_state === 'ADDRESS_QUALIFICATION' ||
    state.workflow_state === 'ADDRESS_CONFIRMATION' ||
    state.workflow_state === 'PLAN_SELECTION' ||
    state.workflow_state === 'CUSTOMER_DETAILS' ||
    state.workflow_state === 'APPOINTMENT' ||
    state.workflow_state === 'PAYMENT' ||
    state.workflow_state === 'ORDER_CONFIRMED'
  )

  const slotList = useMemo(() => {
    const targetDate = chosenDate ? dateKey(chosenDate) : dateKey(today)
    const compactDate = targetDate.replaceAll('-', '')
    const fdhId = state.qualified_address?.fdh_id || 'FDH-CHENNAI-01'
    return [
      { raw: '0900_1200', label: '09:00 AM - 12:00 PM' },
      { raw: '1200_1500', label: '12:00 PM - 03:00 PM' },
      { raw: '1500_1800', label: '03:00 PM - 06:00 PM' }
    ].map((slot) => ({
      slot_id: `DEMO-${fdhId}-${compactDate}-${slot.raw}`,
      date: targetDate,
      time_window: slot.label
    }))
  }, [chosenDate, today, state.qualified_address])

  return (
    <main className="other-view">
      <div className="other-head">
        <button className="back-link" onClick={onBack}>
          <ArrowLeft size={15} /> Home
        </button>
        <div>
          <strong>Signal Selector Assistant</strong>
          <small>{isExisting ? 'Existing Customer Support' : 'General & Plan Assistant'}</small>
        </div>
        <button className="back-link" onClick={resetSession} style={{ marginLeft: 'auto', background: '#FFF0F1', color: '#E31B23', border: '1px solid #FFCCD0', padding: '6px 12px', borderRadius: '16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px', fontWeight: '600' }}>
          <Sparkles size={13} /> New Chat
        </button>
        <span className="mode-badge red-badge" style={{ marginLeft: '10px' }}>
          <span /> {isExisting ? 'Existing Customer' : 'General Connection'}
        </span>
      </div>

      <div className="other-messages">
        {(() => {
          const lastAppointmentMsgIndex = messages.findLastIndex((m) => m.role === 'assistant' && (m.content?.includes('installation appointment slot') || m.content?.includes('Contact details saved')))
          const lastAssistantIndex = messages.findLastIndex((m) => m.role === 'assistant')
          return messages.map((item, index) => {
            const isHiddenUserMessage = item.role === 'user' && (item.content.startsWith('Selected plan:') || item.content.startsWith('📅 Selected Installation Slot:'))
            if (isHiddenUserMessage) return null

            const isCustomerDetailsMsg = item.role === 'user' && item.content.includes('Name:') && item.content.includes('Phone:') && item.content.includes('Email:')
            if (isCustomerDetailsMsg) {
              const nameMatch = item.content.match(/Name:\s*(.*)/)
              const phoneMatch = item.content.match(/Phone:\s*(.*)/)
              const emailMatch = item.content.match(/Email:\s*(.*)/)
              const cName = customer.name || (nameMatch ? nameMatch[1].trim() : '')
              const cPhone = customer.phone || (phoneMatch ? phoneMatch[1].trim() : '')
              const cEmail = customer.email || (emailMatch ? emailMatch[1].trim() : '')
              return (
                <SavedCustomerCard
                  key={index}
                  custName={cName}
                  custPhone={cPhone}
                  custEmail={cEmail}
                  onSave={handleSaveEditedCustomer}
                  busy={busy}
                  readOnly={Boolean(state.appointment || showPaymentGateway || order)}
                />
              )
            }

            return (
              <div key={index} className="message-animate-in">
                <div className={`other-message ${item.role}`}>
                  <span>{item.role === 'assistant' ? <Wifi size={14} /> : 'You'}</span>
                  <div className="message-content">
                    <FormattedText content={item.content} />
                    {item.role === 'assistant' && index === lastAssistantIndex && !isInOrderFlow && (
                      <SuggestedResponses followups={item.followups} onSelect={send} busy={busy} />
                    )}
                    <RecommendedPlanCard
                      recommendedPlan={item.recommended_plan}
                      selectedPlan={state.selected_plan}
                      selectPlan={selectPlan}
                      busy={busy}
                    />
                    {item.role === 'assistant' && index === lastAppointmentMsgIndex && (
                      <AppointmentPicker
                        state={state}
                        chosenDate={chosenDate}
                        setChosenDate={setChosenDate}
                        today={today}
                        slotList={slotList}
                        selectSlot={selectSlot}
                        busy={busy}
                      />
                    )}
                  </div>
                </div>

                <PlanCardGrid
                  plans={item.plans}
                  selectedPlan={state.selected_plan}
                  selectPlan={selectPlan}
                  activateAddon={activateAddon}
                  busy={busy}
                  isExisting={isExisting}
                  pincode={state.pincode}
                />
              </div>
            )
          })
        })()}

        {!messages.some((m) => m.plans && m.plans.length > 0) && !state.selected_plan && (
          <PlanCardGrid
            plans={availablePlans}
            selectedPlan={state.selected_plan}
            selectPlan={selectPlan}
            activateAddon={activateAddon}
            busy={busy}
            isExisting={isExisting}
            pincode={state.pincode}
          />
        )}

        {showCustomerForm && (
          <CustomerFormCard
            selectedPlanName={state.selected_plan?.name}
            customer={customer}
            setCustomer={setCustomer}
            submitCustomer={submitCustomer}
            busy={busy}
          />
        )}

        {showPaymentGateway && (
          <PaymentGatewayCard
            selectedPlan={state.selected_plan}
            confirmBookingAndPayment={confirmBookingAndPayment}
            setShowPaymentGateway={setShowPaymentGateway}
            busy={busy}
          />
        )}

        {order && (
          <div className="success-panel" style={{ padding: '20px', textAlign: 'center', background: '#fff0f1', borderRadius: '16px', margin: '15px 0', border: '1px solid #fee2e2' }}>
            <div className="success-icon" style={{ background: '#E31B23', color: '#fff' }}><Check size={24} /></div>
            <h3 style={{ margin: '8px 0 4px', color: '#B80E16' }}>Booking Confirmed!</h3>
            <p style={{ fontSize: '13px', color: '#7f1d1d' }}>Order ID: <strong>{order.order_id}</strong></p>
          </div>
        )}

        {busy && <div className="typing"><span /><span /><span /></div>}
        {error && <p className="inline-error">{error}</p>}
        <div ref={messagesEndRef} />
      </div>

      <form className="other-composer" onSubmit={submitForm}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t("typeMessage")}
          disabled={busy}
        />
        <MicButton
          isRecording={voice.isRecording}
          isTranscribing={voice.isTranscribing}
          disabled={busy || !voice.micSupported}
          onStart={voice.startRecording}
          onStop={async () => {
            const transcript = await voice.stopRecordingAndTranscribe()
            if (transcript) send(transcript, null, null, null, true)
          }}
        />
        <button className="red-btn" disabled={busy || !input.trim()}><Send size={16} /></button>
      </form>
      {voice.voiceError && <p className="inline-error">{voice.voiceError}</p>}
    </main>
  )
}
