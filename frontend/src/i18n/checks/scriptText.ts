import { NodeTypes, type TemplateChildNode } from '@vue/compiler-dom'
import { parse } from '@vue/compiler-sfc'
import ts from 'typescript'

import { VISIBLE_ATTRIBUTES } from './literalText'

/** Text a script builds for a user to read or hear without vue-i18n. */
export interface ScriptText {
  file: string
  line: number
  /**
   * The key, attribute or call it is in (`summary:`, `setAttribute(aria-label)`), `joined`
   * (translated pieces joined in a fixed order) or `number` (a number written with `toFixed`).
   */
  where: string
  text: string
}

const LETTER = /\p{L}/u
/** A value written like a name in code (`title`, `audio_codec`, `on-demand`), not like text. */
const IDENTIFIER = /^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*$/

/** Object keys whose string a user reads: toasts, menu items, PrimeVue options, notifications. */
const VISIBLE_KEYS = new Set([
  ...VISIBLE_ATTRIBUTES,
  'aria-label',
  'aria-description',
  'aria-roledescription',
  'aria-placeholder',
  'aria-valuetext',
  'body',
])

/** Attributes whose value a user reads or hears, as `setAttribute` names them. */
const VISIBLE_DOM_ATTRIBUTES = new Set([
  'title',
  'alt',
  'placeholder',
  'aria-label',
  'aria-description',
  'aria-roledescription',
  'aria-placeholder',
  'aria-valuetext',
])

/** DOM properties whose value a user reads or hears. */
const VISIBLE_PROPERTIES = new Set([
  'title',
  'alt',
  'placeholder',
  'ariaLabel',
  'ariaDescription',
  'ariaRoleDescription',
  'ariaPlaceholder',
  'ariaValueText',
  'textContent',
  'innerText',
  'innerHTML',
])

/** Calls whose first argument the browser shows. */
const DIALOG_CALLS = new Set(['alert', 'confirm', 'prompt'])

/** vue-i18n's translating calls. */
const TRANSLATE = new Set(['t', '$t', 'tc', '$tc'])

function lineOf(source: ts.SourceFile, node: ts.Node): number {
  return source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1
}

function nameOf(node: ts.PropertyName | ts.Expression): string | null {
  if (ts.isIdentifier(node) || ts.isPrivateIdentifier(node)) return node.text
  if (ts.isStringLiteralLike(node) || ts.isNumericLiteral(node)) return node.text
  return null
}

function isTranslation(node: ts.Node): boolean {
  if (!ts.isCallExpression(node)) return false
  const callee = node.expression
  const name = ts.isIdentifier(callee)
    ? callee.text
    : ts.isPropertyAccessExpression(callee)
      ? callee.name.text
      : null
  return name !== null && TRANSLATE.has(name)
}

/**
 * The literal text a value shows: string literals with a letter, through `a ? 'x' : 'y'`,
 * `a ?? 'x'`, `'x' + y` and the static parts of a template literal. A call (`t('…')`) is not
 * looked into.
 */
function literals(node: ts.Expression): string[] {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
    return LETTER.test(node.text) && !IDENTIFIER.test(node.text) ? [node.text] : []
  }
  if (ts.isTemplateExpression(node)) {
    const parts = [node.head.text, ...node.templateSpans.map((span) => span.literal.text)]
    return parts.some((part) => LETTER.test(part)) ? [parts.join('…')] : []
  }
  if (
    ts.isParenthesizedExpression(node) ||
    ts.isAsExpression(node) ||
    ts.isSatisfiesExpression(node)
  ) {
    return literals(node.expression)
  }
  if (ts.isConditionalExpression(node)) {
    return [...literals(node.whenTrue), ...literals(node.whenFalse)]
  }
  if (ts.isBinaryExpression(node)) {
    const operator = node.operatorToken.kind
    if (
      operator === ts.SyntaxKind.PlusToken ||
      operator === ts.SyntaxKind.QuestionQuestionToken ||
      operator === ts.SyntaxKind.BarBarToken
    ) {
      return [...literals(node.left), ...literals(node.right)]
    }
  }
  return []
}

/**
 * The calls in `node` that write a number without the app's locale: `toFixed` and `toPrecision`
 * always write a period, `toLocaleString()` takes the browser's locale.
 */
function fixedNumbers(node: ts.Node): ts.CallExpression[] {
  const found: ts.CallExpression[] = []
  const visit = (child: ts.Node): void => {
    if (ts.isCallExpression(child) && ts.isPropertyAccessExpression(child.expression)) {
      const method = child.expression.name.text
      if (
        method === 'toFixed' ||
        method === 'toPrecision' ||
        (method === 'toLocaleString' && child.arguments.length === 0)
      ) {
        found.push(child)
      }
    }
    ts.forEachChild(child, visit)
  }
  visit(node)
  return found
}

/**
 * The places where a number becomes text a user reads: the values of a translation's
 * placeholders (`t('…', { value })`), the substitutions of a template literal with words, and
 * a template's `{{ … }}`.
 */
