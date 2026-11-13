import type { ScriptText } from './scriptText'

/**
 * Findings of `findScriptText` in the code base that are not fixed yet, one entry per finding
 * (the line is left out: it moves). The check fails on a finding that is not here and on an
 * entry that no longer happens, so the list only shrinks.
 */
export const ALLOWED_SCRIPT_TEXT: Omit<ScriptText, 'line'>[] = [
  // Shell and pages.
  { file: '/src/components/settings/PreviewSection.vue', where: 'InputNumber', text: 'no :locale' },
  { file: '/src/components/settings/PreviewSection.vue', where: 'InputNumber', text: 'no :locale' },
  { file: '/src/components/settings/QueueSection.vue', where: 'InputNumber', text: 'no :locale' },
  { file: '/src/views/SandboxView.vue', where: 'InputNumber', text: 'no :locale' },
  { file: '/src/views/SandboxView.vue', where: 'InputNumber', text: 'no :locale' },
]
