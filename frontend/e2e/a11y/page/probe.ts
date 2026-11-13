/* oxlint-disable unicorn/consistent-function-scoping -- installProbe is sent as source text: what it calls must be inside it */
// The page side of the accessibility gate, type-checked with the DOM library on its own
// (tsconfig.e2e-page.json). `installProbe` is sent to the page as source text
// (`page.addInitScript`), so everything it uses at run time is declared inside it.
import type { ProbeApi, ProbeFinding, WalkStep } from '../probeApi'

/** Installs `window.__reframeA11y` and starts recording motion. Runs before the app's scripts. */
export function installProbe(): void {
  type Rgba = [number, number, number, number]
  type Rgb = [number, number, number]
  type Theme = 'light' | 'dark'

  // Attributes whose value names a place in the app; the ones that name a list item are
  // written without their value, so that a row's finding is the same finding in every row.
  const PLACE_ATTRIBUTES = [
    'data-card',
    'data-tab',
    'data-section',
    'data-section-link',
    'data-view',
    'data-list',
    'data-action',
    'data-field',
    'data-control',
    'data-edge',
    'data-crop-handle',
    'data-role',
    'data-line',
    'data-note',
    'data-cell',
    'data-path',
    'data-metadata',
  ]
  const ITEM_ATTRIBUTES = ['data-variable', 'data-name', 'data-preset', 'data-tag', 'data-group']
  const ANCHOR_ATTRIBUTES = [
    'data-card',
    'data-tab',
    'data-section',
    'data-view',
    'data-list',
    'data-path',
    'data-metadata',
    'data-crop-magnifier',
  ]
  const ANCHOR_CLASSES = [
    'nav-rail',
    'sources-panel',
    'workspace__header',
    'editor-tabs',
    'preview-panel',
    'status-bar',
    'command-preview',
    'p-dialog',
    'p-popover',
    'p-toast',
    'p-menu',
    'p-select-overlay',
    'p-autocomplete-overlay',
  ]
  // Classes that say what state an element is in, not what it is.
  const STATE_CLASS =
    /^(p-(focus|focus-visible|highlight|disabled|invalid|filled|inputwrapper-(filled|focus)|component|ripple|variant-.*|overlay-mask|hidden-.*|button-(sm|lg))|is-.*|router-link.*)$|--/

  function cssString(value: string): string {
    return JSON.stringify(value)
  }

  function token(element: Element): string {
    let part = element.tagName.toLowerCase()
    const own = [...element.classList].filter((name) => !STATE_CLASS.test(name))
    const app = own.filter((name) => !name.startsWith('p-'))
    for (const name of (app.length > 0 ? app : own).slice(0, 2)) part += `.${CSS.escape(name)}`
    for (const name of PLACE_ATTRIBUTES) {
      const value = element.getAttribute(name)
      if (value !== null) part += `[${name}=${cssString(value)}]`
    }
    for (const name of ITEM_ATTRIBUTES) {
      if (element.hasAttribute(name)) part += `[${name}]`
    }
    const role = element.getAttribute('role')
    if (part === element.tagName.toLowerCase() && role !== null) part += `[role=${cssString(role)}]`
    return part
  }

  function stableId(element: Element): string | null {
    const id = element.id
    return id !== '' && !/\d/.test(id) ? id : null
  }

  function isAnchor(element: Element): boolean {
    return (
      stableId(element) !== null ||
      ANCHOR_ATTRIBUTES.some((name) => element.hasAttribute(name)) ||
      ANCHOR_CLASSES.some((name) => element.classList.contains(name))
    )
  }

  function describe(element: Element | null): string {
    if (element === null) return '(none)'
    if (element === document.documentElement) return 'html'
    if (element === document.body) return 'body'
    const id = stableId(element)
    if (id !== null) return `#${CSS.escape(id)}`
    const self = token(element)
    for (
      let up = element.parentElement;
      up !== null && up !== document.body;
      up = up.parentElement
    ) {
      if (!isAnchor(up)) continue
      const upId = stableId(up)
      return `${upId !== null ? `#${CSS.escape(upId)}` : token(up)} ${self}`
    }
    return self
  }

  function describeAll(selectors: string[]): string[] {
    return selectors.map((selector) => {
      try {
        return describe(document.querySelector(selector))
      } catch {
        return selector
      }
    })
  }

  // Colours as painted: the browser's canvas reads any CSS colour syntax.
  const canvas = document.createElement('canvas')
  canvas.width = 1
  canvas.height = 1
  const pen = canvas.getContext('2d', { willReadFrequently: true })
  const parsed = new Map<string, Rgba>()

  function rgba(color: string): Rgba {
    const known = parsed.get(color)
    if (known !== undefined) return known
    let value: Rgba = [0, 0, 0, 0]
    if (pen !== null) {
      pen.clearRect(0, 0, 1, 1)
      pen.fillStyle = '#000'
      pen.fillStyle = color
      pen.fillRect(0, 0, 1, 1)
      const [r = 0, g = 0, b = 0, a = 0] = pen.getImageData(0, 0, 1, 1).data
      value = a === 0 ? [0, 0, 0, 0] : [(r * 255) / a, (g * 255) / a, (b * 255) / a, a / 255]
    }
    parsed.set(color, value)
    return value
  }

  function over([r, g, b, a]: Rgba, under: Rgb): Rgb {
    return [r * a + under[0] * (1 - a), g * a + under[1] * (1 - a), b * a + under[2] * (1 - a)]
  }

  function contrast(one: Rgb, other: Rgb): number {
    const luminance = (rgb: Rgb): number => {
      const [r = 0, g = 0, b = 0] = rgb.map((channel) => {
        const c = Math.min(255, Math.max(0, channel)) / 255
        return c <= 0.040_45 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * r + 0.7152 * g + 0.0722 * b
    }
    const [x, y] = [luminance(one), luminance(other)]
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
  }

  /** The colour behind `element`'s own box: the backgrounds of it and its parents, composed. */
  function backdrop(element: Element | null): Rgb {
    const layers: Rgba[] = []
    for (let box = element; box !== null; box = box.parentElement) {
      const layer = rgba(getComputedStyle(box).backgroundColor)
      if (layer[3] > 0) layers.push(layer)
      if (layer[3] >= 1) break
    }
    let under: Rgb = [255, 255, 255]
    for (const layer of layers.toReversed()) under = over(layer, under)
    return under
  }

  /**
   * The colours just outside `element`'s box, `distance` pixels out on each side: what a ring
   * drawn there lies on. An element can stick out of its parent (a slider's handle over its
   * thin track), so the parent's background is not always what is next to it.
   */
  function around(element: Element, distance: number): Rgb[] {
    const box = element.getBoundingClientRect()
    const x = box.left + box.width / 2
    const y = box.top + box.height / 2
    const points: [number, number][] = [
      [x, box.top - distance],
      [x, box.bottom + distance],
      [box.left - distance, y],
      [box.right + distance, y],
    ]
    const found: Rgb[] = []
    for (const [px, py] of points) {
      const hit = document.elementsFromPoint(px, py).find((under) => !element.contains(under))
      if (hit !== undefined) found.push(backdrop(hit))
    }
    return found.length > 0 ? found : [backdrop(element.parentElement)]
  }

  /** The best contrast of a ring of `color` against what it lies on. */
  function ring(color: string, behind: Rgb[]): number {
    return Math.max(...behind.map((under) => contrast(over(rgba(color), under), under)))
  }

  // --- motion ---

  const moved: ProbeFinding[] = []

  function seconds(list: string): number {
    return Math.max(
      0,
      ...list.split(',').map((part) => {
        const value = Number.parseFloat(part)
        if (Number.isNaN(value)) return 0
        return part.trim().endsWith('ms') ? value / 1000 : value
      }),
    )
  }

  addEventListener(
    'transitionrun',
    (event) => {
      if (event.target instanceof Element) {
        moved.push({
          rule: 'transition',
          target: describe(event.target),
          detail: event.propertyName,
        })
      }
    },
    true,
  )
  addEventListener(
    'animationstart',
    (event) => {
      if (!(event.target instanceof Element)) return
      const style = getComputedStyle(event.target, event.pseudoElement || null)
      if (seconds(style.animationDuration) > 0) {
        moved.push({
          rule: 'animation',
          target: describe(event.target),
          detail: event.animationName,
        })
      }
    },
    true,
  )
  const animate = Element.prototype.animate
  Element.prototype.animate = function (this: Element, keyframes, options) {
    const duration = typeof options === 'number' ? options : Number(options?.duration ?? 0) || 0
    if (duration > 0)
      moved.push({ rule: 'animate', target: describe(this), detail: `${duration} ms` })
    return animate.call(this, keyframes, options)
  }
  const SCROLL_LOOK_MS = 300
  // A scroll is smooth when the call returns before the position moves and it moves later.
  // Judged by its effect: the browsers scroll smoothly on request even with reduced motion.
  type Scroller = Element | Window
  function offsets(list: Scroller[]): string {
    return list
      .map((box) =>
        box instanceof Element
          ? `${box.scrollLeft},${box.scrollTop}`
          : `${box.scrollX},${box.scrollY}`,
      )
      .join(' ')
  }
  function watched(target: Scroller, what: string, scroll: () => void): void {
    const list: Scroller[] = [window]
    if (target instanceof Element) {
      for (let box: Element | null = target; box !== null; box = box.parentElement) list.push(box)
    }
    const before = offsets(list)
    scroll()
    if (offsets(list) !== before) return
    // Chromium starts a smooth scroll a few frames late: look again a moment later.
    setTimeout(() => {
      // A list that left the page reads 0 for its scroll positions: that is not a scroll.
      if (target instanceof Element && !target.isConnected) return
      if (offsets(list) === before) return
      const element = target instanceof Element ? target : null
      moved.push({
        rule: 'smooth-scroll',
        target: element === null ? 'window' : describe(element),
        detail: what,
      })
    }, SCROLL_LOOK_MS)
  }
  const scrollIntoView = Element.prototype.scrollIntoView
  Element.prototype.scrollIntoView = function (
    this: Element,
    options?: boolean | ScrollIntoViewOptions,
  ) {
    watched(this, 'scrollIntoView', () => scrollIntoView.call(this, options))
  }
  for (const name of ['scroll', 'scrollTo', 'scrollBy'] as const) {
    const element = Element.prototype[name]
    Element.prototype[name] = function (this: Element, ...args: unknown[]) {
      watched(this, name, () => (element as (...a: unknown[]) => void).apply(this, args))
    }
    const view = window[name]
    window[name] = function (...args: unknown[]) {
      watched(window, name, () => (view as (...a: unknown[]) => void).apply(window, args))
    } as typeof view
  }

  function motion(): ProbeFinding[] {
    const found = moved.splice(0)
    for (const animation of document.getAnimations()) {
      if (animation.playState !== 'running') continue
      const target = animation.effect instanceof KeyframeEffect ? animation.effect.target : null
      const name =
        animation instanceof CSSAnimation
          ? animation.animationName
          : animation instanceof CSSTransition
            ? animation.transitionProperty
            : 'script'
      found.push({ rule: 'running', target: describe(target), detail: name })
    }
    for (const element of document.querySelectorAll('*')) {
      for (const pseudo of [null, '::before', '::after']) {
        const style = getComputedStyle(element, pseudo)
        if (pseudo !== null && (style.content === 'none' || style.content === 'normal')) continue
        const where = pseudo === null ? '' : ` (${pseudo})`
        if (style.transitionProperty !== 'none' && seconds(style.transitionDuration) > 0) {
          found.push({
            rule: 'transition-duration',
            target: describe(element),
            detail: `${style.transitionProperty} ${style.transitionDuration}${where}`,
          })
        }
        if (style.animationName !== 'none' && seconds(style.animationDuration) > 0) {
          found.push({
            rule: 'animation-duration',
            target: describe(element),
            detail: `${style.animationName} ${style.animationDuration}${where}`,
          })
        }
        if (pseudo === null && style.scrollBehavior === 'smooth') {
          found.push({
            rule: 'smooth-scroll',
            target: describe(element),
            detail: 'scroll-behavior',
          })
        }
      }
    }
    return found
  }

  // --- the focus walk ---

  const PAINT = [
    'outlineStyle',
    'outlineWidth',
    'outlineColor',
    'outlineOffset',
    'boxShadow',
    'borderTopColor',
    'borderRightColor',
    'borderBottomColor',
    'borderLeftColor',
    'borderTopWidth',
    'backgroundColor',
    'color',
    'textDecorationLine',
  ] as const
  type Paint = Record<(typeof PAINT)[number], string> & { shown: boolean }
  type Part = { name: string; element: Element; pseudo: string | null }
  type Snapshot = Record<string, Paint>

  /** The elements that may draw an element's focus indicator. */
  function parts(element: Element): Part[] {
    const found: Part[] = [
      { name: 'self', element, pseudo: null },
      { name: 'self::before', element, pseudo: '::before' },
      { name: 'self::after', element, pseudo: '::after' },
    ]
    let up = element.parentElement
    for (let level = 1; level <= 3 && up !== null && up !== document.body; level += 1) {
      for (const pseudo of [null, '::before', '::after']) {
        found.push({ name: `parent ${level}${pseudo ?? ''}`, element: up, pseudo })
      }
      up = up.parentElement
    }
    const next = element.nextElementSibling
    if (next !== null) {
      for (const pseudo of [null, '::before', '::after']) {
        found.push({ name: `next${pseudo ?? ''}`, element: next, pseudo })
      }
    }
    const children = [...element.children].slice(0, 3)
    children.forEach((child, index) =>
      found.push({ name: `child ${index}`, element: child, pseudo: null }),
    )
    const active = element.getAttribute('aria-activedescendant')
    const option = active ? document.getElementById(active) : null
    if (option !== null) found.push({ name: 'active option', element: option, pseudo: null })
    return found
  }

  function shown(element: Element, pseudo: string | null): boolean {
    const box = element.getBoundingClientRect()
    if (box.width < 2 || box.height < 2) return false
    const style = getComputedStyle(element, pseudo)
    if (pseudo !== null && (style.content === 'none' || style.content === 'normal')) return false
    if (style.visibility !== 'visible') return false
    const { opacity, clipped } = chainOf(element)
    return !clipped && opacity > 0.1
  }

  // Opacity and clipping down the ancestors, for one look at the page.
  let chain = new Map<Element, { opacity: number; clipped: boolean }>()
  function chainOf(element: Element): { opacity: number; clipped: boolean } {
    const known = chain.get(element)
    if (known !== undefined) return known
    const own = getComputedStyle(element)
    const up =
      element.parentElement === null
        ? { opacity: 1, clipped: false }
        : chainOf(element.parentElement)
    const value = {
      opacity: up.opacity * Number(own.opacity),
      clipped: up.clipped || (own.clipPath !== 'none' && own.clipPath !== ''),
    }
    chain.set(element, value)
    return value
  }

  function look(part: Part): Paint {
    const style = getComputedStyle(part.element, part.pseudo)
    const paint = { shown: shown(part.element, part.pseudo) } as Paint
    for (const name of PAINT) paint[name] = style[name]
    return paint
  }

  function snapshot(element: Element): Snapshot {
    return Object.fromEntries(parts(element).map((part) => [part.name, look(part)]))
  }

  function shadows(value: string): { color: string; inset: boolean; size: number }[] {
    if (value === 'none') return []
    return value.split(/,(?![^(]*\))/).map((shadow) => {
      const color =
        /(rgba?|color|oklab|oklch|lab|lch|hsla?)\([^)]*\)|#[\da-f]+/i.exec(shadow)?.[0] ??
        'transparent'
      const lengths =
        shadow
          .replace(color, '')
          .match(/-?[\d.]+px/g)
          ?.map((length) => Math.abs(Number.parseFloat(length))) ?? []
      // Offsets, blur and spread: a shadow with all four 0 draws nothing.
      return { color, inset: /\binset\b/.test(shadow), size: Math.max(0, ...lengths) }
    })
  }

  /**
   * The contrast of what changed on one part when it took the focus, or null if nothing did.
   * A mark that appears (outline, shadow, underline) is measured against what lies next to it,
   * as 1.4.11 asks; a border, fill or text colour that changes is measured against its
   * unfocused colour, since it was there before and only the change shows the focus.
   */
  function change(part: Part | undefined, focused: Paint, unfocused: Paint): number | null {
    if (!focused.shown || part === undefined) return null
    const element = part.element
    const inside = backdrop(element)
    const outside = backdrop(element.parentElement)
    let best: number | null = null
    const take = (value: number) => {
      best = Math.max(best ?? 0, value)
    }
    const outlined = (paint: Paint) =>
      paint.outlineStyle !== 'none' && Number.parseFloat(paint.outlineWidth) > 0
    if (
      outlined(focused) &&
      (!outlined(unfocused) ||
        focused.outlineColor !== unfocused.outlineColor ||
        focused.outlineWidth !== unfocused.outlineWidth ||
        focused.outlineOffset !== unfocused.outlineOffset)
    ) {
      const offset = Number.parseFloat(focused.outlineOffset)
      const middle = offset + Number.parseFloat(focused.outlineWidth) / 2
      take(ring(focused.outlineColor, middle <= 0 ? [inside] : around(element, middle)))
    }
    if (focused.boxShadow !== unfocused.boxShadow) {
      for (const shadow of shadows(focused.boxShadow)) {
        if (shadow.size === 0) continue
        take(ring(shadow.color, shadow.inset ? [inside] : around(element, shadow.size / 2)))
      }
    }
    for (const side of ['Top', 'Right', 'Bottom', 'Left'] as const) {
      const key = `border${side}Color` as const
      if (focused[key] !== unfocused[key] && Number.parseFloat(focused.borderTopWidth) > 0) {
        take(contrast(over(rgba(focused[key]), outside), over(rgba(unfocused[key]), outside)))
      }
    }
    if (focused.backgroundColor !== unfocused.backgroundColor) {
      take(
        contrast(
          over(rgba(focused.backgroundColor), outside),
          over(rgba(unfocused.backgroundColor), outside),
        ),
      )
    }
    if (focused.color !== unfocused.color) {
      take(contrast(over(rgba(focused.color), inside), over(rgba(unfocused.color), inside)))
    }
    if (focused.textDecorationLine !== unfocused.textDecorationLine) {
      take(contrast(over(rgba(focused.color), inside), inside))
    }
    return best
  }

  /** A focus-indicator finding for `element`, or null when its indicator is there and 3:1. */
  function judge(element: Element, focused: Snapshot, unfocused: Snapshot): ProbeFinding | null {
    const byName = new Map(parts(element).map((part) => [part.name, part]))
    let best: number | null = null
    let where = ''
    for (const [name, paint] of Object.entries(focused)) {
      const part = byName.get(name)
      if (part === undefined) continue
      // A part that came with the focus (the option a list's focus points at) is looked at now.
      const before = unfocused[name] ?? look(part)
      const value = change(part, paint, before)
      if (value !== null && value > (best ?? -1)) {
        best = value
        where = name
      }
    }
    const target = describe(element)
    if (best === null) return { rule: 'no-indicator', target }
    if (best < 3) {
      return { rule: 'indicator-contrast', target, detail: `${best.toFixed(2)}:1 on ${where}` }
    }
    return null
  }

  /** Whether something else covers `element` wherever it could be seen. */
  function obscured(element: Element): boolean {
    const whole = element.getBoundingClientRect()
    // The part inside the window: a tall panel's middle can lie outside it.
    const left = Math.max(whole.left, 0)
    const top = Math.max(whole.top, 0)
    const right = Math.min(whole.right, window.innerWidth)
    const bottom = Math.min(whole.bottom, window.innerHeight)
    if (whole.width === 0 || whole.height === 0) return false
    if (right <= left || bottom <= top) return true
    const box = { left, top, right, bottom, width: right - left, height: bottom - top }
    const insetX = Math.min(box.width / 4, 4)
    const insetY = Math.min(box.height / 4, 4)
    const points: [number, number][] = [
      [box.left + box.width / 2, box.top + box.height / 2],
      [box.left + insetX, box.top + insetY],
      [box.right - insetX, box.top + insetY],
      [box.left + insetX, box.bottom - insetY],
      [box.right - insetX, box.bottom - insetY],
    ]
    return !points.some(([x, y]) => {
      const hit = document.elementFromPoint(x, y)
      if (hit === null) return false
      if (hit === element || element.contains(hit) || hit.contains(element)) return true
      return hit instanceof HTMLLabelElement && hit.control === element
    })
  }

  const TABBABLE =
    'a[href], area[href], button, input, select, textarea, summary, iframe, audio[controls], video[controls], [tabindex], [contenteditable]'

  let darkClass = ''
  let limit = 0
  let region: string | null = null
  let first: Element | null = null
  let previous: { element: Element; focused: Record<Theme, Snapshot> } | null = null
  let settling: { stuck: boolean } | null = null
  let outside = 0
  let stops = 0
  let pageFocused = true
  // Each stop unfocused, taken before the walk: some widgets (PrimeVue's Select) keep their
  // focused look for a while after a blur, so a look taken once the focus has moved is not it.
  let baseline = new Map<Element, Record<Theme, Snapshot>>()

  function inTheme<T>(theme: Theme, read: () => T): T {
    const root = document.documentElement
    const was = root.classList.contains(darkClass)
    root.classList.toggle(darkClass, theme === 'dark')
    try {
      return read()
    } finally {
      root.classList.toggle(darkClass, was)
    }
  }

  function walkStart(dark: string, most: number, within: string | null): void {
    chain = new Map()
    darkClass = dark
    limit = most
    region = within
    first = null
    previous = null
    settling = null
    outside = 0
    stops = 0
    pageFocused = document.hasFocus()
    const scope = within === null ? document : (document.querySelector(within) ?? document)
    const candidates = [...scope.querySelectorAll(TABBABLE)].filter(
      (element) => element !== document.activeElement,
    )
    const light = inTheme('light', () => candidates.map(snapshot))
    const darkLooks = inTheme('dark', () => candidates.map(snapshot))
    baseline = new Map(
      candidates.map((element, index) => [
        element,
        { light: light[index] as Snapshot, dark: darkLooks[index] as Snapshot },
      ]),
    )
  }

  function walkStep(): WalkStep {
    chain = new Map()
    const findings: WalkStep['findings'] = { light: [], dark: [] }
    let judged: { element: Element; focused: Record<Theme, Snapshot> } | null = null
    let unfocused: Record<Theme, Snapshot> | undefined
    let done = false
    if (previous !== null) {
      unfocused = baseline.get(previous.element)
      // Tab left the focus where it was, or took it out of the page (Firefox keeps the last
      // element as the active one then): the walk is over.
      const stuck =
        settling?.stuck ??
        (document.activeElement === previous.element || (pageFocused && !document.hasFocus()))
      if (unfocused === undefined && settling === null) {
        // Only a blur shows the element unfocused.
        if (stuck && previous.element instanceof HTMLElement) previous.element.blur()
        settling = { stuck }
        return { done: false, settle: true, stops, findings }
      }
      done = stuck
      settling = null
      judged = previous
      previous = null
    }
    let next: Element | null = null
    const active = document.activeElement
    if (done) {
      // The walk stays put.
    } else if (region !== null && !(document.querySelector(region)?.contains(active) ?? false)) {
      done = true
    } else if (active === null || active === document.body || active === document.documentElement) {
      outside += 1
      done = outside >= 2
    } else {
      outside = 0
      done = active === first || stops >= limit
      if (!done) {
        first ??= active
        stops += 1
        next = active
      }
    }
    if (next !== null && obscured(next)) {
      for (const theme of ['light', 'dark'] as const) {
        findings[theme].push({ rule: 'obscured', target: describe(next) })
      }
    }
    // The page's own theme first: the other one costs a restyle of the whole page.
    const current: Theme = document.documentElement.classList.contains(darkClass) ? 'dark' : 'light'
    const looks: Partial<Record<Theme, Snapshot>> = {}
    for (const theme of [current, current === 'dark' ? 'light' : 'dark'] as const) {
      inTheme(theme, () => {
        if (judged !== null) {
          const before = unfocused?.[theme] ?? snapshot(judged.element)
          const finding = judge(judged.element, judged.focused[theme], before)
          if (finding !== null) findings[theme].push(finding)
        }
        if (next !== null) looks[theme] = snapshot(next)
      })
    }
    if (next !== null && looks.light !== undefined && looks.dark !== undefined) {
      previous = { element: next, focused: { light: looks.light, dark: looks.dark } }
    }
    return { done, settle: false, stops, findings }
  }

  function settled(): Promise<void> {
    return new Promise((resolve) =>
      requestAnimationFrame(() =>
        requestAnimationFrame(() => setTimeout(resolve, SCROLL_LOOK_MS + 50)),
      ),
    )
  }

  function enterRegion(selector: string): boolean {
    const box = document.querySelector<HTMLElement>(selector)
    if (box === null) return false
    if (!box.hasAttribute('tabindex')) {
      box.setAttribute('tabindex', '-1')
      box.dataset.gateTabindex = ''
    }
    box.focus({ preventScroll: true })
    return true
  }

  function leaveRegion(selector: string): void {
    const box = document.querySelector<HTMLElement>(selector)
    if (box?.dataset.gateTabindex === undefined) return
    box.removeAttribute('tabindex')
    delete box.dataset.gateTabindex
  }

  const api: ProbeApi = {
    describeAll,
    motion,
    settled,
    enterRegion,
    leaveRegion,
    walkStart,
    walkStep,
  }
  // The name is `PROBE_GLOBAL` of probeApi.ts; this function cannot import it at run time.
  Reflect.set(window, '__reframeA11y', api)
}
