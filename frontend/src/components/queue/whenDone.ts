import type { SystemInfo, WhenDone } from '@/api/types'

/** Where the server runs, as far as the when-done choices go. */
export type WhenDoneHost = 'desktop' | 'web' | 'container'

export function whenDoneHost(info: SystemInfo | null | undefined): WhenDoneHost {
  if (info?.container === true) return 'container'
  return info?.mode === 'desktop' ? 'desktop' : 'web'
}

export interface WhenDoneChoice {
  value: WhenDone
  disabled: boolean
}

const POWER: ReadonlySet<WhenDone> = new Set(['sleep', 'shutdown'])

/**
 * The when-done choices the server can carry out. Quit is shown but disabled on a web server
 * (it says it is the desktop app's); a container offers no Sleep or Shut down, except the
 * saved value, shown disabled so that the select still names it.
 */
export function whenDoneChoices(host: WhenDoneHost, saved: WhenDone): WhenDoneChoice[] {
  const all: WhenDoneChoice[] = [
    { value: 'nothing', disabled: false },
    { value: 'notify', disabled: false },
    { value: 'quit', disabled: host !== 'desktop' },
    { value: 'sleep', disabled: host === 'container' },
    { value: 'shutdown', disabled: host === 'container' },
  ]
  if (host !== 'container') return all
  return all.filter((choice) => !POWER.has(choice.value) || choice.value === saved)
}