function shownNumbers(node: ts.Node, interpolation: boolean): ts.CallExpression[] {
  if (interpolation) return ts.isSourceFile(node) ? fixedNumbers(node) : []
  if (isTranslation(node)) {
    const values = (node as ts.CallExpression).arguments[1]
    return values !== undefined && ts.isObjectLiteralExpression(values) ? fixedNumbers(values) : []
  }
  if (ts.isTemplateExpression(node)) {
    const text = [node.head.text, ...node.templateSpans.map((span) => span.literal.text)]
    if (text.some((part) => LETTER.test(part))) {
      return node.templateSpans.flatMap((span) => fixedNumbers(span.expression))
    }
  }
  return []
}

/**
 * Punctuation that sets two values apart in a fixed order (`a: b`, `a – b`), which a message
 * should hold. ` · ` between facts and `×` in a size are kept as data separators.
 */
function joinsByPunctuation(between: string): boolean {
  const text = between.trim()
  return text !== '' && !/[\p{L}\p{N}]/u.test(text) && text !== '·' && text !== '×'
}

/** The translated pieces of `node` and whether it joins them with text in a fixed order. */
function translatedPieces(node: ts.Expression): number {
  if (isTranslation(node)) return 1
  if (ts.isParenthesizedExpression(node)) return translatedPieces(node.expression)
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
    return translatedPieces(node.left) + translatedPieces(node.right)
  }
  if (ts.isTemplateExpression(node)) {
    return node.templateSpans.reduce((sum, span) => sum + translatedPieces(span.expression), 0)
  }
  return 0
}

/**
 * Text joined from translated pieces: `t('a') + t('b')`, `` `${t('a')}: …` ``, or
 * `[t('a'), t('b')].join(…)`. One message with placeholders orders its parts per language.
 */
function joined(node: ts.Node): boolean {
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
    const parent = node.parent
    // The outermost `+` of a chain reports it once.
    if (ts.isBinaryExpression(parent) && parent.operatorToken.kind === ts.SyntaxKind.PlusToken) {
      return false
    }
    const pieces = translatedPieces(node)
    return pieces >= 2 || (pieces === 1 && literals(node).length > 0)
  }
  if (ts.isTemplateExpression(node)) {
    const pieces = translatedPieces(node)
    const text = [node.head.text, ...node.templateSpans.map((span) => span.literal.text)]
    return pieces >= 2 || (pieces === 1 && text.some((part) => LETTER.test(part)))
  }
  if (
    ts.isCallExpression(node) &&
    ts.isPropertyAccessExpression(node.expression) &&
    node.expression.name.text === 'join' &&
    ts.isArrayLiteralExpression(node.expression.expression)
  ) {
    return node.expression.expression.elements.filter(isTranslation).length >= 2
  }
  return false
}

function walk(
  source: ts.SourceFile,
  interpolation: boolean,
  report: (node: ts.Node, where: string, text: string) => void,
): void {
  const visit = (node: ts.Node): void => {
    for (const call of shownNumbers(node, interpolation)) {
      report(call, 'number', call.getText(source))
    }
    if (ts.isPropertyAssignment(node)) {
      const key = nameOf(node.name)
      if (key !== null && VISIBLE_KEYS.has(key)) {
        for (const text of literals(node.initializer)) report(node, `${key}:`, text)
      }
    } else if (ts.isCallExpression(node)) {
      const callee = node.expression
      const [first, second] = node.arguments
      if (
        ts.isPropertyAccessExpression(callee) &&
        callee.name.text === 'setAttribute' &&
        first !== undefined &&
        second !== undefined
      ) {
        const attribute = nameOf(first)
        if (attribute !== null && VISIBLE_DOM_ATTRIBUTES.has(attribute)) {
          for (const text of literals(second)) report(node, `setAttribute(${attribute})`, text)
        }
      }
      const name = ts.isIdentifier(callee)
        ? callee.text
        : ts.isPropertyAccessExpression(callee) &&
            ts.isIdentifier(callee.expression) &&
            callee.expression.text === 'window'
          ? callee.name.text
          : null
      if (name !== null && DIALOG_CALLS.has(name) && first !== undefined) {
        for (const text of literals(first)) report(node, `${name}()`, text)
      }
    } else if (
      ts.isBinaryExpression(node) &&
      node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      ts.isPropertyAccessExpression(node.left) &&
      VISIBLE_PROPERTIES.has(node.left.name.text)
    ) {
      for (const text of literals(node.right)) report(node, `.${node.left.name.text} =`, text)
    }
    if (joined(node)) report(node, 'joined', node.getText(source).replaceAll(/\s+/g, ' '))
    ts.forEachChild(node, visit)
  }
  visit(source)
}

interface Code {
  code: string
  /** A template's `{{ … }}`: the whole expression is shown. */
  interpolation: boolean
  /** The line of the file where `code` starts. */
  firstLine: number
}

