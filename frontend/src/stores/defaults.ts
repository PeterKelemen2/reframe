import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watch } from 'vue'

import { api, ApiError, apiQuiet, unwrap } from '@/api/client'
import { text } from '@/api/text'
import type {
  AudioCodecRule,
  AudioDefaults,
  Fix,
  JobTemplate,
  MediaSource,
  Preset,
  Schemas,
  SubtitleDefaults,
  TrackDraft,
  ValidationIssue,
} from '@/api/types'
import {
  completeAudio,
  completeSubtitles,
  fixesOnly,
  keyedPath,
  keysAfter,
  newRule,
} from '@/components/defaults/model'
import { latestRequest } from '@/editor/latest'
import { applyOps, cloneJson, PatchError, sameJson } from '@/editor/patch'

import { useEditorStore } from './editor'
import { templateOfPreset, usePresetsStore } from './presets'
import { useSourcesStore } from './sources'
import { useToastStore } from './toasts'

export type DefaultsKind = 'audio' | 'subtitles'

/**
 * Whose defaults the dialog edits: the open job's (from its preset), a preset's, or a batch
 * group's. The group target is typed for the batch UI and not built yet.
 */
export type DefaultsTarget =
  | { kind: 'job' }
  | { kind: 'preset'; presetId: string }
  | { kind: 'group'; groupId: string }

export type Container = NonNullable<Schemas['DefaultsPreviewRequest']['container']>

/** Milliseconds from the last edit to `presets/defaults/preview`. */
export const PREVIEW_DEBOUNCE = 250

/** An issue of the shown preview, with its path keyed to a rule (`codec_rules[k3]`). */
export interface PlacedIssue {
  issue: ValidationIssue
  at: string
}

const TOAST_LIFE = 10_000

