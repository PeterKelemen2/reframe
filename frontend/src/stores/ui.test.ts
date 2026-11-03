import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useUiStore } from './ui'

describe('ui.reveal', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('opens the advanced panel for an advanced option and for the custom parameters', () => {
    const ui = useUiStore()
    ui.reveal('video.advanced.bframes')
    expect([ui.activeTab, ui.advancedOpen]).toEqual(['video', true])

    ui.advancedOpen = false
    ui.reveal('video.custom_params')
    expect(ui.advancedOpen).toBe(true)
  })

  it('leaves the advanced panel closed for the other video fields', () => {
    const ui = useUiStore()
    ui.reveal('video.encoder')
    expect([ui.activeTab, ui.advancedOpen]).toEqual(['video', false])
  })
})
