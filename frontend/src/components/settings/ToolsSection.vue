<script setup lang="ts">
import { Download, RefreshCw, TriangleAlert } from '@lucide/vue'
import Button from 'primevue/button'
import ProgressBar from 'primevue/progressbar'
import { computed, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { EncoderStatus, ValidationIssue } from '@/api/types'
import Section from '@/components/base/Section.vue'
import { useSystemStore } from '@/stores/system'

import RefusalList from './RefusalList.vue'
import ToolBuildPicker from './ToolBuildPicker.vue'
import ToolRow from './ToolRow.vue'
import { setByEnvironment, TOOL_NAMES, type ToolInfo } from './tools'
import { useBundledTools } from './useBundledTools'
import { useSettingsLocked } from './useSetting'

const { t } = useI18n()
const system = useSystemStore()
const locked = useSettingsLocked()
const { fetching, fetchTask, install } = useBundledTools()

const tools = computed<ToolInfo[]>(() => {
  const set = system.info?.tools
  return set ? TOOL_NAMES.map((name) => set[name]) : []
})
const mode = computed(() => system.info?.mode ?? 'web')

const checking = ref(false)
/** The environment sets both: a bundled build would not be used. */
const bundledUseless = computed(() => {
  const set = system.info?.tools
  return set !== undefined && TOOL_NAMES.every((name) => setByEnvironment(set[name]))
})
const bundledIssues = shallowRef<ValidationIssue[]>([])

const installed = computed(() => system.builds?.installed ?? null)
const installedLabel = computed(() => {
  const name = installed.value?.name
  return system.builds?.builds?.find((offer) => offer.name === name)?.label ?? name ?? ''
})
/** Encoders that another FFmpeg build or a driver update can make available. */
const mismatched = computed<EncoderStatus[]>(() =>
  Object.values(system.capabilities?.encoders ?? {}).filter(
    (status) => status.build_mismatch && status.state === 'unavailable',
  ),
)

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

async function downloadPinned(name: string): Promise<void> {
  bundledIssues.value = []
  bundledIssues.value = (await install({ build: name })).issues
}
</script>

<template>
  <Section :title="t('settings.tools.title')">
    <template #actions>
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
    <section
      v-if="mismatched.length > 0"
      class="tools-section__mismatch"
      :aria-label="t('settings.tools.mismatchTitle')"
      data-field="mismatch-notice"
    >
      <TriangleAlert class="tools-section__mismatch-icon" :size="18" aria-hidden="true" />
      <div class="tools-section__mismatch-body">
        <p class="tools-section__mismatch-title">{{ t('settings.tools.mismatchTitle') }}</p>
        <ul class="tools-section__mismatch-list">
          <li v-for="status in mismatched" :key="status.id" :data-encoder="status.id">
            <code>{{ status.id }}</code
            >: {{ status.reason }}
          </li>
        </ul>
        <p class="tools-section__mismatch-help">{{ t('settings.tools.mismatchHelp') }}</p>
      </div>
    </section>
    <div v-if="installed" class="tools-section__installed" data-field="installed-build">
      <p class="tools-section__installed-line">
        {{
          t('settings.tools.installedBuild', {
            label: installedLabel,
            name: installed.name,
            version: installed.version,
          })
        }}
      </p>
      <div v-if="installed.outdated" class="tools-section__outdated" data-field="outdated">
        <span>{{ t('settings.tools.outdated', { name: installed.name }) }}</span>
        <Button
          :label="t('settings.tools.downloadPinned', { label: installedLabel })"
          size="small"
          :loading="fetching"
          :disabled="bundledUseless || locked || fetching"
          data-action="download-pinned"
          @click="downloadPinned(installed.name)"
        >
          <template #icon>
            <Download :size="16" aria-hidden="true" />
          </template>
        </Button>
      </div>
    </div>
    <RefusalList :issues="bundledIssues" />
    <div v-if="fetching" class="tools-section__progress" role="status">
      <span>{{ fetchTask?.message || t('settings.tools.downloading') }}</span>
      <ProgressBar
        :value="fetchTask?.progress ?? undefined"
        :mode="typeof fetchTask?.progress === 'number' ? 'determinate' : 'indeterminate'"
        :pt="{ root: { 'aria-label': t('settings.tools.downloading') } }"
      />
    </div>

    <h3 class="tools-section__subtitle">{{ t('settings.tools.buildsTitle') }}</h3>
    <ToolBuildPicker :disabled="bundledUseless || locked" />

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

.tools-section__subtitle {
  margin: 0;
  font-size: var(--rf-font-size-md);
}

.tools-section__mismatch {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--rf-space-2);
  padding: var(--rf-space-3) var(--rf-space-4);
  border: 1px solid var(--p-status-warn-border-color);
  border-radius: var(--rf-radius-md);
  background: var(--p-status-warn-background);
  color: var(--rf-color-text);
}

.tools-section__mismatch-icon {
  margin-top: 0.1em;
  color: var(--p-status-warn-color);
}

.tools-section__mismatch-body {
  display: grid;
  gap: var(--rf-space-1);
  min-width: 0;
}

.tools-section__mismatch-title,
.tools-section__mismatch-help,
.tools-section__installed-line {
  margin: 0;
}

.tools-section__mismatch-title {
  font-weight: var(--rf-font-weight-medium);
}

.tools-section__mismatch-list {
  margin: 0;
  padding-inline-start: var(--rf-space-4);
  overflow-wrap: anywhere;
}

.tools-section__mismatch-list code {
  font-family: var(--rf-font-mono);
}

.tools-section__installed {
  display: grid;
  gap: var(--rf-space-2);
}

.tools-section__outdated {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-3);
}

.tools-section__progress {
  display: grid;
  gap: var(--rf-space-1);
}

.tools-section__rows {
  display: grid;
}
</style>
