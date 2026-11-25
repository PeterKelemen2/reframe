<script setup lang="ts">
import { TriangleAlert, X } from '@lucide/vue'
import Button from 'primevue/button'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Schemas, SourceEntry } from '@/api/types'
import { fileName } from '@/components/shell/format'

import { sourceSummary } from './panel'

/** One source in the panel: alone, or as a member of a batch group (`member`, `label`). */
const props = defineProps<{
  entry: SourceEntry
  member?: Schemas['GroupMember']
  /** The member's episode label (`E05`). */
  label?: string
  /** The member's episode title, shown after its label. */
  subTitle?: string | null
  /** `${idBase}-title` and `${idBase}-details` name the tree item, without its remove button. */
  idBase: string
}>()

const emit = defineEmits<{ remove: []; reprobe: [] }>()

const { t } = useI18n()

const name = computed(() => fileName(props.entry.path))
const summary = computed(() => sourceSummary(props.entry).join(' · '))
const warnings = computed(() => props.entry.source?.warnings ?? [])
const near = computed(() => props.member?.match === 'near')
/** The label is an episode code (`E05`), not the file name standing in for one. */
const episodic = computed(() => props.label !== undefined && props.label !== name.value)
</script>

<template>
  <div class="source-item" :data-path="entry.path">
    <div class="source-item__head">
      <span :id="`${idBase}-title`" class="source-item__title">
        <template v-if="member">
          <!-- A near match shows its differences below; the name says how it matched. -->
          <span class="rf-sr-only">{{
            near ? t('sources.group.near') : t('sources.group.exact')
          }}</span>
          <!-- Words apart in the row's name, which is built from these spans. -->
          {{ ' ' }}
          <span class="source-item__episode" :title="entry.path">
            <span
              class="source-item__label"
              :class="{
                'source-item__label--code': episodic,
                'source-item__label--alone': episodic && !subTitle,
              }"
              >{{ label }}</span
            >
            <template v-if="subTitle">
              {{ ' ' }}
              <span class="source-item__sub-title" data-field="sub-title">{{ subTitle }}</span>
            </template>
          </span>
        </template>
        <span v-else class="source-item__name" :title="entry.path">{{ name }}</span>
      </span>
      <Button
        class="source-item__remove"
        severity="secondary"
        text
        rounded
        size="small"
        tabindex="-1"
        :aria-label="t('sources.panel.remove', { name })"
        v-tooltip.left="t('sources.panel.remove', { name })"
        data-action="remove"
        @click.stop="emit('remove')"
      >
        <template #icon><X :size="14" aria-hidden="true" /></template>
      </Button>
    </div>
    <!-- Keeps the title and the details apart as words in the row's visible text. -->
    {{ ' ' }}
    <div :id="`${idBase}-details`" class="source-item__details">
      <p v-if="!member && summary" class="source-item__summary" data-field="summary">
        {{ summary }}
      </p>
      <ul v-if="near && member?.differences?.length" class="source-item__differences">
        <li v-for="line in member.differences" :key="line" data-field="difference">
          <TriangleAlert :size="14" aria-hidden="true" />
          <span>{{ line }}</span>
        </li>
      </ul>
      <div v-if="entry.source === null" class="source-item__stale" data-state="stale">
        <span>{{ t('sources.panel.stale') }}</span>
        <Button
          :label="t('sources.panel.reprobe')"
          link
          size="small"
          tabindex="-1"
          data-action="reprobe"
          @click.stop="emit('reprobe')"
        />
      </div>
      <!-- No aria-label: it would replace the warnings in the tree item's description. -->
      <ul v-if="warnings.length" class="source-item__warnings">
        <li v-for="(warning, index) in warnings" :key="index" data-field="warning">
          <TriangleAlert :size="14" aria-hidden="true" />
          <span>{{ warning }}</span>
          <!-- After the text: the row's name must hold its visible text unbroken. -->
          <span class="rf-sr-only">&nbsp;{{ t('sources.panel.warning') }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.source-item {
  --source-item-code: 2.25rem;

  display: grid;
  gap: 0.125rem;
  min-width: 0;
}

.source-item__head,
.source-item__title {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
  min-width: 0;
}

.source-item__title {
  flex: 1;
}

.source-item__details {
  display: grid;
  gap: 0.125rem;
  min-width: 0;
}

.source-item__details:empty {
  display: none;
}

.source-item__name,
.source-item__episode {
  overflow: hidden;
  flex: 1;
  min-width: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* An episode row: its code in a column of its own, then its title. */
.source-item__episode {
  display: flex;
  align-items: baseline;
  gap: var(--rf-space-2);
}

.source-item__label {
  overflow: hidden;
  text-overflow: ellipsis;
}

.source-item__label--code {
  flex: none;
  min-width: var(--source-item-code);
  color: var(--rf-color-text-muted);
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-sm);
  font-variant-numeric: tabular-nums;
}

.source-item__sub-title {
  overflow: hidden;
  min-width: 0;
  text-overflow: ellipsis;
}

/* The open row: the code in ink too, the name a step heavier. */
[aria-selected='true'] > .source-item .source-item__label--code,
.source-item__label--alone {
  color: var(--rf-color-text);
}

[aria-selected='true'] > .source-item .source-item__name,
[aria-selected='true'] > .source-item .source-item__sub-title {
  font-weight: var(--rf-font-weight-medium);
}

.source-item__remove {
  flex: none;
  width: 1.75rem;
  height: 1.75rem;
  margin-block: -0.25rem;
  margin-inline-start: auto;
  opacity: 0;
}

.source-item:hover .source-item__remove,
:focus-within > .source-item .source-item__remove,
:focus > .source-item .source-item__remove {
  opacity: 1;
}

.source-item__summary {
  overflow: hidden;
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-item__differences,
.source-item__warnings {
  display: grid;
  gap: 0.125rem;
  margin: 0;
  padding: 0;
  font-size: var(--rf-font-size-xs);
  list-style: none;
}

/* Under the title, past the code column. */
.source-item__differences {
  padding-inline-start: calc(var(--source-item-code) + var(--rf-space-2));
}

.source-item__differences li,
.source-item__warnings li {
  display: flex;
  align-items: flex-start;
  gap: var(--rf-space-1);
  color: var(--p-status-warn-color);
}

.source-item__differences li > svg,
.source-item__warnings li > svg {
  flex: none;
  margin-top: 0.15em;
}

.source-item__stale {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0 var(--rf-space-2);
  color: var(--p-status-error-color);
  font-size: var(--rf-font-size-sm);
}
</style>
