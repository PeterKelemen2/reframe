/* oxlint-disable unicorn/consistent-function-scoping -- installProbe is sent as source text: what it calls must be inside it */
// The page side of the accessibility gate, type-checked with the DOM library on its own
// (tsconfig.e2e-page.json). `installProbe` is sent to the page as source text
// (`page.addInitScript`), so everything it uses at run time is declared inside it.
import type {
  ProbeApi,
  ProbeFinding,
  Rect,
  ShotPlace,
  ThemeFindings,
  ThemeName,
  WalkStep,
} from '../probeApi'

/** Installs `window.__reframeA11y` and starts recording motion. Runs before the app's scripts. */
export function installProbe(): void {
  type Rgba = [number, number, number, number]
  type Rgb = [number, number, number]
  type Theme = ThemeName

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

  // --- colours as painted ---

  // The browser's canvas reads any CSS colour syntax.
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
      // getImageData gives straight (not premultiplied) RGBA.
      const [r = 0, g = 0, b = 0, a = 0] = pen.getImageData(0, 0, 1, 1).data
      value = a === 0 ? [0, 0, 0, 0] : [r, g, b, a / 255]
    }
    parsed.set(color, value)
    return value
  }

  function faded([r, g, b, a]: Rgba, opacity: number): Rgba {
    return [r, g, b, a * opacity]
  }

  function over([r, g, b, a]: Rgba, under: Rgb): Rgb {
    return [r * a + under[0] * (1 - a), g * a + under[1] * (1 - a), b * a + under[2] * (1 - a)]
  }

  function luminance(rgb: Rgb): number {
    const [r = 0, g = 0, b = 0] = rgb.map((channel) => {
      const c = Math.min(255, Math.max(0, channel)) / 255
      return c <= 0.040_45 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
    })
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }

  function contrast(one: Rgb, other: Rgb): number {
    const [x, y] = [luminance(one), luminance(other)]
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
  }

  /** The lowest contrast of `fg` against `bg`, both painted over each of `unders`. */
  function worst(fg: Rgba, bg: Rgba | null, unders: Rgb[]): number {
    return Math.min(
      ...unders.map((under) => contrast(over(fg, under), bg === null ? under : over(bg, under))),
    )
  }

  const COLOR_WORDS = /(rgba?|color|oklab|oklch|lab|lch|hsla?|hwb)\([^)]*\)|#[\da-f]+|[a-z]+/gi

  /** The colours of the gradients in a `background-image`; null when it holds a picture. */
  function gradientColors(image: string): Rgba[] | null {
    if (image === 'none' || image === '') return []
    if (/url\(|image-set\(|element\(/i.test(image)) return null
    const found: Rgba[] = []
    for (const [word] of image.matchAll(COLOR_WORDS)) {
      if (/^[a-z]+$/i.test(word) && !CSS.supports('color', word)) continue
      found.push(rgba(word))
    }
    return found
  }

  function isRaster(element: Element): boolean {
    return (
      element instanceof HTMLImageElement ||
      element instanceof HTMLCanvasElement ||
      element instanceof HTMLVideoElement ||
      element instanceof HTMLIFrameElement
    )
  }

  // Opacity, clipping and filters down the ancestors, for one look at the page.
  type Chain = { opacity: number; clipped: boolean; filtered: boolean }
  let chain = new Map<Element, Chain>()
  function chainOf(element: Element): Chain {
    const known = chain.get(element)
    if (known !== undefined) return known
    const own = getComputedStyle(element)
    const up: Chain =
      element.parentElement === null
        ? { opacity: 1, clipped: false, filtered: false }
        : chainOf(element.parentElement)
    const value = {
      opacity: up.opacity * Number(own.opacity),
      clipped: up.clipped || (own.clipPath !== 'none' && own.clipPath !== ''),
      filtered:
        up.filtered ||
        own.filter !== 'none' ||
        own.mixBlendMode !== 'normal' ||
        (own.backdropFilter !== undefined && own.backdropFilter !== 'none'),
    }
    chain.set(element, value)
    return value
  }

  type Backdrop = { colors: Rgb[]; image: boolean }

  /**
   * The colours behind `element`'s content: the backgrounds and gradients of it and its parents,
   * each faded by the opacity it is painted with, composed. A gradient gives each of its
   * colours, so a check can take the worst. `image`: a picture is among them.
   */
  function backdrop(element: Element | null): Backdrop {
    const layers: { color: Rgba; gradient: Rgba[] }[] = []
    let image = false
    for (let box = element; box !== null; box = box.parentElement) {
      const style = getComputedStyle(box)
      const opacity = chainOf(box).opacity
      const color = faded(rgba(style.backgroundColor), opacity)
      const gradient = gradientColors(style.backgroundImage)
      if (gradient === null || isRaster(box)) image = true
      const tints = (gradient ?? []).map((tint) => faded(tint, opacity))
      if (color[3] > 0 || tints.length > 0) layers.push({ color, gradient: tints })
      if (color[3] >= 1) break
    }
    let colors: Rgb[] = [[255, 255, 255]]
    for (const layer of layers.toReversed()) {
      colors = colors.map((under) => over(layer.color, under))
      if (layer.gradient.length > 0) {
        colors = layer.gradient.flatMap((tint) => colors.map((under) => over(tint, under)))
      }
      if (colors.length > 16) {
        const sorted = colors.toSorted((a, b) => luminance(a) - luminance(b))
        colors = [sorted[0] as Rgb, sorted.at(-1) as Rgb]
      }
    }
    return { colors, image }
  }

  type Box = { left: number; top: number; right: number; bottom: number }

  /** The boxes of the ancestors of `element` that clip what overflows them, and the window. */
  function clipBoxes(element: Element): Box[] {
    const found: Box[] = [{ left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight }]
    for (let up = element.parentElement; up !== null; up = up.parentElement) {
      const style = getComputedStyle(up)
      const clips =
        style.overflowX !== 'visible' ||
        style.overflowY !== 'visible' ||
        /paint|strict|content/.test(style.contain)
      if (!clips || up === document.documentElement || up === document.body) continue
      const box = up.getBoundingClientRect()
      found.push({
        left: box.left + Number.parseFloat(style.borderLeftWidth),
        right: box.right - Number.parseFloat(style.borderRightWidth),
        top: box.top + Number.parseFloat(style.borderTopWidth),
        bottom: box.bottom - Number.parseFloat(style.borderBottomWidth),
      })
    }
    return found
  }

  function insideAll(boxes: Box[], x: number, y: number): boolean {
    return boxes.every((box) => x >= box.left && x <= box.right && y >= box.top && y <= box.bottom)
  }

  /** The part of `element` a user can see: its box cut by the clipping ancestors and the window. */
  function visibleBox(element: Element, boxes = clipBoxes(element)): Box {
    const own = element.getBoundingClientRect()
    const seen = { left: own.left, top: own.top, right: own.right, bottom: own.bottom }
    for (const box of boxes) {
      seen.left = Math.max(seen.left, box.left)
      seen.top = Math.max(seen.top, box.top)
      seen.right = Math.min(seen.right, box.right)
      seen.bottom = Math.min(seen.bottom, box.bottom)
    }
    const empty = seen.right <= seen.left || seen.bottom <= seen.top
    return empty ? { left: own.left, top: own.top, right: own.right, bottom: own.bottom } : seen
  }

  type Side = { contrast: number; image: boolean }

  /**
   * A ring of `color` drawn `distance` pixels outside `element`, side by side: its contrast
   * against what lies there (an element can stick out of its parent, so the parent's background
   * is not always what is next to it), 1 where an ancestor clips the ring away.
   */
  function ringSides(element: Element, color: Rgba, distance: number): Side[] {
    const box = element.getBoundingClientRect()
    const boxes = clipBoxes(element)
    // Each side is looked at across from the middle of what can be seen of the element.
    const seen = visibleBox(element, boxes)
    const x = (seen.left + seen.right) / 2
    const y = (seen.top + seen.bottom) / 2
    const points: [number, number][] = [
      [x, box.top - distance],
      [x, box.bottom + distance],
      [box.left - distance, y],
      [box.right + distance, y],
    ]
    const sides: Side[] = []
    for (const [px, py] of points) {
      if (!insideAll(boxes, px, py)) {
        sides.push({ contrast: 1, image: false })
        continue
      }
      const hit = document.elementsFromPoint(px, py).find((under) => !element.contains(under))
      if (hit === undefined) continue
      const behind = backdrop(hit)
      sides.push({ contrast: worst(color, null, behind.colors), image: behind.image })
    }
    return sides
  }

  /** The contrast a ring reaches on at least half of its sides. */
  function ring(sides: Side[]): number {
    const sorted = sides.map((side) => side.contrast).toSorted((a, b) => b - a)
    return sorted[Math.floor((sorted.length - 1) / 2)] ?? 1
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
  // An animation built by hand (`new Animation(effect)`) starts through `play`; `animate` does not
  // call it, so nothing is counted twice.
  const play = Animation.prototype.play
  Animation.prototype.play = function (this: Animation) {
    const timing = this.effect?.getComputedTiming()
    const duration = Number(timing?.duration ?? 0) || 0
    if (duration > 0 && !(this instanceof CSSAnimation) && !(this instanceof CSSTransition)) {
      const target = this.effect instanceof KeyframeEffect ? this.effect.target : null
      moved.push({ rule: 'animate', target: describe(target), detail: `${duration} ms (play)` })
    }
    play.call(this)
  }
  // A script tween: frame callbacks that change an element's style in frame after frame.
  const FRAME_LOOP = 10
  const styleWatch = new MutationObserver(() => {})
  styleWatch.observe(document, { attributes: true, attributeFilter: ['style'], subtree: true })
  let frameStreak = 0
  let lastFrame = -1
  const frame = window.requestAnimationFrame.bind(window)
  window.requestAnimationFrame = (callback) =>
    frame((time) => {
      styleWatch.takeRecords()
      callback(time)
      const records = styleWatch.takeRecords()
      if (records.length === 0 || time === lastFrame) return
      frameStreak = lastFrame >= 0 && time - lastFrame < 50 ? frameStreak + 1 : 1
      lastFrame = time
      if (frameStreak === FRAME_LOOP) {
        const target = records[0]?.target
        moved.push({
          rule: 'frame-loop',
          target: describe(target instanceof Element ? target : null),
          detail: `style changed in ${FRAME_LOOP} frames in a row`,
        })
      }
    })
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
  let scrollCalls = 0
  function watched(target: Scroller, what: string, scroll: () => void): void {
    const list: Scroller[] = [window]
    if (target instanceof Element) {
      for (let box: Element | null = target; box !== null; box = box.parentElement) list.push(box)
    }
    const before = offsets(list)
    const call = (scrollCalls += 1)
    const focused = document.activeElement
    scroll()
    if (offsets(list) !== before) return
    // Chromium starts a smooth scroll a few frames late: look again a moment later.
    setTimeout(() => {
      // A list that left the page reads 0 for its scroll positions: that is not a scroll.
      if (target instanceof Element && !target.isConnected) return
      // A later scroll, or a focus that moved (it scrolls into view), may have moved it.
      if (call !== scrollCalls || document.activeElement !== focused) return
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

  // --- what can take the focus ---

  const TABBABLE =
    'a[href], area[href], button, input, select, textarea, summary, iframe, audio[controls], video[controls], [tabindex], [contenteditable]'
  // Items that arrow keys move the focus (or the active descendant) to.
  const ITEM =
    '[role="option"], [role="treeitem"], [role="tab"], [role="menuitem"], [role="menuitemradio"], [role="menuitemcheckbox"]'
  const COMPOSITE =
    '[role="tablist"], [role="tree"], [role="treegrid"], [role="menu"], [role="menubar"], [role="listbox"], [role="grid"]'

  function rendered(element: Element): boolean {
    if (element.getClientRects().length === 0) return false
    if (element.closest('[inert]') !== null) return false
    return getComputedStyle(element).visibility === 'visible'
  }

  function tabbable(element: Element): boolean {
    return (
      element instanceof HTMLElement &&
      element.matches(TABBABLE) &&
      element.tabIndex >= 0 &&
      !element.matches(':disabled') &&
      rendered(element)
    )
  }

  /** What a user can put the focus on: a Tab stop, or an item an arrow key reaches. */
  function isTarget(element: Element): boolean {
    return tabbable(element) || (element.matches(ITEM) && rendered(element))
  }

  /** Whether `box` holds no focus target but `element` (and what is inside it). */
  function onlyFor(box: Element, element: Element): boolean {
    for (const other of box.querySelectorAll(`${TABBABLE}, ${ITEM}`)) {
      if (other === element || element.contains(other) || other.contains(element)) continue
      if (isTarget(other)) return false
    }
    return true
  }

  // --- the focus indicator ---

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
    'borderRightWidth',
    'borderBottomWidth',
    'borderLeftWidth',
    'backgroundColor',
    'backgroundImage',
    'color',
    'textDecorationLine',
  ] as const
  type Rings = { outline: number | null; shadows: number[] }
  type Paint = Record<(typeof PAINT)[number], string> & {
    shown: boolean
    opacity: number
    /** Measured while focused: the element may be scrolled out of view by the time it is judged. */
    rings?: Rings
  }
  type Part = { name: string; element: Element; pseudo: string | null; own: boolean }
  type Snapshot = Record<string, Paint>

  /**
   * The elements that may draw an element's focus indicator. A part around the element
   * (a parent, the next sibling) shows its focus only if it holds no other focus target: a
   * toolbar that changes on `:focus-within` does not say which of its buttons has the focus.
   */
  function parts(element: Element): Part[] {
    const found: Part[] = [
      { name: 'self', element, pseudo: null, own: true },
      { name: 'self::before', element, pseudo: '::before', own: true },
      { name: 'self::after', element, pseudo: '::after', own: true },
    ]
    let up = element.parentElement
    for (let level = 1; level <= 3 && up !== null && up !== document.body; level += 1) {
      const own = !isTarget(up) && onlyFor(up, element)
      for (const pseudo of [null, '::before', '::after']) {
        found.push({ name: `parent ${level}${pseudo ?? ''}`, element: up, pseudo, own })
      }
      up = up.parentElement
    }
    const next = element.nextElementSibling
    if (next !== null) {
      const own = !isTarget(next) && onlyFor(next, element)
      for (const pseudo of [null, '::before', '::after']) {
        found.push({ name: `next${pseudo ?? ''}`, element: next, pseudo, own })
      }
    }
    const children = [...element.children].slice(0, 3)
    children.forEach((child, index) =>
      found.push({ name: `child ${index}`, element: child, pseudo: null, own: true }),
    )
    const option = activeOption(element)
    if (option !== null) {
      found.push({ name: 'active option', element: option, pseudo: null, own: true })
    }
    return found
  }

  /** The option that `element`'s `aria-activedescendant` names. */
  function activeOption(element: Element): Element | null {
    const id = element.getAttribute('aria-activedescendant')
    return id ? document.getElementById(id) : null
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

  function look(part: Part, measure = false): Paint {
    const style = getComputedStyle(part.element, part.pseudo)
    const paint = {
      shown: shown(part.element, part.pseudo),
      opacity: chainOf(part.element).opacity,
    } as Paint
    for (const name of PAINT) paint[name] = style[name]
    if (measure && paint.shown) paint.rings = rings(part, paint)
    return paint
  }

  function snapshot(element: Element, measure = false): Snapshot {
    return Object.fromEntries(parts(element).map((part) => [part.name, look(part, measure)]))
  }

  function outlined(paint: Paint): boolean {
    return paint.outlineStyle !== 'none' && Number.parseFloat(paint.outlineWidth) > 0
  }

  /** The contrast of the part's outline and of each of its shadows against what they lie on. */
  function rings(part: Part, paint: Paint): Rings {
    const element = part.element
    const fade = (color: string) => faded(rgba(color), paint.opacity)
    let inside: Rgb[] | null = null
    const within = (color: Rgba) => worst(color, null, (inside ??= backdrop(element).colors))
    let outline: number | null = null
    if (outlined(paint)) {
      const offset = Number.parseFloat(paint.outlineOffset)
      const middle = offset + Number.parseFloat(paint.outlineWidth) / 2
      const color = fade(paint.outlineColor)
      outline = middle <= 0 ? within(color) : ring(ringSides(element, color, middle))
    }
    const found: number[] = []
    for (const shadow of shadows(paint.boxShadow)) {
      if (shadow.size === 0) continue
      const color = fade(shadow.color)
      found.push(shadow.inset ? within(color) : ring(ringSides(element, color, shadow.size / 2)))
    }
    return { outline, shadows: found }
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
   * unfocused colour, since it was there before and only the change shows the focus. Colours
   * are faded by the opacity they are painted with; against a gradient, its worst colour counts.
   */
  function change(part: Part, focused: Paint, unfocused: Paint): number | null {
    if (!focused.shown) return null
    const element = part.element
    const inside = backdrop(element).colors
    const outside = backdrop(element.parentElement).colors
    const fade = (color: string) => faded(rgba(color), focused.opacity)
    const was = (color: string) => faded(rgba(color), unfocused.opacity)
    let best: number | null = null
    const take = (value: number) => {
      best = Math.max(best ?? 0, value)
    }
    const measured = focused.rings ?? rings(part, focused)
    if (
      measured.outline !== null &&
      (!outlined(unfocused) ||
        focused.outlineColor !== unfocused.outlineColor ||
        focused.outlineWidth !== unfocused.outlineWidth ||
        focused.outlineOffset !== unfocused.outlineOffset)
    ) {
      take(measured.outline)
    }
    if (focused.boxShadow !== unfocused.boxShadow) {
      for (const value of measured.shadows) take(value)
    }
    for (const side of ['Top', 'Right', 'Bottom', 'Left'] as const) {
      const key = `border${side}Color` as const
      const width = Number.parseFloat(focused[`border${side}Width`])
      if (focused[key] !== unfocused[key] && width > 0) {
        take(worst(fade(focused[key]), was(unfocused[key]), outside))
      }
    }
    if (focused.backgroundColor !== unfocused.backgroundColor) {
      take(worst(fade(focused.backgroundColor), was(unfocused.backgroundColor), outside))
    }
    if (focused.backgroundImage !== unfocused.backgroundImage) {
      const tints = gradientColors(focused.backgroundImage) ?? []
      const base = was(unfocused.backgroundColor)
      for (const tint of tints) take(worst(faded(tint, focused.opacity), base, outside))
    }
    if (focused.color !== unfocused.color) {
      take(worst(fade(focused.color), was(unfocused.color), inside))
    }
    if (focused.textDecorationLine !== unfocused.textDecorationLine) {
      take(worst(fade(focused.color), null, inside))
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
      if (part === undefined || !part.own) continue
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

  // --- what covers an element ---

  // Hit testing skips elements with `pointer-events: none`, which still paint: an overlay of
  // that kind still hides what is under it.
  const allHits = document.createElement('style')
  allHits.textContent = '*, *::before, *::after { pointer-events: auto !important }'
  function hitsAt(points: [number, number][]): Element[][] {
    document.head.append(allHits)
    try {
      return points.map(([x, y]) => document.elementsFromPoint(x, y))
    } finally {
      allHits.remove()
    }
  }

  /** Whether `element` paints anything that hides what lies under it. */
  function paints(element: Element): boolean {
    if (getComputedStyle(element).visibility !== 'visible') return false
    if (chainOf(element).opacity <= 0.1) return false
    if (isRaster(element) || element instanceof SVGSVGElement) return true
    const style = getComputedStyle(element)
    return rgba(style.backgroundColor)[3] > 0 || style.backgroundImage !== 'none'
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
    return !hitsAt(points).some((stack) => {
      for (const hit of stack) {
        if (hit === element || element.contains(hit) || hit.contains(element)) return true
        if (hit instanceof HTMLLabelElement && hit.control === element) return true
        if (paints(hit)) return false
      }
      return false
    })
  }

  // --- pictures ---

  const SHOT_MARGIN = 8

  function rectOf(element: Element): Rect {
    const box = element.getBoundingClientRect()
    return { x: box.left, y: box.top, width: box.width, height: box.height }
  }

  /** Whether the paint around `element` is a picture or a filter that computed colours miss. */
  function needsPixels(element: Element): boolean {
    if (chainOf(element).filtered) return true
    if (isRaster(element) || element.querySelector('img, canvas, video') !== null) return true
    if (backdrop(element).image) return true
    const box = element.getBoundingClientRect()
    const x = box.left + box.width / 2
    const y = box.top + box.height / 2
    const points: [number, number][] = [
      [x, box.top - 3],
      [x, box.bottom + 3],
      [box.left - 3, y],
      [box.right + 3, y],
    ]
    return points.some(([px, py]) => {
      const hit = document.elementsFromPoint(px, py).find((under) => !element.contains(under))
      return hit !== undefined && backdrop(hit).image
    })
  }

  function place(element: Element): ShotPlace | null {
    const box = rectOf(element)
    const left = Math.max(0, Math.floor(box.x - SHOT_MARGIN))
    const top = Math.max(0, Math.floor(box.y - SHOT_MARGIN))
    const right = Math.min(window.innerWidth, Math.ceil(box.x + box.width + SHOT_MARGIN))
    const bottom = Math.min(window.innerHeight, Math.ceil(box.y + box.height + SHOT_MARGIN))
    if (right - left < 1 || bottom - top < 1) return null
    const seen = visibleBox(element)
    return {
      clip: { x: left, y: top, width: right - left, height: bottom - top },
      box,
      seen: {
        x: seen.left,
        y: seen.top,
        width: seen.right - seen.left,
        height: seen.bottom - seen.top,
      },
    }
  }

  async function decode(png: string): Promise<ImageData> {
    const bytes = Uint8Array.from(atob(png), (char) => char.codePointAt(0) ?? 0)
    const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }))
    const board = document.createElement('canvas')
    board.width = bitmap.width
    board.height = bitmap.height
    const brush = board.getContext('2d', { willReadFrequently: true })
    if (brush === null) throw new Error('no 2d canvas')
    brush.drawImage(bitmap, 0, 0)
    return brush.getImageData(0, 0, bitmap.width, bitmap.height)
  }

  /**
   * Judges a stop by its pictures: the pixels around it that changed by 3:1 when it took the
   * focus must add up to a 1 px line round it. The stop that has the focus now is left out of
   * the comparison: its own indicator is not this one's.
   */
  async function comparePixels(
    key: number,
    focused: { png: string; place: ShotPlace },
    unfocused: { png: string; place: ShotPlace },
  ): Promise<ProbeFinding | null> {
    const element = shots.get(key)
    if (element === undefined) return null
    const [one, other] = await Promise.all([decode(focused.png), decode(unfocused.png)])
    const now = document.activeElement
    const skip = now !== null && now !== element && now !== document.body ? rectOf(now) : null
    const { box } = focused.place
    let strong = 0
    let changed = 0
    for (let dy = -SHOT_MARGIN; dy < box.height + SHOT_MARGIN; dy += 1) {
      for (let dx = -SHOT_MARGIN; dx < box.width + SHOT_MARGIN; dx += 1) {
        const fx = Math.round(box.x + dx - focused.place.clip.x)
        const fy = Math.round(box.y + dy - focused.place.clip.y)
        const pageX = unfocused.place.box.x + dx
        const pageY = unfocused.place.box.y + dy
        const ux = Math.round(pageX - unfocused.place.clip.x)
        const uy = Math.round(pageY - unfocused.place.clip.y)
        if (fx < 0 || fy < 0 || fx >= one.width || fy >= one.height) continue
        if (ux < 0 || uy < 0 || ux >= other.width || uy >= other.height) continue
        if (
          skip !== null &&
          pageX >= skip.x - SHOT_MARGIN &&
          pageX < skip.x + skip.width + SHOT_MARGIN &&
          pageY >= skip.y - SHOT_MARGIN &&
          pageY < skip.y + skip.height + SHOT_MARGIN
        ) {
          continue
        }
        const f = (fy * one.width + fx) * 4
        const u = (uy * other.width + ux) * 4
        const ratio = contrast(
          [one.data[f] ?? 0, one.data[f + 1] ?? 0, one.data[f + 2] ?? 0],
          [other.data[u] ?? 0, other.data[u + 1] ?? 0, other.data[u + 2] ?? 0],
        )
        if (ratio > 1.05) changed += 1
        if (ratio >= 3) strong += 1
      }
    }
    const { seen } = focused.place
    const need = Math.round(2 * (seen.width + seen.height))
    const target = describe(element)
    if (changed === 0) return { rule: 'no-indicator', target, detail: 'pixels' }
    if (strong < need) {
      return {
        rule: 'indicator-contrast',
        target,
        detail: `pixels: ${strong} px at 3:1, ${need} needed`,
      }
    }
    return null
  }

  // --- the focus walk ---

  // `fresh`: judged against its look once it has lost the focus, not the look from before the
  // walk; an option a list points at may have been the pointed one then too.
  type Item = {
    element: Element
    focused: Record<Theme, Snapshot>
    shot: number | null
    fresh: boolean
  }

  let darkClass = ''
  let limit = 0
  let region: string | null = null
  let first: Element | null = null
  // The stop that has the focus, and the option its active descendant names.
  let stop: Item | null = null
  let option: Item | null = null
  // The item an arrow key moved the focus to, until the focus comes back.
  let arrowed: Item | null = null
  let settling: { stuck: boolean } | null = null
  let outside = 0
  let stops = 0
  let pageFocused = true
  let visited = new Set<Element>()
  let startStops = new Set<Element>()
  let lastStop: Element | null = null
  let shots = new Map<number, Element>()
  // Each target unfocused, taken before the walk: some widgets (PrimeVue's Select) keep their
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

  let ownTheme: boolean | null = null
  function setTheme(theme: Theme | null): void {
    const root = document.documentElement
    if (theme === null) {
      if (ownTheme !== null) root.classList.toggle(darkClass, ownTheme)
      ownTheme = null
      return
    }
    ownTheme ??= root.classList.contains(darkClass)
    root.classList.toggle(darkClass, theme === 'dark')
  }

  /** Whether the stop looks as it did before the walk: its blur has nothing left to settle. */
  function looksPlain(key: number): boolean {
    const element = shots.get(key)
    const before = element === undefined ? undefined : baseline.get(element)
    if (element === undefined || before === undefined) return false
    const theme: Theme = document.documentElement.classList.contains(darkClass) ? 'dark' : 'light'
    chain = new Map()
    const now = snapshot(element)
    return Object.entries(before[theme]).every(
      ([name, paint]) => JSON.stringify(paint) === JSON.stringify(now[name]),
    )
  }

  function shotPlace(key: number): ShotPlace | null {
    const element = shots.get(key)
    if (element === undefined) return null
    // The next stop's focus may have scrolled it away; the unwatched scroll is no motion.
    scrollIntoView.call(element, { block: 'nearest', inline: 'nearest' })
    return place(element)
  }

  function looks(element: Element): Record<Theme, Snapshot> {
    return {
      light: inTheme('light', () => snapshot(element, true)),
      dark: inTheme('dark', () => snapshot(element, true)),
    }
  }

  function item(element: Element, pixels: boolean, fresh = false): Item {
    let shot: number | null = null
    if (pixels) {
      shot = shots.size
      shots.set(shot, element)
    }
    return { element, focused: looks(element), shot, fresh }
  }

  function walkStart(dark: string, most: number, within: string | null): void {
    chain = new Map()
    darkClass = dark
    limit = most
    region = within
    first = null
    stop = null
    option = null
    arrowed = null
    settling = null
    outside = 0
    stops = 0
    pageFocused = document.hasFocus()
    visited = new Set()
    startStops = new Set(tabStops())
    lastStop = null
    shots = new Map()
    const scope = within === null ? document : (document.querySelector(within) ?? document)
    const candidates = [...scope.querySelectorAll(`${TABBABLE}, ${ITEM}`)].filter(
      (element) => element !== document.activeElement,
    )
    const light = inTheme('light', () => candidates.map((element) => snapshot(element)))
    const darkLooks = inTheme('dark', () => candidates.map((element) => snapshot(element)))
    baseline = new Map(
      candidates.map((element, index) => [
        element,
        { light: light[index] as Snapshot, dark: darkLooks[index] as Snapshot },
      ]),
    )
  }

  /** Judges items that have lost the focus; the ones judged by pixels are returned instead. */
  function judgeAll(items: Item[], findings: ThemeFindings, pixels: number[]): void {
    for (const each of items) {
      if (each.shot !== null) {
        pixels.push(each.shot)
        continue
      }
      for (const theme of ['light', 'dark'] as const) {
        inTheme(theme, () => {
          const kept = each.fresh ? undefined : baseline.get(each.element)?.[theme]
          const before = kept ?? snapshot(each.element)
          const finding = judge(each.element, each.focused[theme], before)
          if (finding !== null) findings[theme].push(finding)
        })
      }
    }
  }

  function both(findings: ThemeFindings, finding: ProbeFinding): void {
    findings.light.push(finding)
    findings.dark.push(finding)
  }

  // PrimeVue's focus traps: a sentinel that takes the focus hands it on at once.
  const SENTINEL = '[data-p-hidden-focusable="true"]'

  function radioDone(element: Element): boolean {
    if (!(element instanceof HTMLInputElement) || element.type !== 'radio' || !element.name) {
      return false
    }
    const group = document.querySelectorAll(
      `input[type="radio"][name="${CSS.escape(element.name)}"]`,
    )
    return [...group].some((mate) => visited.has(mate) || (mate as HTMLInputElement).checked)
  }

  /** The Tab stops of the walk's region (or the page), sentinels left out. */
  function tabStops(): Element[] {
    const scope = region === null ? document.body : document.querySelector(region)
    if (scope === null) return []
    return [...scope.querySelectorAll(TABBABLE)].filter(
      (element) => !element.matches(SENTINEL) && tabbable(element),
    )
  }

  /**
   * At the end of a walk, the Tab stops it never reached (of those there from its start): after
   * the last stop, a trap when the focus stayed put and the region left early when it moved out;
   * each one on its own otherwise.
   */
  function coverage(findings: ThemeFindings, how: 'stuck' | 'left' | 'other'): void {
    const missed = tabStops().filter(
      (element) =>
        startStops.has(element) &&
        !visited.has(element) &&
        !(element.matches('input[type="radio"]') && radioDone(element)),
    )
    const after = (element: Element) =>
      lastStop !== null &&
      (lastStop.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0 &&
      !lastStop.contains(element)
    const later = missed.filter(after)
    const names = (list: Element[]) => [...new Set(list.map(describe))]
    const detail = `${later.length} not reached: ${names(later).slice(0, 3).join(', ')}`
    if (later.length > 0 && how === 'stuck') {
      both(findings, { rule: 'trap', target: describe(lastStop), detail })
    } else if (later.length > 0 && how === 'left') {
      both(findings, { rule: 'region-exit', target: describe(lastStop), detail })
    }
    const rest = how === 'other' ? missed : missed.filter((element) => !after(element))
    for (const name of names(rest)) both(findings, { rule: 'unreached', target: name })
  }

  function arrowKey(element: Element): string | null {
    const role = element.getAttribute('role') ?? ''
    if (role === 'tab') {
      const list = element.closest('[role="tablist"]')
      return list?.getAttribute('aria-orientation') === 'vertical' ? 'ArrowDown' : 'ArrowRight'
    }
    if (role === 'treeitem' || role === 'option') return 'ArrowDown'
    if (role.startsWith('menuitem')) {
      return element.closest('[role="menubar"]') === null ? 'ArrowDown' : 'ArrowRight'
    }
    if (activeOption(element) === null) return null
    if (['listbox', 'tree', 'grid', 'treegrid'].includes(role)) return 'ArrowDown'
    if (role === 'combobox' && element.getAttribute('aria-expanded') === 'true') return 'ArrowDown'
    return null
  }

  function walkStep(): WalkStep {
    chain = new Map()
    const findings: ThemeFindings = { light: [], dark: [] }
    const pixels: number[] = []
    let done = false
    let how: 'stuck' | 'left' | 'other' = 'other'
    if (stop !== null) {
      // Tab left the focus where it was, or took it out of the page (Firefox keeps the last
      // element as the active one then): the walk is over.
      const stuck =
        settling?.stuck ??
        (document.activeElement === stop.element || (pageFocused && !document.hasFocus()))
      if (!baseline.has(stop.element) && settling === null) {
        // Only a blur shows the element unfocused.
        if (stuck && stop.element instanceof HTMLElement) stop.element.blur()
        settling = { stuck }
        return { done: false, settle: true, stops, findings, pixels, shoot: null, arrow: null }
      }
      done = stuck
      // Its pictures need it unfocused, and the walk keeps the focus on it at the end.
      if (stuck && stop.shot !== null && stop.element instanceof HTMLElement) stop.element.blur()
      if (stuck) how = 'stuck'
      settling = null
      lastStop = stop.element
      judgeAll([stop], findings, pixels)
      stop = null
      option = null
    }
    let next: Element | null = null
    const active = document.activeElement
    if (done) {
      // The walk stays put.
    } else if (region !== null && !(document.querySelector(region)?.contains(active) ?? false)) {
      done = true
      how = 'left'
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
    let shoot: number | null = null
    let arrow: string | null = null
    if (next !== null) {
      visited.add(next)
      if (obscured(next)) both(findings, { rule: 'obscured', target: describe(next) })
      stop = item(next, needsPixels(next))
      shoot = stop.shot
      const pointed = activeOption(next)
      if (pointed !== null) option = item(pointed, false, true)
      arrow = arrowKey(next)
    }
    if (done && stops < limit) coverage(findings, how)
    return { done, settle: false, stops, findings, pixels, shoot, arrow }
  }

  // Found while an arrow key had moved the focus, handed over by `arrowBack`.
  let arrowFound: ThemeFindings = { light: [], dark: [] }

  function arrowSeen(): boolean {
    if (stop === null) return false
    const element = stop.element
    const active = document.activeElement
    let reached: Element | null = null
    if (active !== element) {
      const widget = element.closest(COMPOSITE)
      if (active !== null && widget?.contains(active)) reached = active
      else if (element instanceof HTMLElement) element.focus({ preventScroll: true })
    } else {
      const now = activeOption(element)
      if (now !== null && now !== option?.element) {
        reached = now
        // The option pointed at before is pointed at no more: its look now is its plain one.
        if (option !== null) judgeAll([option], arrowFound, [])
      }
    }
    if (reached === null) return false
    arrowed = item(reached, false, option !== null)
    return true
  }

  function arrowBack(): ThemeFindings {
    const findings = arrowFound
    arrowFound = { light: [], dark: [] }
    if (stop !== null && document.activeElement !== stop.element) {
      if (stop.element instanceof HTMLElement) stop.element.focus({ preventScroll: true })
    }
    if (arrowed !== null) judgeAll([arrowed], findings, [])
    arrowed = null
    return findings
  }

  // --- text contrast that axe leaves open ---

  function disabled(element: Element): boolean {
    return element.closest(':disabled, [aria-disabled="true"]') !== null
  }

  function measureText(selectors: string[]): { ratio: number; need: number; skip?: string }[] {
    chain = new Map()
    const modal = document.querySelector('.p-dialog-mask.p-overlay-mask, .p-overlay-mask')
    return selectors.map((selector) => {
      let element: Element | null = null
      try {
        element = document.querySelector(selector)
      } catch {
        // axe's selector is not one this browser reads.
      }
      if (element === null) return { ratio: 0, need: 0, skip: 'gone' }
      if (disabled(element)) return { ratio: 0, need: 0, skip: 'disabled' }
      if (modal !== null && !modal.contains(element)) {
        return { ratio: 0, need: 0, skip: 'behind a modal dialog' }
      }
      const style = getComputedStyle(element)
      const size = Number.parseFloat(style.fontSize)
      const bold = Number(style.fontWeight) >= 700
      const need = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5
      const behind = backdrop(element)
      if (behind.image) return { ratio: 0, need, skip: 'picture' }
      const colors = [...behind.colors]
      for (const pseudo of ['::before', '::after']) {
        const own = getComputedStyle(element, pseudo)
        if (own.content === 'none' || own.content === 'normal') continue
        const tint = rgba(own.backgroundColor)
        if (tint[3] > 0) colors.push(...behind.colors.map((under) => over(tint, under)))
      }
      const text = faded(rgba(style.color), chainOf(element).opacity)
      return { ratio: worst(text, null, colors), need }
    })
  }

  // --- regions ---

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
    arrowSeen,
    arrowBack,
    setTheme,
    looksPlain,
    shotPlace,
    comparePixels,
    measureText,
  }
  // The name is `PROBE_GLOBAL` of probeApi.ts; this function cannot import it at run time.
  Reflect.set(window, '__reframeA11y', api)
}
