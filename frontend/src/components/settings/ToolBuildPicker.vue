<script setup lang="ts">
import { Download, FileArchive, LoaderCircle } from '@lucide/vue'
import RadioButton from 'primevue/radiobutton'
import { computed, onMounted, ref, shallowRef, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { Schemas, ValidationIssue } from '@/api/types'
import FocusSafeButton from '@/components/shell/FocusSafeButton'
import { formatBytes } from '@/components/summary/format'
import { platform } from '@/platform'
import { useSystemStore } from '@/stores/system'

import RefusalList from './RefusalList.vue'
import { useBundledTools } from './useBundledTools'

type ToolBuildOffer = Schemas['ToolBuildOffer']

/**
 * The offered FFmpeg builds with their licence and source, *Download* and *Install from file*.
 * After a download that cannot reach the server it says so and points to the alternatives.
 */
const props = defineProps<{
  /** The settings are read-only, or the environment sets both tools. */
  disabled?: boolean
}>()

const ARCHIVE_FILTERS = ['.xz', '.zip']

const { t, n } = useI18n()
const system = useSystemStore()
const { fetching, fetchTask, install } = useBundledTools()
const id = useId()

const offers = computed<ToolBuildOffer[]>(() => system.builds?.builds ?? [])
const installed = computed(() => system.builds?.installed ?? null)
const desktop = computed(() => system.info?.mode === 'desktop')
const chosen = ref<string | null>(null)
const running = ref<'download' | 'file' | null>(null)
const offline = ref(false)
const issues = shallowRef<ValidationIssue[]>([])
const shadowedBy = ref<string | null>(null)

const busy = computed(() => props.disabled || fetching.value || running.value !== null)
const chosenOffer = computed(() => offers.value.find((offer) => offer.name === chosen.value))

function preselect(): void {
  if (chosenOffer.value !== undefined) return
  const usable = offers.value.filter((offer) => offer.size !== null && offer.size !== undefined)
  const wanted = [installed.value?.name, 'default']
  chosen.value =
    wanted.map((name) => usable.find((offer) => offer.name === name)).find(Boolean)?.name ??
    usable[0]?.name ??
    null
}
watch(offers, preselect, { immediate: true })

async function load(): Promise<void> {
  try {
    await system.loadBuilds()
  } catch (error) {
    // The API client has shown it as a toast; the list stays empty.
    if (!(error instanceof ApiError)) throw error
  }
}
onMounted(load)
// A download that the server or another front end ran changes the installed build.
watch(fetchTask, (now, before) => {
  if (before && !now) void load()
})

function sizeOf(offer: ToolBuildOffer): string | null {
  return typeof offer.size === 'number' ? formatBytes(offer.size, t, n) : null
}

async function run(
  kind: 'download' | 'file',
  source: { build: string } | { path: string },
): Promise<void> {
  running.value = kind
  offline.value = false
  issues.value = []
  shadowedBy.value = null
  try {
    const outcome = await install(source)
    offline.value = outcome.offline
    issues.value = outcome.issues
    shadowedBy.value = outcome.shadowedBy
  } finally {
    running.value = null
  }
}

async function download(): Promise<void> {
  if (busy.value || chosen.value === null) return
  await run('download', { build: chosen.value })
}

async function installFile(): Promise<void> {
  if (busy.value) return
  const [path] = await platform.pickFiles({ multiple: false, filters: ARCHIVE_FILTERS })
  if (path === undefined) return
  await run('file', { path })
}

const opened = ref(new Set<string>())

function toggled(name: string, event: Event): void {
  const next = new Set(opened.value)
  if ((event.target as HTMLDetailsElement).open) next.add(name)
  else next.delete(name)
  opened.value = next
}

async function openLink(link: string): Promise<void> {
  await platform.openExternal(link)
}
</script>

<template>
  <div class="build-picker" data-component="build-picker">
    <fieldset class="build-picker__builds">
      <legend class="build-picker__legend">{{ t('settings.builds.legend') }}</legend>
      <p v-if="offers.length === 0" class="build-picker__muted" data-field="no-builds">
        {{ system.builds === null ? t('settings.builds.loading') : t('settings.builds.none') }}
      </p>
      <div
        v-for="offer in offers"
        :key="offer.name"
        class="build-picker__build"
        :data-build="offer.name"
      >
        <RadioButton
          v-model="chosen"
          :input-id="`${id}-${offer.name}`"
          :name="`${id}-build`"
          :value="offer.name"
          :disabled="sizeOf(offer) === null"
        />
        <div class="build-picker__body">
          <label :for="`${id}-${offer.name}`" class="build-picker__label">
            <span class="build-picker__name">{{ offer.label }}</span>
            <code class="build-picker__id">{{ offer.name }}</code>
            <span
              v-if="installed?.name === offer.name"
              class="build-picker__installed"
              data-field="installed"
              >{{ t('settings.builds.installed') }}</span
            >
          </label>
          <p class="build-picker__summary">{{ offer.summary }}</p>
          <p class="build-picker__facts" data-field="facts">
            {{
              sizeOf(offer) === null
                ? t('settings.builds.factsNoArchive', {
                    version: offer.release_version,
                    license: offer.license,
                  })
                : t('settings.builds.facts', {
                    version: offer.release_version,
                    size: sizeOf(offer),
                    license: offer.license,
                  })
            }}
          </p>
          <details
            v-if="offer.source_links?.length"
            class="build-picker__sources"
            @toggle="toggled(offer.name, $event)"
          >
            <summary>{{ t('settings.builds.sources') }}</summary>
            <!-- Links in a closed details element are unreachable Tab stops to the a11y gate. -->
            <ul v-if="opened.has(offer.name)" class="build-picker__links">
              <li v-for="link in offer.source_links" :key="link">
                <a
                  :href="link"
                  target="_blank"
                  rel="noopener noreferrer"
                  @click.prevent="openLink(link)"
                  >{{ link }}</a
                >
              </li>
            </ul>
          </details>
        </div>
      </div>
    </fieldset>

    <p v-if="offline" class="build-picker__offline" role="alert" data-field="offline">
      {{ desktop ? t('settings.builds.offlineDesktop') : t('settings.builds.offlineWeb') }}
    </p>
    <RefusalList :issues="issues" />
    <p v-if="shadowedBy" class="build-picker__muted" role="status" data-field="shadowed">
      {{ t('settings.builds.shadowed', { path: shadowedBy }) }}
    </p>

    <div class="build-picker__actions">
      <FocusSafeButton
        class="build-picker__download"
        :label="t('settings.builds.download')"
        :disabled="busy || chosenOffer === undefined"
        data-action="download"
        @click="download"
      >
        <template #icon>
          <LoaderCircle
            v-if="running === 'download'"
            class="build-picker__spin"
            :size="18"
            aria-hidden="true"
          />
          <Download v-else :size="18" aria-hidden="true" />
        </template>
      </FocusSafeButton>
      <FocusSafeButton
        class="build-picker__file"
        :label="t('settings.builds.installFile')"
        severity="secondary"
        outlined
        :disabled="busy"
        data-action="install-file"
        @click="installFile"
      >
        <template #icon>
          <LoaderCircle
            v-if="running === 'file'"
            class="build-picker__spin"
            :size="18"
            aria-hidden="true"
          />
          <FileArchive v-else :size="18" aria-hidden="true" />
        </template>
      </FocusSafeButton>
    </div>
  </div>
</template>

<style scoped>
.build-picker {
  display: grid;
  gap: var(--rf-space-3);
}

.build-picker__builds {
  display: grid;
  gap: var(--rf-space-3);
  margin: 0;
  padding: 0;
  border: 0;
}

.build-picker__legend {
  padding: 0;
  margin-bottom: var(--rf-space-2);
  font-weight: var(--rf-font-weight-medium);
}

.build-picker__build {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--rf-space-2);
  align-items: start;
}

