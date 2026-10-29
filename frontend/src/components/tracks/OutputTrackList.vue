<script setup lang="ts">
import { ListPlus, Plus, RotateCcw } from '@lucide/vue'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable, { type DataTableRowReorderEvent } from 'primevue/datatable'
import Menu from 'primevue/menu'
import vTooltip from 'primevue/tooltip'
import { computed, nextTick, ref, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, ApiError, unwrap } from '@/api/client'
import type {
  AudioOutputTrack,
  AudioStream,
  JsonPatchOp,
  SubtitleOutputTrack,
  SubtitleStream,
} from '@/api/types'
import Section from '@/components/base/Section.vue'
import { type SourceStream, streamLabel } from '@/components/media/streams'
import { useJobSource } from '@/components/summary/useJobSource'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'

import AudioTrackRow from './AudioTrackRow.vue'
import {
  addOps,
  moveOp,
  newAudioTrack,
  type NewTrackContext,
  newSubtitleTrack,
  removeOp,
  type TrackList,
  unusedStreams,
} from './ops'
import SubtitleTrackRow from './SubtitleTrackRow.vue'

/** The job's output tracks of one list: add, remove, reorder (drag or buttons), reload. */
const props = defineProps<{ list: TrackList }>()

const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()
const { source } = useJobSource()
const id = useId()

const root = useTemplateRef<HTMLElement>('root')
const addMenu = useTemplateRef<InstanceType<typeof Menu>>('addMenu')
const reloading = ref(false)
const title = computed(() => t('tracks.output.title'))

const audioTracks = computed<readonly AudioOutputTrack[]>(() => editor.job?.audio ?? [])
const subtitleTracks = computed<readonly SubtitleOutputTrack[]>(() => editor.job?.subtitles ?? [])
const audioStreams = computed<readonly AudioStream[]>(() => source.value?.audio ?? [])
const subtitleStreams = computed<readonly SubtitleStream[]>(() => source.value?.subtitles ?? [])

const tracks = computed(() => (props.list === 'audio' ? audioTracks.value : subtitleTracks.value))
const streams = computed<readonly SourceStream[]>(() =>
  props.list === 'audio' ? audioStreams.value : subtitleStreams.value,
)
/** DataTable rows: copies, since the job is frozen and the table must not hold it. */
const rows = computed(() => tracks.value.map((track, index) => ({ index, track })))
const unused = computed(() => unusedStreams(streams.value, tracks.value))

function context(): NewTrackContext {
  return {
    definitions: system.definitions,
    container: editor.job?.output?.container,
    draft: editor.draft,
    usable: (encoder) => system.encoderStatus(encoder)?.state !== 'unavailable',
  }
}

function adds(chosen: readonly SourceStream[]): JsonPatchOp[] {
  if (props.list === 'audio') {
    const ctx = context()
    return addOps('audio', chosen as AudioStream[], audioTracks.value, (stream, existing) =>
      newAudioTrack(stream, existing, ctx),
    )
  }
  return addOps('subtitles', chosen as SubtitleStream[], subtitleTracks.value, (stream, existing) =>
    newSubtitleTrack(stream, existing, { draft: editor.draft }),
  )
}

const addItems = computed(() =>
  streams.value.map((stream) => ({
    label: streamLabel(stream),
    command: () => editor.patch(adds([stream])),
  })),
)

function addAll(): void {
  if (unused.value.length > 0) editor.patch(adds(unused.value))
}

async function focusIn(index: number, selectors: string[]): Promise<void> {
  await nextTick()
  const row = root.value?.querySelector(`[data-path="${props.list}[${index}]"]`)
  for (const selector of selectors) {
    const found = row?.querySelector<HTMLElement>(`${selector}:not(:disabled)`)
    if (found) {
      found.focus()
      return
    }
  }
}

/** A move from the buttons keeps the focus on the moved track's button. */
function move(from: number, to: number): void {
  if (to < 0 || to >= tracks.value.length || to === from) return
  editor.patch([moveOp(props.list, from, to)])
  const first = to < from ? '[data-move="up"]' : '[data-move="down"]'
  const other = to < from ? '[data-move="down"]' : '[data-move="up"]'
  void focusIn(to, [first, other])
}

function onReorder(event: DataTableRowReorderEvent): void {
  if (event.dragIndex !== event.dropIndex) {
    editor.patch([moveOp(props.list, event.dragIndex, event.dropIndex)])
  }
}

