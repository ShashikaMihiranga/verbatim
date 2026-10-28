import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { splitName } from './messages'
import { checkPassword, isCommonPassword, passwordOk, validEmail } from './passwordRules'
import { safeDestination } from './redirect'
import { nextSignInStep } from './signInSteps'
import SidePanel from './SidePanel'
import { VARIANTS, parseVariant } from './variants'

describe('password rules', () => {
  it('needs 12+ characters, letters and numbers', () => {
    expect(passwordOk('Summer-Ridge-2041')).toBe(true)
    expect(passwordOk('short1A')).toBe(false)
    expect(passwordOk('onlyletterslongenough')).toBe(false)
    expect(passwordOk('123456789012345')).toBe(false)
  })
  it('reports each rule separately', () => {
    const rules = Object.fromEntries(checkPassword('abcdefghij').map((r) => [r.id, r.met]))
    expect(rules.length).toBe(false)
    expect(rules.mix).toBe(false)
    expect(checkPassword('').every((r) => !r.met)).toBe(true)
  })
  it('rejects common passwords, even dressed up', () => {
    for (const pw of ['password1234', 'Password2024!', 'qwerty123456', 'aaaaaaaaaaaa1']) {
      expect(isCommonPassword(pw) || !passwordOk(pw)).toBe(true)
    }
    expect(isCommonPassword('password')).toBe(true)
    expect(isCommonPassword('Summer-Ridge-2041')).toBe(false)
  })
  it('checks email shape', () => {
    expect(validEmail('sam@company.com')).toBe(true)
    expect(validEmail('sam@company')).toBe(false)
    expect(validEmail('sam @company.com')).toBe(false)
  })
})

describe('variants', () => {
  it('only accepts a to d', () => {
    for (const v of VARIANTS) expect(parseVariant(v)).toBe(v)
    for (const bad of ['e', 'A', '', null, undefined, 3, {}]) expect(parseVariant(bad)).toBe('a')
  })
  it('renders a different side panel for each design', () => {
    const html = Object.fromEntries(VARIANTS.map((v) => [v, renderToStaticMarkup(<SidePanel variant={v} />)]))
    expect(html.a).toContain('panel-a')
    expect(html.b).toContain('panel-b')
    expect(html.c).toContain('panel-c')
    expect(html.d).toContain('panel-d')
    expect(new Set(Object.values(html)).size).toBe(4)
    for (const v of VARIANTS) {
      expect(html[v]).toContain('aria-hidden="true"')
      expect(html[v]).toContain(`data-variant="${v}"`)
    }
  })
})

describe('redirects and names', () => {
  it('only allows paths inside the app', () => {
    expect(safeDestination('/cleaning')).toBe('/cleaning')
    for (const bad of ['https://evil.test', '//evil.test', '\\evil', undefined, 5, '/sign-in']) {
      expect(safeDestination(bad)).toBe('/upload')
    }
  })
  it('splits a full name', () => {
    expect(splitName('Sam')).toEqual({ firstName: 'Sam' })
    expect(splitName('  Sam  Lee Wong ')).toEqual({ firstName: 'Sam', lastName: 'Lee Wong' })
  })
})

describe('sign-in steps', () => {
  it('a finished sign-in opens the session', () => {
    expect(nextSignInStep({ status: 'complete', createdSessionId: 'sess_1' })).toEqual({ kind: 'done', sessionId: 'sess_1' })
  })
  it('a new device asks for the emailed code instead of failing', () => {
    const factors = [{ strategy: 'email_code', emailAddressId: 'idn_1', safeIdentifier: 'c***@getverbatim.app' }]
    for (const status of ['needs_second_factor', 'needs_client_trust']) {
      expect(nextSignInStep({ status, supportedSecondFactors: factors })).toEqual({
        kind: 'email_code', emailAddressId: 'idn_1', sentTo: 'c***@getverbatim.app',
      })
    }
  })
  it('a step the form cannot do says so', () => {
    expect(nextSignInStep({ status: 'needs_second_factor', supportedSecondFactors: [{ strategy: 'totp' }] }).kind).toBe('unsupported')
    expect(nextSignInStep({ status: 'needs_new_password' })).toEqual({ kind: 'unsupported', status: 'needs_new_password' })
    expect(nextSignInStep({ status: 'complete', createdSessionId: null }).kind).toBe('unsupported')
  })
})