/** The expressions bound in a template (`:pt="{ … }"`, `v-bind="…"`, `{{ … }}`). */
function templateExpressions(nodes: readonly TemplateChildNode[], found: Code[]): void {
  for (const node of nodes) {
    if (node.type === NodeTypes.INTERPOLATION) {
      found.push({
        code: `(${node.content.loc.source})`,
        interpolation: true,
        firstLine: node.loc.start.line,
      })
    } else if (node.type === NodeTypes.ELEMENT) {
      for (const prop of node.props) {
        if (prop.type === NodeTypes.DIRECTIVE && prop.name === 'bind' && prop.exp) {
          found.push({
            code: `(${prop.exp.loc.source})`,
            interpolation: false,
            firstLine: prop.exp.loc.start.line,
          })
        }
      }
      templateExpressions(node.children, found)
    }
  }
}

/**
 * The code of a file: the whole of a `.ts` file; the `<script>` blocks and the bound template
 * expressions of a `.vue` one.
 */
function codeOf(source: string, file: string): Code[] {
  if (!file.endsWith('.vue')) return [{ code: source, interpolation: false, firstLine: 1 }]
  const { descriptor } = parse(source, { filename: file })
  const found = [descriptor.script, descriptor.scriptSetup]
    .filter((block) => block !== null)
    .map((block) => ({
      code: block.content,
      interpolation: false,
      firstLine: block.loc.start.line,
    }))
  const ast = descriptor.template?.ast
  if (ast) templateExpressions(ast.children, found)
  return found
}

/**
 * Values shown side by side in a template in a fixed order: `{{ a }}: {{ b }}`, or a translation
 * next to a value that is not one (`{{ t('x.rule') }} {{ n }}`). Two translations side by side
 * are taken as whole sentences.
 */
function templateJoins(nodes: readonly TemplateChildNode[], found: ScriptText[], file: string) {
  for (const node of nodes) {
    if (node.type !== NodeTypes.ELEMENT) continue
    const children = node.children
    for (const [index, between] of children.entries()) {
      const before = children[index - 1]
      const after = children[index + 1]
      if (between.type !== NodeTypes.TEXT || before === undefined || after === undefined) continue
      if (before.type !== NodeTypes.INTERPOLATION || after.type !== NodeTypes.INTERPOLATION)
        continue
      const translated = [before, after].filter((side) =>
        /(^|[^\w$.])\$?t\(/.test(side.content.loc.source),
      ).length
      if (
        joinsByPunctuation(between.content) ||
        (between.content.trim() === '' && translated === 1)
      ) {
        const text = `${before.loc.source}${between.content}${after.loc.source}`
        found.push({ file, line: before.loc.start.line, where: 'joined', text })
      }
    }
    templateJoins(children, found, file)
  }
}

/**
 * The lines of PrimeVue `InputNumber`s without a `locale`: they write numbers the browser's way,
 * not the app's (`:locale="locale"` from `useI18n()`).
 */
function numberInputsWithoutLocale(nodes: readonly TemplateChildNode[], found: number[]): void {
  for (const node of nodes) {
    if (node.type !== NodeTypes.ELEMENT) continue
    const isNumber = node.tag === 'InputNumber' || node.tag === 'input-number'
    const hasLocale = node.props.some((prop) =>
      prop.type === NodeTypes.ATTRIBUTE
        ? prop.name === 'locale'
        : prop.name === 'bind' &&
          prop.arg?.type === NodeTypes.SIMPLE_EXPRESSION &&
          prop.arg.content === 'locale',
    )
    if (isNumber && !hasLocale) found.push(node.loc.start.line)
    numberInputsWithoutLocale(node.children, found)
  }
}

/**
 * Text in the code of `file` (a `.ts` file, or a single-file component's scripts and bound
 * template expressions) that a user would read or hear untranslated: a string literal with a
 * letter as the value of a visible key (`summary: 'Saved'`, `:pt="{ root: { 'aria-label': … } }"`),
 * of a visible attribute set in code, in `alert()`; text joined from translated pieces, and
 * values a template joins in a fixed order; a number written without the app's locale where it
 * becomes text (`n()` or `Intl` with `locale` follow it); and an `InputNumber` without it.
 */
export function findScriptText(source: string, file: string): ScriptText[] {
  const found: ScriptText[] = []
  for (const { code, interpolation, firstLine } of codeOf(source, file)) {
    const parsed = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
    walk(parsed, interpolation, (node, where, text) => {
      found.push({ file, line: firstLine + lineOf(parsed, node) - 1, where, text })
    })
  }
  if (file.endsWith('.vue')) {
    const ast = parse(source, { filename: file }).descriptor.template?.ast
    const lines: number[] = []
    if (ast) numberInputsWithoutLocale(ast.children, lines)
    for (const line of lines) found.push({ file, line, where: 'InputNumber', text: 'no :locale' })
    if (ast) templateJoins(ast.children, found, file)
  }
  return found
}
