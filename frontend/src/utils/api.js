export const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

export const newSession = () => crypto.randomUUID()

export const formatDateLocal = (date) => {
  if (!date) return ''
  if (typeof date === 'string') return date.slice(0, 10)
  if (date instanceof Date) {
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }
  return String(date)
}

export const dateKey = (date) => formatDateLocal(date)

export async function request(path, payload) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 30000)
  try {
    const response = await fetch(`${API}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok || body.success === false) {
      throw new Error(body.error || body.message || body.detail || 'Something went wrong. Please try again.')
    }
    return body.data !== undefined && body.data !== null ? { ...body, ...body.data } : body
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('The server took too long to respond. Check that the API is running.')
    throw error
  } finally {
    window.clearTimeout(timer)
  }
}

export const loadRazorpay = () => {
  return new Promise((resolve) => {
    if (window.Razorpay) {
      resolve(true)
      return
    }
    const script = document.createElement('script')
    script.src = 'https://checkout.razorpay.com/v1/checkout.js'
    script.onload = () => resolve(true)
    script.onerror = () => resolve(false)
    document.body.appendChild(script)
  })
}
