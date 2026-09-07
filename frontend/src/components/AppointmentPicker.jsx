import React from 'react'
import { DayPicker } from 'react-day-picker'
import 'react-day-picker/style.css'
import { dateKey } from '../utils/api'

export function AppointmentPicker({
  state,
  chosenDate,
  setChosenDate,
  today,
  slotList,
  selectSlot,
  busy
}) {
  const isAppointmentFixed = Boolean(state.appointment)
  const currentDateKey = state.appointment?.date || (chosenDate ? dateKey(chosenDate) : dateKey(today))
  const displayDateObj = new Date(currentDateKey + 'T00:00:00')

  return (
    <div style={{ padding: '24px', background: '#ffffff', borderRadius: '12px', border: '1px solid #F0EDED', marginTop: '12px', boxShadow: '0 2px 12px rgba(0,0,0,0.04)', textAlign: 'left', width: '100%', boxSizing: 'border-box' }}>
      <h3 style={{ margin: '0 0 20px 0', fontSize: '16px', fontWeight: '600', color: '#1a1a1a', letterSpacing: '-0.3px' }}>Pick a date and time</h3>
      <div style={{ display: 'flex', gap: '28px', flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <style>{`
          .calendly-cal.rdp-root {
            --rdp-accent-color: #E31B23;
            --rdp-accent-background-color: #E31B23;
            --rdp-day-height: 40px;
            --rdp-day-width: 40px;
            --rdp-day_button-height: 36px;
            --rdp-day_button-width: 36px;
            --rdp-day_button-border-radius: 50%;
            --rdp-selected-border: 2px solid transparent;
            --rdp-today-color: #E31B23;
            --rdp-nav-height: 2.5rem;
            --rdp-nav_button-height: 2rem;
            --rdp-nav_button-width: 2rem;
            --rdp-disabled-opacity: 0.65;
            font-family: inherit;
            font-size: 14px;
          }
          .calendly-cal .rdp-month_caption { font-size: 15px; font-weight: 600; color: #1f2937; }
          .calendly-cal .rdp-weekday { font-size: 12px; font-weight: 600; color: #6b7280; opacity: 1; text-transform: capitalize; }
          .calendly-cal .rdp-day_button { font-size: 14px; font-weight: 500; color: #1f2937; transition: all 0.15s ease; border-radius: 50%; }
          .calendly-cal .rdp-day_button:hover:not(:disabled) { background: #FFF0F1; color: #E31B23; font-weight: 600; }
          .calendly-cal .rdp-selected .rdp-day_button { background-color: #E31B23 !important; color: #ffffff !important; font-weight: 700; box-shadow: 0 4px 10px rgba(227, 27, 35, 0.3); }
          .calendly-cal .rdp-today:not(.rdp-selected) .rdp-day_button { color: #E31B23; font-weight: 700; border: 1.5px dashed #E31B23; }
          .calendly-cal .rdp-chevron { fill: #4b5563; }
          .calendly-cal .rdp-button_next, .calendly-cal .rdp-button_previous { border-radius: 8px; transition: background 0.15s; }
          .calendly-cal .rdp-button_next:hover, .calendly-cal .rdp-button_previous:hover { background: #F3F4F6; }

          /* Past / Disabled Dates Styling */
          .calendly-cal .rdp-disabled { opacity: 0.65 !important; }
          .calendly-cal .rdp-disabled .rdp-day_button { color: #94a3b8 !important; font-weight: 500; text-decoration: line-through; text-decoration-color: #cbd5e1; cursor: not-allowed !important; }
          .calendly-cal .rdp-disabled .rdp-day_button:hover { background: transparent !important; color: #94a3b8 !important; cursor: not-allowed !important; }

          .cal-slot { width: 100%; margin-bottom: 10px; padding: 14px 16px; border-radius: 10px; border: 1.5px solid #E5E7EB; background: #fff; cursor: pointer; text-align: center; font-weight: 600; font-size: 13px; color: #374151; transition: all 0.15s ease; outline: none; display: block; }
          .cal-slot:hover:not(:disabled) { border-color: #E31B23; background: #FFF0F1; color: #E31B23; transform: translateY(-1px); box-shadow: 0 4px 12px rgba(227, 27, 35, 0.08); }
          .cal-slot:disabled { opacity: 0.45; cursor: not-allowed; }
          .cal-slot.cal-slot--active { background: linear-gradient(135deg, #E31B23, #C4121A); color: #fff; border-color: #E31B23; font-weight: 700; box-shadow: 0 4px 12px rgba(227, 27, 35, 0.25); }
        `}</style>

        <div style={{ flex: '1 1 280px', minWidth: '270px', pointerEvents: isAppointmentFixed ? 'none' : 'auto', opacity: isAppointmentFixed ? 0.8 : 1 }}>
          <DayPicker
            className="calendly-cal"
            mode="single"
            selected={state.appointment?.date ? new Date(state.appointment.date + 'T00:00:00') : (chosenDate || today)}
            onSelect={(d) => !isAppointmentFixed && d && setChosenDate(d)}
            disabled={isAppointmentFixed ? { before: new Date(2000, 0, 1), after: new Date(2099, 11, 31) } : { before: today }}
            fromDate={today}
            defaultMonth={state.appointment?.date ? new Date(state.appointment.date + 'T00:00:00') : (chosenDate || today)}
          />
        </div>

        <div style={{ flex: '1 1 180px', minWidth: '170px', paddingTop: '2px' }}>
          <div style={{ fontSize: '15px', fontWeight: '500', color: '#1a1a1a', marginBottom: '16px' }}>
            {isNaN(displayDateObj) ? '' : displayDateObj.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </div>
          {slotList.map((slot) => {
            const isSelected = state.appointment && state.appointment.slot_id === slot.slot_id
            return (
              <button
                key={slot.slot_id}
                className={`cal-slot${isSelected ? ' cal-slot--active' : ''}`}
                onClick={() => !isAppointmentFixed && selectSlot(slot)}
                disabled={busy || (isAppointmentFixed && !isSelected)}
              >
                {slot.time_window}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
