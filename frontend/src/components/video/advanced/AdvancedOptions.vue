<script setup lang="ts">
import { RotateCcw } from '@lucide/vue'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import InputText from 'primevue/inputtext'
import vTooltip from 'primevue/tooltip'
import { computed, ref, useId, watch } from 'vue'
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
import { useOptionSearch } from './useOptionSearch'

const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()
const ui = useUiStore()
const id = useId()

const video = computed(() => editor.job?.video ?? null)
const encoder = computed(() =>
  video.value === null ? null : (system.definitions?.video_encoders?.[video.value.encoder] ?? null),
)
const options = computed(() => encoder.value?.options ?? [])
const categories = computed(() => categoriesOf(options.value))
const advanced = computed(() => video.value?.advanced ?? {})
const customParams = computed(() => video.value?.custom_params ?? '')
const disabled = computed(() => video.value?.passthrough === true)

const selectedId = ref<string | null>(null)
const selected = computed(
  () =>
    categories.value.find((category) => category.id === selectedId.value) ??
    (categories.value[0] as Category),
)
const changedOnly = ref(false)
const query = ref('')
const searched = computed(() => query.value.trim())

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
  return changedOnly.value ? list.filter((option) => option.key in advanced.value) : list
})
const customShown = computed(() => {
  if (changedOnly.value && customParams.value === '') return false
  if (searched.value === '') return selected.value.id === CUSTOM_CATEGORY
  return categoryName(CUSTOM_CATEGORY, t).toLowerCase().includes(searched.value.toLowerCase())
})
const unknownKeys = computed(() =>
  Object.keys(advanced.value).filter((key) => !options.value.some((option) => option.key === key)),
)

function choose(category: string): void {
  selectedId.value = category
  query.value = ''
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
    if (changedOnly.value && !changed) changedOnly.value = false
    const found =
      option === undefined
        ? customShown.value
        : (matches.value?.some((match) => match.key === option.key) ?? false)
    if (searched.value !== '' && !found) query.value = ''
    selectedId.value = category
  },
  { immediate: true },
)
</script>

<template>
  <div class="advanced-options" data-panel="advanced">
    <div class="advanced-options__layout">
      <div class="advanced-options__side">
        <InputText
          :model-value="query"
          type="search"
          :aria-label="t('advanced.search.label')"
          :placeholder="t('advanced.search.placeholder')"
          autocomplete="off"
          spellcheck="false"
          fluid
          data-role="search"
          @update:model-value="query = $event ?? ''"
        />
        <span class="advanced-options__check">
          <Checkbox v-model="changedOnly" :input-id="`${id}-changed`" binary />
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

      <div class="advanced-options__main">
        <h3 class="advanced-options__title">
          {{ searched === '' ? categoryName(selected.id, t) : t('advanced.search.title') }}
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
              : t('advanced.search.count', shown.length)
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
          v-if="shown.length === 0 && !customShown && searched === '' && changedOnly"
          class="advanced-options__empty"
          data-state="none-changed"
        >
          {{ t('advanced.noneChanged') }}
        </p>
        <p
          v-else-if="shown.length === 0 && !customShown && matches !== null && searched !== ''"
          class="advanced-options__empty"
          data-state="no-match"
        >
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
              <Button
                v-tooltip.top="t('advanced.reset', { label: key })"
                class="advanced-options__reset"
                text
                rounded
                size="small"
                :disabled="disabled"
                :aria-label="t('advanced.reset', { label: key })"
                data-action="reset"
                @click="editor.patch([{ op: 'remove', path: optionPointer(key) }])"
              >
                <template #icon><RotateCcw :size="16" aria-hidden="true" /></template>
              </Button>
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

.advanced-options__category[aria-current='true'] {
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

.advanced-options__reset {
  width: 1.75rem;
  height: 1.75rem;
  padding: 0;
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
</style>
