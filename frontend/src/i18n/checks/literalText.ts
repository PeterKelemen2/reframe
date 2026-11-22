import {
  type AttributeNode,
  type DirectiveNode,
  type ElementNode,
  type ExpressionNode,
  NodeTypes,
  type RootNode,
  type TemplateChildNode,
} from '@vue/compiler-dom'
import { parse } from '@vue/compiler-sfc'

/** Text in a `<template>` that a user would see untranslated. */
export interface LiteralText {
  file: string
  line: number
  /** `text`, `{{ }}`, or the attribute or directive it is in (`title`, `:label`, `v-tooltip`). */
  where: string
  text: string
}

const LETTER = /\p{L}/u

/**
 * Attributes whose value a user reads, or hears from a screen reader, on any element or
 * component (camelCase: `aria-label` is `ariaLabel`).
 */
export const VISIBLE_ATTRIBUTES = new Set([
  'title',
  'alt',
  'placeholder',
  'ariaLabel',
  'ariaDescription',
  'ariaRoledescription',
  'ariaPlaceholder',
  'ariaValuetext',
  // PrimeVue props that render text.
  'label',
  'header',
  'footer',
  'subheader',
  'legend',
  'message',
  'summary',
  'detail',
  'tooltip',
  'badge',
  'onLabel',
  'offLabel',
  'acceptLabel',
  'rejectLabel',
  'chooseLabel',
  'uploadLabel',
  'cancelLabel',
  'emptyMessage',
  'emptyFilterMessage',
  'emptySelectionMessage',
  'selectionMessage',
  'filterPlaceholder',
  'currentPageReportTemplate',
])

/** Components whose `value` is the text they show. */
const VALUE_IS_TEXT = new Set(['Tag', 'Badge', 'Chip', 'OverlayBadge'])

/** Directives whose expression is shown as text. */
const TEXT_DIRECTIVES = new Set(['tooltip', 'text', 'html'])

/** A call whose first argument is a message key, not text. */
const KEY_CALL_BEFORE = /(?:^|[^\w$])(?:\$t|t|te|tc|tm|rt)\(\s*$/
const COMPARISON_BEFORE = /[!=]==?\s*$/
const COMPARISON_AFTER = /^\s*[!=]==?/

function camelize(name: string): string {
  return name.replace(/-(\w)/g, (_, letter: string) => letter.toUpperCase())
}

function pascalize(name: string): string {
  const camel = camelize(name)
  return camel.charAt(0).toUpperCase() + camel.slice(1)
}

function isVisibleAttribute(element: ElementNode, name: string): boolean {
  const attribute = camelize(name)
  return (
    VISIBLE_ATTRIBUTES.has(attribute) ||
    (attribute === 'value' && VALUE_IS_TEXT.has(pascalize(element.tag)))
  )
}

/** Skips a `${ … }` of a template literal; returns the index after its `}`. */
function skipSubstitution(source: string, start: number): number {
  let depth = 1
  let index = start
  while (index < source.length && depth > 0) {
    const char = source[index]
    if (char === '{') depth += 1
    else if (char === '}') depth -= 1
    else if (char === "'" || char === '"' || char === '`') index = readString(source, index).end - 1
    index += 1
  }
  return index
}

/** The string literal that starts at `start`: its static text and the index after it. */
function readString(source: string, start: number): { text: string; end: number } {
  const quote = source[start]
  let text = ''
  let index = start + 1
  while (index < source.length) {
    const char = source[index]
    if (char === '\\') {
      text += source[index + 1] ?? ''
      index += 2
    } else if (char === quote) {
      return { text, end: index + 1 }
    } else if (quote === '`' && char === '$' && source[index + 1] === '{') {
      index = skipSubstitution(source, index + 2)
    } else {
      text += char
      index += 1
    }
  }
  return { text, end: index }
}

/**
 * String literals with a letter in a JavaScript expression that is shown, except a message
 * key (the first argument of `t(…)`) and an operand of a comparison (`kind === 'audio'`).
 */
function shownStrings(expression: string): string[] {
  const found: string[] = []
  let index = 0
  while (index < expression.length) {
    const char = expression[index]
    if (char !== "'" && char !== '"' && char !== '`') {
      index += 1
      continue
    }
    const { text, end } = readString(expression, index)
    const before = expression.slice(0, index)
    const after = expression.slice(end)
    const isKey = KEY_CALL_BEFORE.test(before)
    const isCompared = COMPARISON_BEFORE.test(before) || COMPARISON_AFTER.test(after)
    if (!isKey && !isCompared && LETTER.test(text)) found.push(text)
    index = end
  }
  return found
}

function expressionText(node: ExpressionNode | undefined): string {
  if (!node) return ''
  return node.type === NodeTypes.SIMPLE_EXPRESSION ? node.content : node.loc.source
}

function checkAttribute(
  element: ElementNode,
  prop: AttributeNode | DirectiveNode,
  report: (line: number, where: string, text: string) => void,
): void {
  if (prop.type === NodeTypes.ATTRIBUTE) {
    const value = prop.value?.content ?? ''
    if (isVisibleAttribute(element, prop.name) && LETTER.test(value)) {
      report(prop.loc.start.line, prop.name, value)
    }
    return
  }
  const argument =
    prop.arg?.type === NodeTypes.SIMPLE_EXPRESSION && prop.arg.isStatic ? prop.arg.content : null
  const shown =
    (prop.name === 'bind' && argument !== null && isVisibleAttribute(element, argument)) ||
    TEXT_DIRECTIVES.has(prop.name)
  if (!shown) return
  const where = prop.name === 'bind' ? `:${argument}` : `v-${prop.name}`
  for (const text of shownStrings(expressionText(prop.exp))) {
    report(prop.loc.start.line, where, text)
  }
}

function walk(
  nodes: readonly TemplateChildNode[],
  report: (line: number, where: string, text: string) => void,
): void {
  for (const node of nodes) {
    switch (node.type) {
      case NodeTypes.TEXT:
        if (LETTER.test(node.content)) report(node.loc.start.line, 'text', node.content.trim())
        break
      case NodeTypes.INTERPOLATION:
        for (const text of shownStrings(expressionText(node.content))) {
          report(node.loc.start.line, '{{ }}', text)
        }
        break
      case NodeTypes.ELEMENT:
        for (const prop of node.props) checkAttribute(node, prop, report)
        walk(node.children, report)
        break
      default:
        break
    }
  }
}

/**
 * Literal user-visible text in the `<template>` of a single-file component: text with a letter
 * outside `{{ }}`, a letter in a static visible attribute, and a string literal with a letter
 * in `{{ }}`, a bound visible attribute or `v-tooltip`. Symbols and numbers pass.
 */
export function findLiteralText(source: string, file: string): LiteralText[] {
  const { descriptor, errors } = parse(source, { filename: file })
  if (errors.length > 0) {
    return [{ file, line: 0, where: 'parse', text: String(errors[0]) }]
  }
  const ast: RootNode | undefined = descriptor.template?.ast ?? undefined
  if (!ast) return []
  const found: LiteralText[] = []
  walk(ast.children, (line, where, text) => found.push({ file, line, where, text }))
  return found
}
