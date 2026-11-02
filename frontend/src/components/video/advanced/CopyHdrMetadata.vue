<script setup lang="ts">
import Button from 'primevue/button'
import { computed, ref, watch } from 'vue'
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

const busy = ref(false)
const note = ref<{ text: string; failed: boolean } | null>(null)
const encoderId = computed(() => editor.job?.video?.encoder ?? '')
const passthrough = computed(() => editor.job?.video?.passthrough === true)

watch([() => editor.session, encoderId], () => {
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

async function copy(): Promise<void> {
  const session = editor.session
  busy.value = true
  note.value = null
  try {
    const body = { job: editor.job as JobSettings }
    const ops = unwrap(await apiQuiet.POST('/api/jobs/hdr-metadata', { body }))
    if (session !== editor.session) return
    if (ops.length === 0) {
      note.value = { text: nothingCopied(), failed: false }
      return
    }
    editor.patch(ops)
    const options = ops.map((op) => tokensOf(op.path).at(-1)).join(', ')
    note.value = { text: t('params.hdr.copied', { options }), failed: false }
  } catch (error) {
    if (session !== editor.session) return
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
      :disabled="passthrough"
      data-action="copy-hdr"
      @click="copy"
    />
    <p
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
