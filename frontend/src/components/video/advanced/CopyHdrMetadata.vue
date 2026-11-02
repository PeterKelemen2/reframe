<script setup lang="ts">
import Button from 'primevue/button'
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { apiQuiet, unwrap } from '@/api/client'
import type { JobSettings } from '@/api/types'
import { useJobSource } from '@/components/summary/useJobSource'
import { tokensOf } from '@/editor/pointer'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'

const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()
const { source } = useJobSource()

const noteId = useId()
const busy = ref(false)
const note = ref<{ text: string; failed: boolean } | null>(null)
const encoderId = computed(() => editor.job?.video?.encoder ?? '')
const passthrough = computed(() => editor.job?.video?.passthrough === true)
// The template takes no file's values: each file's encode writes its own source's metadata.
const inGroup = computed(() => editor.target?.kind === 'group')

/** What the answer was asked for: another job, encoder or shown file makes it void. */
const asked = computed(() =>
  JSON.stringify([editor.session, encoderId.value, editor.target?.sourceId ?? null]),
)

watch(asked, () => {
  note.value = null
})

/** Why the server's patch was empty. */
function nothingCopied(): string {
  const hdr = source.value?.video?.[0]?.hdr
  if (!hdr?.mastering_display && !hdr?.content_light) return t('params.hdr.noMetadata')
  const encoder = system.definitions?.video_encoders?.[encoderId.value]
  const label = encoder?.label ?? encoderId.value
  return encoder?.family === 'software'
    ? t('params.hdr.cannotCarry', { encoder: label })
    : t('params.hdr.fromFrames', { encoder: label })
}

function labelOf(path: string): string {
  const key = tokensOf(path).at(-1) as string
  const options = system.definitions?.video_encoders?.[encoderId.value]?.options ?? []
  return options.find((option) => option.key === key)?.label ?? key
}

async function copy(): Promise<void> {
  const before = asked.value
  busy.value = true
  note.value = null
  try {
    const body = { job: editor.job as JobSettings }
    const ops = unwrap(await apiQuiet.POST('/api/jobs/hdr-metadata', { body }))
    if (asked.value !== before) return
    if (ops.length === 0) {
      note.value = { text: nothingCopied(), failed: false }
      return
    }
    editor.patch(ops)
    // A mastering display and a content light level at most.
    const [first, second] = ops.map((op) => labelOf(op.path))
    note.value = { text: t('params.hdr.copied', { first, second }, ops.length), failed: false }
  } catch (error) {
    if (asked.value !== before) return
    note.value = {
      text: t('params.hdr.failed', { reason: (error as Error).message }),
      failed: true,
    }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="copy-hdr-metadata">
    <Button
      :label="t('params.hdr.copy')"
      severity="secondary"
      outlined
      size="small"
      :loading="busy"
      :disabled="passthrough || inGroup"
      :aria-describedby="inGroup ? noteId : undefined"
      data-action="copy-hdr"
      @click="copy"
    />
    <p v-if="inGroup" :id="noteId" class="copy-hdr-metadata__note">{{ t('params.hdr.group') }}</p>
    <p
      v-else
      class="copy-hdr-metadata__note"
      :class="{ 'copy-hdr-metadata__note--failed': note?.failed }"
      role="status"
      :data-note="note === null ? undefined : note.failed ? 'failed' : 'done'"
    >
      {{ note?.text }}
    </p>
  </div>
</template>

<style scoped>
.copy-hdr-metadata {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2) var(--rf-space-3);
}

.copy-hdr-metadata__note {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.copy-hdr-metadata__note--failed {
  color: var(--p-status-error-color);
}
</style>
