import type { ScriptText } from './scriptText'

/**
 * Findings of `findScriptText` in the code base that are not fixed yet, one entry per finding
 * (the line is left out: it moves). The check fails on a finding that is not here and on an
 * entry that no longer happens, so the list only shrinks.
 */
export const ALLOWED_SCRIPT_TEXT: Omit<ScriptText, 'line'>[] = []
