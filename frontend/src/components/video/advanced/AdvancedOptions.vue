<script setup lang="ts">
import Checkbox from 'primevue/checkbox'
import InputText from 'primevue/inputtext'
import { computed, onBeforeUpdate, onUpdated, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { EncoderOption } from '@/api/types'
import Field from '@/components/base/Field.vue'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'

import CopyHdrMetadata from './CopyHdrMetadata.vue'
import CustomParams from './CustomParams.vue'
import OptionRow from './OptionRow.vue'
import {
  type Category,
  categoriesOf,
  categoryName,
  CUSTOM_CATEGORY,
  HDR_CATEGORY,
  optionPath,
  optionPointer,
} from './options'
import ResetButton from './ResetButton.vue'
import { useOptionSearch } from './useOptionSearch'
import { panelView } from './view'

const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()
const ui = useUiStore()
const id = useId()
const side = useTemplateRef<HTMLElement>('side')
const main = useTemplateRef<HTMLElement>('main')

const video = computed(() => editor.job?.video ?? null)
const encoder = computed(() =>
  video.value === null ? null : (system.definitions?.video_encoders?.[video.value.encoder] ?? null),
)
const options = computed(() => encoder.value?.options ?? [])
const categories = computed(() => categoriesOf(options.value))
const advanced = computed(() => video.value?.advanced ?? {})
const customParams = computed(() => video.value?.custom_params ?? '')
const disabled = computed(() => video.value?.passthrough === true)

const selected = computed(
  () =>
    categories.value.find((category) => category.id === panelView.category) ??
    (categories.value[0] as Category),
)
const searched = computed(() => panelView.query.trim())

const counts = computed<Record<string, number>>(() =>
  Object.fromEntries(
    categories.value.map((category) => [
      category.id,
      category.options.filter((option) => option.key in advanced.value).length,
    ]),
  ),
)

const { matches } = useOptionSearch(
  () => (options.value.length > 0 ? (encoder.value?.id ?? null) : null),
  () => searched.value,
)

const shown = computed<EncoderOption[]>(() => {
  const list = searched.value === '' ? selected.value.options : (matches.value ?? [])
  return panelView.changedOnly ? list.filter((option) => option.key in advanced.value) : list
})
/** The custom parameters match a search for their category's name. */
const customMatches = computed(() =>
  categoryName(CUSTOM_CATEGORY, t).toLowerCase().includes(searched.value.toLowerCase()),
)
const matchCount = computed(() => (matches.value?.length ?? 0) + (customMatches.value ? 1 : 0))
const customShown = computed(() => {
  if (panelView.changedOnly && customParams.value === '') return false
  if (searched.value === '') return selected.value.id === CUSTOM_CATEGORY
  return customMatches.value
})
/** Why nothing is shown; `null` while something is, or while the search is on its way. */
const empty = computed<'none-changed' | 'no-match' | null>(() => {
  if (shown.value.length > 0 || customShown.value) return null
  if (searched.value === '') return panelView.changedOnly ? 'none-changed' : null
  if (matches.value === null) return null
  return matchCount.value === 0 ? 'no-match' : 'none-changed'
})
const unknownKeys = computed(() =>
  Object.keys(advanced.value).filter((key) => !options.value.some((option) => option.key === key)),
)

function choose(category: string): void {
  panelView.category = category
  panelView.query = ''
}

/** A reveal of an option shows it: its category, without a search or filter that hides it. */
watch(
  () => ui.revealed,
  (request) => {
    if (request === null) return
    const option = options.value.find((candidate) => optionPath(candidate.key) === request.path)
    const category =
      request.path === 'video.custom_params' ? CUSTOM_CATEGORY : (option?.category ?? null)
    if (category === null) return
    const changed = option === undefined ? customParams.value !== '' : option.key in advanced.value
    if (panelView.changedOnly && !changed) panelView.changedOnly = false
    const found =
      option === undefined
        ? customShown.value
        : (matches.value?.some((match) => match.key === option.key) ?? false)
    if (searched.value !== '' && !found) panelView.query = ''
    panelView.category = category
  },
  { immediate: true },
)

// A reset or an emptied field under "Show only changed" takes the focused row away: the focus
// goes back to the view's choice instead of falling to the page. A blur on removal (Chromium)
// can start a second update before the first one's hook runs, so only a later focus replaces it.
let focused: Element | null = null
onBeforeUpdate(() => {
  const active = document.activeElement
  if (active !== null && main.value?.contains(active)) focused = active
})
onUpdated(() => {
  const lost = focused !== null && !focused.isConnected
  focused = null
  if (!lost || document.activeElement !== document.body) return
  const choice =
    side.value?.querySelector<HTMLElement>('[aria-current="true"]') ??
    side.value?.querySelector<HTMLElement>('[data-role="search"]')
  choice?.focus()
})
</script>

<template>
  <div class="advanced-options" data-panel="advanced">
    <div class="advanced-options__layout">
      <div ref="side" class="advanced-options__side">
        <InputText
          :model-value="panelView.query"
          type="search"
          :aria-label="t('advanced.search.label')"
          :placeholder="t('advanced.search.placeholder')"
          autocomplete="off"
          spellcheck="false"
          fluid
          data-role="search"
          @update:model-value="panelView.query = $event ?? ''"
        />
        <span class="advanced-options__check">
          <Checkbox v-model="panelView.changedOnly" :input-id="`${id}-changed`" binary />
          <label :for="`${id}-changed`">{{ t('advanced.changedOnly') }}</label>
        </span>
        <nav class="advanced-options__categories" :aria-label="t('advanced.categories')">
          <button
            v-for="category in categories"
            :key="category.id"
            type="button"
            class="advanced-options__category"
            :aria-current="searched === '' && category.id === selected.id ? 'true' : undefined"
            :data-category="category.id"
            :data-count="counts[category.id]"
            @click="choose(category.id)"
          >
            <span class="advanced-options__name">{{ categoryName(category.id, t) }}</span>
            <template v-if="counts[category.id]">
              <span class="advanced-options__count" aria-hidden="true">{{
                counts[category.id]
              }}</span>
              <span class="rf-sr-only">{{ t('advanced.changedCount', counts[category.id]!) }}</span>
            </template>
          </button>
        </nav>
      </div>

      <div ref="main" class="advanced-options__main">
        <!-- The custom parameters field's own label names its category. -->
        <h3 v-if="searched !== ''" class="advanced-options__title">
          {{ t('advanced.search.title') }}
        </h3>
        <h3 v-else-if="selected.id !== CUSTOM_CATEGORY" class="advanced-options__title">
          {{ categoryName(selected.id, t) }}
        </h3>
        <p
          v-if="searched !== ''"
          class="advanced-options__status"
          role="status"
          data-role="search-status"
        >
          {{
            matches === null
              ? t('advanced.search.searching')
              : t('advanced.search.count', matchCount)
          }}
        </p>
        <CopyHdrMetadata v-if="searched === '' && selected.id === HDR_CATEGORY" />
        <template v-if="encoder !== null">
          <OptionRow
            v-for="option in shown"
            :key="option.key"
            :option="option"
            :encoder="encoder"
            :disabled="disabled"
            :category="searched === '' ? undefined : categoryName(option.category, t)"
          />
        </template>
        <CustomParams v-if="customShown" />
        <p
          v-if="empty === 'none-changed'"
          class="advanced-options__empty"
          data-state="none-changed"
        >
          {{ searched === '' ? t('advanced.noneChanged') : t('advanced.search.noneChanged') }}
        </p>
        <p v-else-if="empty === 'no-match'" class="advanced-options__empty" data-state="no-match">
          {{ t('advanced.search.none', { query: searched }) }}
        </p>

        <div v-if="unknownKeys.length > 0" class="advanced-options__unknown" data-role="unknown">
          <h3 class="advanced-options__title">
            {{ t('advanced.unknown.title', { encoder: encoder?.label ?? video?.encoder }) }}
          </h3>
          <p class="advanced-options__hint">{{ t('advanced.unknown.hint') }}</p>
          <Field
            v-for="key in unknownKeys"
            :key="key"
            :label="key"
            :path="optionPath(key)"
            :data-option="key"
          >
            <div class="advanced-options__unknown-value">
              <code>{{ advanced[key] }}</code>
              <ResetButton
                :label="key"
                :disabled="disabled"
                @click="editor.patch([{ op: 'remove', path: optionPointer(key) }])"
              />
            </div>
          </Field>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.advanced-options {
  container-type: inline-size;
}

.advanced-options__layout {
  display: grid;
  grid-template-columns: minmax(11rem, 15rem) minmax(0, 1fr);
  align-items: start;
  gap: var(--rf-space-4);
}

.advanced-options__side {
  display: grid;
  gap: var(--rf-space-3);
}

.advanced-options__check {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.advanced-options__categories {
  display: grid;
  gap: 2px;
}

.advanced-options__category {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--rf-space-2);
  padding: var(--rf-space-1) var(--rf-space-2);
  border: 0;
  border-inline-start: 3px solid transparent;
  border-radius: var(--rf-radius-sm);
  background: none;
  color: var(--rf-color-text);
  font: inherit;
  text-align: start;
  cursor: pointer;
}

.advanced-options__category:hover {
  background: var(--rf-color-surface-hover);
}

/* The tint alone is too faint to tell the selection: the bar is the mark. */
.advanced-options__category[aria-current='true'] {
  border-inline-start-color: var(--rf-color-primary);
  background: color-mix(in srgb, var(--rf-color-primary) 16%, transparent);
  font-weight: var(--rf-font-weight-medium);
}

.advanced-options__count {
  min-width: 1.5rem;
  padding: 0 var(--rf-space-1);
  border-radius: var(--rf-radius-pill);
  background: var(--rf-color-primary);
  color: var(--rf-color-on-primary);
  font-size: var(--rf-font-size-xs);
  text-align: center;
}

.advanced-options__main {
  display: grid;
  gap: var(--rf-space-2);
  min-width: 0;
}

.advanced-options__title {
  margin: 0;
  font-size: var(--rf-font-size-md);
  font-weight: var(--rf-font-weight-bold);
}

.advanced-options__status,
.advanced-options__empty,
.advanced-options__hint {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.advanced-options__unknown {
  display: grid;
  gap: var(--rf-space-2);
  margin-top: var(--rf-space-3);
}

.advanced-options__unknown-value {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.advanced-options__unknown-value code {
  min-width: 0;
  overflow-wrap: anywhere;
}

/* In a narrow column the categories go above the options, side by side. */
@container (width < 40rem) {
  .advanced-options__layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .advanced-options__categories {
    display: flex;
    flex-wrap: wrap;
  }
}

/* As an option's row: in a narrow column the key goes above its value. */
@container (width < 30rem) {
  .advanced-options__unknown :deep(.rf-field--inline) {
    grid-template-columns: minmax(0, 1fr);
  }

  .advanced-options__unknown :deep(.rf-field--inline .rf-field__issues) {
    grid-column: 1;
  }
}
</style>