/** The audio and subtitle defaults dialog: what it edits, the edited copy, and its live preview. */
export const useDefaultsStore = defineStore('defaults', () => {
  const editor = useEditorStore()
  const presets = usePresetsStore()
  const sources = useSourcesStore()
  const toasts = useToastStore()

  const visible = ref(false)
  const kind = ref<DefaultsKind>('audio')
  const target = ref<DefaultsTarget | null>(null)
  /** The template the defaults come from, as it was when the dialog opened. */
  const template = shallowRef<JobTemplate | null>(null)
  /** The edited defaults; the kind the dialog does not edit stays the template's. */
  const audio = shallowRef<AudioDefaults | null>(null)
  const subtitles = shallowRef<SubtitleDefaults | null>(null)
  /** What `audio` and `subtitles` are compared with for `changed` (moves on after a save). */
  const saved = shallowRef<{ audio: AudioDefaults; subtitles: SubtitleDefaults } | null>(null)
  /** One stable key per codec rule, in rule order: rows and issues follow a moved rule. */
  const ruleKeys = shallowRef<number[]>([])
  const preview = shallowRef<TrackDraft | null>(null)
  /** The rule keys of the request whose answer `preview` is. */
  const previewKeys = shallowRef<number[]>([])
  /** A preview request waits for its delay or is under way: `preview` may be out of date. */
  const previewing = ref(false)
  const previewFailure = ref<string | null>(null)
  const busy = ref(false)

  let keyCount = 0
  const nextKey = () => ++keyCount

  const preset = computed<Preset | null>(() => {
    const whose = target.value
    if (whose?.kind === 'job') return editor.preset
    if (whose?.kind === 'preset') return presets.byId(whose.presetId) ?? null
    return null
  })
  /** A built-in preset's defaults are shown, never changed. */
  const readOnly = computed(
    () => target.value?.kind === 'preset' && preset.value?.built_in === true,
  )
  const container = computed<Container | null>(() => {
    const output =
      target.value?.kind === 'job' ? editor.job?.output : (template.value?.output ?? undefined)
    return (output?.container as Container | undefined) ?? null
  })
  /** The source the preview drafts: the job's, else the open one. */
  const sourceId = computed<string | null>(() => {
    const opened = editor.target
    if (opened?.kind === 'job') return opened.sourceId
    if (target.value?.kind === 'job') return null
    const active = sources.active
    return active !== null && active.source !== null ? active.id : null
  })
  const source = computed<MediaSource | null>(
    () => sources.entries.find((entry) => entry.id === sourceId.value)?.source ?? null,
  )
  const changed = computed(
    () =>
      saved.value !== null &&
      (!sameJson(saved.value.audio, audio.value) ||
        !sameJson(saved.value.subtitles, subtitles.value)),
  )
  const issues = computed<PlacedIssue[]>(() =>
    (preview.value?.issues ?? []).map((issue) => ({
      issue,
      at: keyedPath(issue.path ?? '', previewKeys.value),
    })),
  )

  function issuesAt(at: string): ValidationIssue[] {
    return issues.value.filter((placed) => placed.at === at).map((placed) => placed.issue)
  }

  const request = latestRequest<{ drafts: TrackDraft[]; keys: number[] }>({
    async send(signal) {
      const keys = ruleKeys.value
      const body = {
        source_ids: [sourceId.value as string],
        audio_defaults: audio.value as AudioDefaults,
        subtitle_defaults: subtitles.value as SubtitleDefaults,
        container: container.value,
      }
      const drafts = unwrap(await apiQuiet.POST('/api/presets/defaults/preview', { body, signal }))
      return { drafts, keys }
    },
    done({ drafts, keys }) {
      preview.value = drafts[0] ?? null
      previewKeys.value = keys
      previewFailure.value = null
      previewing.value = false
    },
    failed(error) {
      previewing.value = false
      if (!(error instanceof ApiError)) throw error
      preview.value = null
      previewFailure.value = error.problem.detail ?? error.problem.title
    },
  })

  /** Sends the preview after `delay` ms; an older request's answer is never shown. */
  function schedulePreview(delay: number): void {
    if (!visible.value || sourceId.value === null || audio.value === null) {
      request.cancel()
      previewing.value = false
      preview.value = null
      previewFailure.value = null
      return
    }
    previewing.value = true
    request.schedule(delay)
  }

  function start(which: DefaultsKind, whose: DefaultsTarget, from: JobTemplate): void {
    template.value = from
    audio.value = completeAudio(from.audio_defaults)
    subtitles.value = completeSubtitles(from.subtitle_defaults)
    saved.value = { audio: audio.value, subtitles: subtitles.value }
    ruleKeys.value = (audio.value.codec_rules ?? []).map(nextKey)
    preview.value = null
    previewKeys.value = []
    previewFailure.value = null
    kind.value = which
    target.value = whose
    visible.value = true
    schedulePreview(0)
  }

  function fail(summary: string, detail?: string): void {
    toasts.push({ severity: 'error', summary, detail, life: TOAST_LIFE })
  }

  /**
   * Opens the dialog on a copy of the target's defaults. A job's are its preset's (the job keeps
   * none of its own). A batch group is not built: a toast says so.
   */
  async function open(which: DefaultsKind, whose: DefaultsTarget): Promise<void> {
    if (whose.kind === 'group') {
      toasts.push({
        severity: 'info',
        summary: text('defaults.group.notBuilt'),
        detail: text('defaults.group.notBuiltDetail'),
        life: TOAST_LIFE,
      })
      return
    }
    await presets.ensureLoaded().catch(() => undefined)
    if (whose.kind === 'job') {
      const from = editor.currentTemplate
      if (from === null) {
        fail(text('defaults.open.noPreset'))
        return
      }
      start(which, whose, cloneJson(from))
      return
    }
    const found = presets.byId(whose.presetId)
    if (found === undefined) {
      fail(text('defaults.open.presetGone'))
      return
    }
    start(which, whose, templateOfPreset(cloneJson(found)))
  }

  /** Closes without applying or saving. */
  function close(): void {
    visible.value = false
    request.cancel()
    previewing.value = false
  }

  function edited(): void {
    schedulePreview(PREVIEW_DEBOUNCE)
  }

  /** Replaces the edited audio defaults (one edit; the preview follows after a pause). */
  function setAudio(next: AudioDefaults): void {
    if (readOnly.value) return
    audio.value = next
    edited()
  }

  function setSubtitles(next: SubtitleDefaults): void {
    if (readOnly.value) return
    subtitles.value = next
    edited()
  }

  function rules(): AudioCodecRule[] {
    return [...(audio.value?.codec_rules ?? [])]
  }

  function setRules(next: AudioCodecRule[], keys: number[]): void {
    if (readOnly.value || audio.value === null) return
    ruleKeys.value = keys
    setAudio({ ...audio.value, codec_rules: next })
  }

  /** A new rule just above the catch-all; returns its key. */
  function addRule(): number {
    const list = rules()
    const key = nextKey()
    const at = Math.max(list.length - 1, 0)
    const keys = [...ruleKeys.value]
    list.splice(at, 0, newRule(list.at(-1)))
    keys.splice(at, 0, key)
    setRules(list, keys)
    return key
  }

  function setRule(index: number, rule: AudioCodecRule): void {
    const list = rules()
    if (index < 0 || index >= list.length) return
    list[index] = rule
    setRules(list, ruleKeys.value)
  }

  /** The catch-all (the last rule) is never removed. */
  function removeRule(index: number): void {
    const list = rules()
    if (index < 0 || index >= list.length - 1) return
    const keys = [...ruleKeys.value]
    list.splice(index, 1)
    keys.splice(index, 1)
    setRules(list, keys)
  }

  /** Moves a rule among the rules above the catch-all, which stays last. */
  function moveRule(from: number, to: number): void {
    const list = rules()
    const last = list.length - 1
    if (from === to || from < 0 || to < 0 || from >= last || to >= last) return
    const keys = [...ruleKeys.value]
    const [rule] = list.splice(from, 1)
    const [key] = keys.splice(from, 1)
    if (rule === undefined || key === undefined) return
    list.splice(to, 0, rule)
    keys.splice(to, 0, key)
    setRules(list, keys)
  }

  const member = computed(() => (kind.value === 'audio' ? 'audio_defaults' : 'subtitle_defaults'))

  /** A fix that changes only the defaults the dialog edits. */
  function offersFix(fix: Fix): boolean {
    return !readOnly.value && fixesOnly(fix.patch, member.value)
  }

  /** Its paths are the shown answer's: only while no edit has come after it. */
  function applyFix(fix: Fix): void {
    if (!offersFix(fix) || previewing.value || audio.value === null || subtitles.value === null) {
      return
    }
    let next: { audio_defaults: AudioDefaults; subtitle_defaults: SubtitleDefaults }
    try {
      next = applyOps(
        { audio_defaults: audio.value, subtitle_defaults: subtitles.value },
        fix.patch,
      )
    } catch (error) {
      if (!(error instanceof PatchError)) throw error
      fail(text('defaults.fixFailed'))
      return
    }
    const count = next.audio_defaults.codec_rules?.length ?? 0
    const keys = keysAfter(ruleKeys.value, fix.patch, nextKey)
    ruleKeys.value = keys.length === count ? keys : Array.from({ length: count }, nextKey)
    audio.value = next.audio_defaults
    subtitles.value = next.subtitle_defaults
    edited()
  }

  /** The template with the edited defaults in it. */
  function editedTemplate(): JobTemplate {
    return {
      ...(template.value as JobTemplate),
      audio_defaults: audio.value as AudioDefaults,
      subtitle_defaults: subtitles.value as SubtitleDefaults,
    }
  }

  async function guarded(run: () => Promise<void>): Promise<void> {
    if (busy.value) return
    busy.value = true
    try {
      await run()
    } finally {
      busy.value = false
    }
  }

  /**
   * Replaces the job's tracks of the dialog's kind with what the edited defaults draft for its
   * source (`jobs/explain`): one undo step. A refusal is the API client's toast; the dialog stays.
   */
  async function apply(): Promise<void> {
    const opened = editor.target
    if (target.value?.kind !== 'job' || opened?.kind !== 'job') return
    const session = editor.session
    const list = kind.value
    await guarded(async () => {
      let draft: TrackDraft
      try {
        draft = unwrap(
          await api.POST('/api/jobs/explain', {
            body: { source_id: opened.sourceId, template: editedTemplate() },
          }),
        )
      } catch (error) {
        if (!(error instanceof ApiError)) throw error
        return
      }
      if (editor.session !== session || editor.job === null) return
      editor.set(`/${list}`, list === 'audio' ? draft.audio : draft.subtitles)
      close()
    })
  }

  /** Writes the edited defaults of the dialog's kind into a user preset. */
  async function saveInto(into: Preset): Promise<boolean> {
    const edits =
      kind.value === 'audio'
        ? { audio_defaults: audio.value }
        : { subtitle_defaults: subtitles.value }
    try {
      await presets.save({ ...into, ...edits } as Preset)
    } catch (error) {
      if (!(error instanceof ApiError)) throw error
      fail(
        text('defaults.save.failed', { name: into.name }),
        error.problem.detail ?? error.problem.title,
      )
      return false
    }
    if (audio.value !== null && subtitles.value !== null) {
      saved.value = { audio: audio.value, subtitles: subtitles.value }
    }
    editor.refreshPresetChanges()
    return true
  }

  /**
   * The preset target: saves the edited defaults into the preset and closes. The job target:
   * saves them into the job's preset (a user preset) and stays open, so they can be applied too.
   * A built-in preset is never changed.
   */
  async function save(): Promise<void> {
    const into = preset.value
    if (into === null || into.built_in || target.value?.kind === 'group') return
    const closes = target.value?.kind === 'preset'
    await guarded(async () => {
      if (!(await saveInto(into))) return
      if (closes) close()
      else {
        toasts.push({
          severity: 'success',
          summary: text('defaults.save.saved', { name: into.name }),
          life: 5000,
        })
      }
    })
  }

  /**
   * The job target with a built-in preset: a new user preset from the job's settings with the
   * edited defaults. Rejects with the `ApiError` (not toasted), so that a name clash can be shown.
   */
  async function saveAsNew(details: {
    name: string
    category: string
    description: string
  }): Promise<Preset> {
    const created = await presets.create({ template: editedTemplate(), ...details })
    if (audio.value !== null && subtitles.value !== null) {
      saved.value = { audio: audio.value, subtitles: subtitles.value }
    }
    toasts.push({
      severity: 'success',
      summary: text('defaults.save.created', { name: created.name }),
      life: 5000,
    })
    return created
  }

  // A measured bitrate or another opened source changes what the defaults draft.
  watch(source, () => {
    if (visible.value) schedulePreview(0)
  })

  // The job the dialog was opened for is gone (another source opened, the job closed).
  watch(
    () => editor.session,
    () => {
      if (visible.value && target.value?.kind === 'job') close()
    },
  )

  return {
    visible,
    kind,
    target,
    template,
    audio,
    subtitles,
    ruleKeys,
    preview,
    previewKeys,
    previewing,
    previewFailure,
    busy,
    preset,
    readOnly,
    container,
    sourceId,
    source,
    changed,
    issues,
    issuesAt,
    open,
    close,
    setAudio,
    setSubtitles,
    addRule,
    setRule,
    removeRule,
    moveRule,
    offersFix,
    applyFix,
    apply,
    save,
    saveAsNew,
  }
})
