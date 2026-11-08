import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from '../App'

vi.mock('../services/api', async (orig) => {
  const mod = await orig()
  return {
    ...mod,
    ensureCsrf: vi.fn().mockResolvedValue('t'),
    api: { ...mod.api, me: vi.fn().mockRejectedValue({ response: { status: 401 } }) },
  }
})

describe('routing', () => {
  it('redirects unauthenticated users to the login page', async () => {
    window.history.pushState({}, '', '/portfolio')
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/login')
  })
})
