<script setup lang="ts">
import { Download, RefreshCw } from '@lucide/vue'
import Button from 'primevue/button'
import ProgressBar from 'primevue/progressbar'
import { computed, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { ValidationIssue } from '@/api/types'
import Section from '@/components/base/Section.vue'
import { useSystemStore } from '@/stores/system'

import RefusalList from './RefusalList.vue'
import ToolRow from './ToolRow.vue'
import { FFMPEG_FAMILY, setByEnvironment, TOOL_NAMES, type ToolInfo } from './tools'
import { useBundledTools } from './useBundledTools'
import { useSettingsLocked } from './useSetting'

const { t } = useI18n()
const system = useSystemStore()
const locked = useSettingsLocked()
const { canDownload, fetching, fetchTask, use } = useBundledTools()

const tools = computed<ToolInfo[]>(() => {
  const set = system.info?.tools
  return set ? TOOL_NAMES.map((name) => set[name]) : []
})
const mode = computed(() => system.info?.mode ?? 'web')

const checking = ref(false)
/** The environment sets both: a bundled build would not be used. */
const bundledUseless = computed(() => {
  const set = system.info?.tools
  return set !== undefined && FFMPEG_FAMILY.every((name) => setByEnvironment(set[name]))
})
const bundledIssues = shallowRef<ValidationIssue[]>([])

async function checkAgain(): Promise<void> {
  checking.value = true
  try {
    await system.rescanTools()
  } catch (error) {
    // The API client has shown it as a toast.
    if (!(error instanceof ApiError)) throw error
  } finally {
    checking.value = false
  }
}

async function useBundled(): Promise<void> {
  bundledIssues.value = []
  bundledIssues.value = await use('ffmpeg')
}
</script>

<template>
  <Section :title="t('settings.tools.title')">
    <template #actions>
      <Button
        v-if="canDownload"
        :label="t('settings.tools.useBundled')"
        severity="secondary"
        outlined
        size="small"
        :loading="fetching"
        :disabled="bundledUseless || locked"
        data-action="fetch-bundled"
        @click="useBundled"
      >
        <template #icon>
          <Download :size="16" aria-hidden="true" />
        </template>
      </Button>
      <Button
        :label="t('settings.tools.checkAgain')"
        severity="secondary"
        outlined
        size="small"
        :loading="checking"
        :disabled="fetching"
        data-action="check-again"
        @click="checkAgain"
      >
        <template #icon>
          <RefreshCw :size="16" aria-hidden="true" />
        </template>
      </Button>
    </template>

    <p class="tools-section__intro">{{ t('settings.tools.intro') }}</p>
    <p v-if="bundledUseless" class="tools-section__note" data-field="bundled-note">
      {{ t('settings.tools.bundledUseless') }}
    </p>
    <RefusalList :issues="bundledIssues" />
    <div v-if="fetching" class="tools-section__progress" role="status">
      <span>{{ fetchTask?.message || t('settings.tools.downloading') }}</span>
      <ProgressBar
        :value="fetchTask?.progress ?? undefined"
        :mode="typeof fetchTask?.progress === 'number' ? 'determinate' : 'indeterminate'"
        :pt="{ root: { 'aria-label': t('settings.tools.downloading') } }"
      />
    </div>

    <div class="tools-section__rows">
      <ToolRow v-for="tool in tools" :key="tool.name" :tool="tool" :mode="mode" :locked="locked" />
    </div>
  </Section>
</template>

<style scoped>
.tools-section__intro,
.tools-section__note {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.tools-section__progress {
  display: grid;
  gap: var(--rf-space-1);
}

.tools-section__rows {
  display: grid;
}
</style>
