import { onBeforeUnmount, onMounted, watch, type WatchSource } from 'vue'

import { DARK_MODE_CLASS } from '@/styles/theme'

function take(rule: CSSStyleRule, into: Map<string, string>): void {
  for (let index = 0; index < rule.style.length; index += 1) {
    const name = rule.style[index]
    if (name?.startsWith('--')) into.set(name, rule.style.getPropertyValue(name))
  }
}

/**
 * Custom properties are resolved where they are declared: the root's `--p-button-background:
 * var(--p-primary-color)` reaches a dark box already resolved to the light value. So a box in
 * one scheme while the page shows the other declares every root property again, in the order of
 * the cascade, with that scheme's values.
 */
function collect(): { light: Map<string, string>; dark: Map<string, string> } {
  const light = new Map<string, string>()
  const dark = new Map<string, string>()
  const root = document.documentElement
  const matchesRoot = (part: string): boolean => {
    try {
      return root.matches(part.replace(`.${DARK_MODE_CLASS}`, '').trim() || ':root')
    } catch {
      return false
    }
  }
  const walk = (rules: CSSRuleList) => {
    for (const rule of rules) {
      if (rule instanceof CSSMediaRule) {
        if (matchMedia(rule.conditionText).matches) walk(rule.cssRules)
      } else if (rule instanceof CSSStyleRule) {
        const parts = rule.selectorText.split(',').map((part) => part.trim())
        const forDark = parts.some((part) => part.includes(DARK_MODE_CLASS) && matchesRoot(part))
        const forRoot = parts.some(
          (part) =>
            !part.includes(DARK_MODE_CLASS) && part.startsWith(':root') && matchesRoot(part),
        )
        if (forRoot) take(rule, light)
        if (forDark) take(rule, dark)
      } else if ('cssRules' in rule) {
        walk((rule as CSSGroupingRule).cssRules)
      }
    }
  }
  for (const sheet of document.styleSheets) {
    try {
      walk(sheet.cssRules)
    } catch {
      // A sheet of another origin cannot be read; it declares none of the app's properties.
    }
  }
  return { light, dark: new Map([...light, ...dark]) }
}

function block(selector: string, properties: Map<string, string>): string {
  const lines = [...properties].map(([name, value]) => `  ${name}: ${value};`)
  return `${selector} {\n${lines.join('\n')}\n}`
}

/**
 * Gives `.{prefix}--light` and `.{prefix}--dark` the custom properties of each colour scheme, so
 * that the two can be seen side by side. Built again when `sources` change (theme, density) and
 * when a component adds its styles.
 */
export function useSchemeScopes(prefix: string, sources: WatchSource[]): void {
  let style: HTMLStyleElement | null = null
  let observer: MutationObserver | null = null
  let queued = false

  function build(): void {
    queued = false
    if (style === null) return
    const { light, dark } = collect()
    style.textContent = `${block(`.${prefix}--light`, light)}\n${block(`.${prefix}--dark`, dark)}`
  }

  function schedule(): void {
    if (queued) return
    queued = true
    requestAnimationFrame(build)
  }

  onMounted(() => {
    style = document.createElement('style')
    style.dataset.sandboxScopes = prefix
    document.head.append(style)
    build()
    observer = new MutationObserver((records) => {
      const added = records.some(
        (record) =>
          record.target !== style && [...record.addedNodes].some((node) => node !== style),
      )
      if (added) {
        schedule()
      }
    })
    observer.observe(document.head, { childList: true, subtree: true, characterData: true })
  })

  watch(sources, schedule, { flush: 'post' })

  onBeforeUnmount(() => {
    observer?.disconnect()
    style?.remove()
    style = null
  })
}
