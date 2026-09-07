export const ALLOWED_PROVIDER_PREFIXES = [
  'gmail',
  'yahoo',
  'outlook',
  'hotmail',
  'icloud',
  'live',
  'prodapt'
]

export function validateCustomerEmail(email) {
  if (!email || !email.trim()) {
    return {
      isValid: false,
      error: 'Please enter your email address.'
    }
  }

  const trimmed = email.trim().toLowerCase()
  const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/

  if (!emailRegex.test(trimmed)) {
    return {
      isValid: false,
      error: 'Please enter a valid email address.'
    }
  }

  const parts = trimmed.split('@')
  if (parts.length !== 2) {
    return {
      isValid: false,
      error: 'Please enter a valid email address.'
    }
  }

  const domain = parts[1]
  const provider = domain.split('.')[0]

  if (!ALLOWED_PROVIDER_PREFIXES.includes(provider)) {
    return {
      isValid: false,
      error: 'Please enter a valid email address.'
    }
  }

  return {
    isValid: true,
    error: '',
    domain,
    provider
  }
}