async function remove(index: number): Promise<void> {
  editor.patch([removeOp(props.list, index)])
  const left = tracks.value.length
  if (left === 0) {
    await nextTick()
    root.value?.querySelector<HTMLElement>('[data-action="add"]')?.focus()
    return
  }
  await focusIn(Math.min(index, left - 1), ['[data-action="remove"]'])
}

/** Drafts the source again with the job's preset and takes this list from it: one undo step. */
async function reload(): Promise<void> {
  const target = editor.target
  if (target?.kind !== 'job' || reloading.value) return
  const session = editor.session
  reloading.value = true
  try {
    const answer = unwrap(
      await api.POST('/api/jobs/draft', {
        body: { source_id: target.sourceId, preset_id: editor.presetId },
      }),
    )
    if (editor.session !== session || editor.job === null) return
    editor.set(`/${props.list}`, answer.job[props.list] ?? [])
  } catch (error) {
    // The API client has shown the problem.
    if (!(error instanceof ApiError)) throw error
  } finally {
    reloading.value = false
  }
}
</script>

<template>
  <div ref="root" class="output-tracks" :data-list="list">
    <Section :title="title">
      <template #actions>
        <Button
          size="small"
          data-action="add"
          :label="t('tracks.output.add')"
          :disabled="streams.length === 0"
          aria-haspopup="menu"
          :aria-controls="`${id}-add`"
          @click="addMenu?.toggle($event)"
        >
          <template #icon><Plus :size="16" aria-hidden="true" /></template>
        </Button>
        <Menu ref="addMenu" :pt="{ root: { id: `${id}-add` } }" :model="addItems" popup />
        <Button
          v-tooltip.top="t('tracks.output.addAllHelp')"
          size="small"
          severity="secondary"
          data-action="add-all"
          :label="t('tracks.output.addAll')"
          :disabled="unused.length === 0"
          @click="addAll"
        >
          <template #icon><ListPlus :size="16" aria-hidden="true" /></template>
        </Button>
        <Button
          v-tooltip.top="t('tracks.output.reloadHelp')"
          size="small"
          severity="secondary"
          data-action="reload"
          :label="t('tracks.output.reload')"
          :loading="reloading"
          :disabled="editor.target?.kind !== 'job'"
          @click="reload"
        >
          <template #icon><RotateCcw :size="16" aria-hidden="true" /></template>
        </Button>
      </template>
      <p v-if="rows.length === 0" class="output-tracks__empty" data-state="empty">
        {{ list === 'audio' ? t('tracks.output.noAudio') : t('tracks.output.noSubtitles') }}
      </p>
      <DataTable
        v-else
        class="output-tracks__table"
        :value="rows"
        data-key="index"
        :table-props="{ 'aria-label': title }"
        @row-reorder="onReorder"
      >
        <Column row-reorder body-class="output-tracks__handle" header-class="output-tracks__handle">
          <template #header>
            <span class="rf-sr-only">{{ t('tracks.output.dragColumn') }}</span>
          </template>
        </Column>
        <Column body-class="output-tracks__editor">
          <template #header>
            <span class="rf-sr-only">{{ t('tracks.output.trackColumn') }}</span>
          </template>
          <template #body="{ data }">
            <AudioTrackRow
              v-if="list === 'audio'"
              :index="data.index"
              :count="rows.length"
              :track="data.track"
              :streams="audioStreams"
              @move="(to: number) => move(data.index, to)"
              @remove="remove(data.index)"
            />
            <SubtitleTrackRow
              v-else
              :index="data.index"
              :count="rows.length"
              :track="data.track"
              :streams="subtitleStreams"
              @move="(to: number) => move(data.index, to)"
              @remove="remove(data.index)"
            />
          </template>
        </Column>
      </DataTable>
    </Section>
  </div>
</template>

<style scoped>
.output-tracks__empty {
  margin: 0;
  color: var(--rf-color-text-muted);
}

/* DataTable makes its header sticky with an inline style. */
.output-tracks__table :deep(thead) {
  position: absolute !important;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
}

.output-tracks__table :deep(td) {
  vertical-align: top;
}

.output-tracks__table :deep(.output-tracks__editor) {
  width: 100%;
}

.output-tracks__table :deep(.output-tracks__handle) {
  width: 2rem;
  padding-inline: var(--rf-space-1);
  padding-top: var(--rf-space-4);
  cursor: grab;
}
</style>
