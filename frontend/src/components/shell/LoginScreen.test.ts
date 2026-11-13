import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { useSystemStore } from '@/stores/system'

import LoginScreen from './LoginScreen.vue'
import { appI18n, mountShell } from './testing'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountLogin(mode: 'token' | 'password') {
  const result = await mountShell(LoginScreen, {
    setup: () => {
      useSystemStore().auth = { mode, authenticated: false }
    },
  })
  mounted.push(result.wrapper)
  const system = useSystemStore()
  const login = vi.fn<(password: string) => Promise<boolean>>()
  const loginWithToken = vi.fn<(token: string) => Promise<boolean>>()
  system.login = login
  system.loginWithToken = loginWithToken
  const { wrapper } = result
  async function submit(value: string): Promise<void> {
    await wrapper.find('input').setValue(value)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
  }
  // The issue's text without its screen-reader prefix ("Error: ").
  const problem = () => {
    const issue = wrapper.find('.rf-field__issue')
    return issue.exists() ? issue.text().replace(/^Error: /, '') : null
  }
  return { wrapper, login, loginWithToken, submit, problem }
}

describe('the login screen', () => {
  it('asks for the token in token mode and sends it trimmed', async () => {
    const { wrapper, loginWithToken, login, submit, problem } = await mountLogin('token')
    expect(wrapper.find('label').text()).toBe('Access token')
    loginWithToken.mockResolvedValue(true)
    await submit('  abc123 \n')
    expect(loginWithToken).toHaveBeenCalledWith('abc123')
    expect(login).not.toHaveBeenCalled()
    expect(problem()).toBeNull()
  })

  it('says so inline when the server does not take the token', async () => {
    const { loginWithToken, submit, problem, wrapper } = await mountLogin('token')
    loginWithToken.mockResolvedValue(false)
    await submit('wrong')
    expect(problem()).toBe('The server does not accept this token.')
    expect(wrapper.find('input').attributes('aria-describedby')).toBeTruthy()
  })

  it('asks for the password in password mode and sends it as typed', async () => {
    const { wrapper, login, loginWithToken, submit, problem } = await mountLogin('password')
    expect(wrapper.find('label').text()).toBe('Password')
    login.mockResolvedValue(false)
    await submit(' correct horse ')
    expect(login).toHaveBeenCalledWith(' correct horse ')
    expect(loginWithToken).not.toHaveBeenCalled()
    expect(problem()).toBe('The password is wrong.')
  })

  it("shows another refusal (too many attempts, no server) with the server's words", async () => {
    const { login, submit, problem } = await mountLogin('password')
    login.mockRejectedValue(
      new ApiError(429, {
        type: 'about:blank',
        title: 'Too many login attempts',
        detail: 'Try again in 30 seconds.',
        status: 429,
        code: 'auth.rate_limited',
      }),
    )
    await submit('pw')
    expect(problem()).toBe('Too many login attempts: Try again in 30 seconds.')
  })

  it("words the server's refusal with one message, which a translation may reorder", async () => {
    const { wrapper, login, submit, problem } = await mountLogin('password')
    appI18n(wrapper).global.mergeLocaleMessage('en', {
      shell: { login: { refused: '{detail} ({title})' } },
    })
    login.mockRejectedValue(
      new ApiError(503, {
        type: 'about:blank',
        title: 'Server busy',
        detail: 'Wait a moment.',
        status: 503,
        code: 'server.busy',
      }),
    )
    await submit('pw')
    expect(problem()).toBe('Wait a moment. (Server busy)')
  })

  it('sends nothing for an empty field', async () => {
    const { login, submit, problem } = await mountLogin('password')
    await submit('   ')
    expect(login).not.toHaveBeenCalled()
    expect(problem()).toBe('Enter a value first.')
  })
})