.build-picker__body {
  display: grid;
  gap: var(--rf-space-1);
}

.build-picker__label {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--rf-space-2);
}

.build-picker__name {
  font-weight: var(--rf-font-weight-medium);
}

.build-picker__id {
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-sm);
  color: var(--rf-color-text-muted);
}

.build-picker__installed {
  font-size: var(--rf-font-size-sm);
  color: var(--p-status-ok-color);
}

.build-picker__summary,
.build-picker__facts,
.build-picker__muted,
.build-picker__offline {
  margin: 0;
}

.build-picker__facts,
.build-picker__muted,
.build-picker__sources {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.build-picker__links {
  display: grid;
  gap: var(--rf-space-1);
  margin: var(--rf-space-1) 0 0;
  padding-inline-start: var(--rf-space-4);
  overflow-wrap: anywhere;
}

.build-picker__links a {
  display: inline-block;
  min-height: 24px;
  line-height: 24px;
}

.build-picker__offline {
  padding: var(--rf-space-2) var(--rf-space-3);
  border: 1px solid var(--p-status-error-border-color);
  border-radius: var(--rf-radius-md);
  background: var(--p-status-error-background);
  color: var(--rf-color-text);
}

.build-picker__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
}

.build-picker__spin {
  animation: build-picker-spin 1s linear infinite;
}

@keyframes build-picker-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
