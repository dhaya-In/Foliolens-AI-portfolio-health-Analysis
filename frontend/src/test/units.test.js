import { describe, it, expect } from 'vitest'
import { money, pct, signClass, isStale, timeAgo } from '../utils/format'
import { readCookie } from '../services/api'
import { sortHoldings } from '../pages/PortfolioPage'
import { passwordChecks } from '../pages/RegisterPage'

describe('format', () => {
  it('formats money per currency and never invents values', () => {
    expect(money(1234.5, 'INR')).toBe('₹1,234.50')
    expect(money(-50, 'USD')).toBe('-$50.00')
    expect(money(null, 'USD')).toBe('—')
  })
  it('formats percentages with sign', () => {
    expect(pct(2.345)).toBe('+2.35%')
    expect(pct(-1)).toBe('-1.00%')
    expect(pct(undefined)).toBe('—')
    expect(signClass(-3)).toBe('neg')
  })
  it('detects stale timestamps', () => {
    const now = Date.parse('2026-10-28T10:00:00Z')
    expect(isStale('2026-10-28T09:50:00Z', 900, now)).toBe(false)
    expect(isStale('2026-10-28T09:00:00Z', 900, now)).toBe(true)
    expect(isStale(null)).toBe(true)
    expect(timeAgo('2026-10-28T08:00:00Z', now)).toBe('2 h ago')
  })
})

describe('api helpers', () => {
  it('reads the CSRF cookie', () => {
    expect(readCookie('fl_csrf', 'a=1; fl_csrf=abc%3D; b=2')).toBe('abc=')
    expect(readCookie('fl_csrf', 'a=1')).toBeNull()
  })
})

describe('portfolio sorting', () => {
  const rows = [{ ticker: 'B', market_value: 10 }, { ticker: 'A', market_value: null }, { ticker: 'C', market_value: 30 }]
  it('sorts numbers and keeps unpriced rows last', () => {
    expect(sortHoldings(rows, 'market_value', 'desc').map(r => r.ticker)).toEqual(['C', 'B', 'A'])
    expect(sortHoldings(rows, 'market_value', 'asc').map(r => r.ticker)).toEqual(['B', 'C', 'A'])
    expect(sortHoldings(rows, 'ticker', 'asc').map(r => r.ticker)).toEqual(['A', 'B', 'C'])
  })
})

describe('password rules mirror the backend policy', () => {
  it('flags weak passwords', () => {
    expect(passwordChecks('short').every(c => c.ok)).toBe(false)
    expect(passwordChecks('CorrectHorse9Battery', 'me@x.com').every(c => c.ok)).toBe(true)
    expect(passwordChecks('Alice12345678', 'alice@x.com').every(c => c.ok)).toBe(false)
  })
})
