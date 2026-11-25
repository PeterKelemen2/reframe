<script setup lang="ts">
import { Check, ChevronDown } from '@lucide/vue'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import { computed, nextTick, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { Language } from '@/api/types'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

import { type Container, describeTag, searchLanguages, type WrittenAs, writtenAs } from './catalog'

/** One language (BCP 47) picked from a search dialog over `system.languages`; favourites first. */
const props = defineProps<{
  /** The accessible name when no `Field` labels it. */
  label?: string
  inputId?: string
  /** The id of the label element (`Field`'s `labelId`). */
  labelledby?: string
  placeholder?: string
  disabled?: boolean
  invalid?: boolean
  /** Offer *None* (`null`); for an output track it means "keep the source's language". */
  clearable?: boolean
  /** The text of *None*; already translated. */
  noneLabel?: string
  /** The ISO 639-2 code shown is the one this container writes (MP4: 639-2/T). */
  container?: Container
  /** Tags that are not offered (the members of an ordered list). */
  exclude?: readonly string[]
}>()

const model = defineModel<string | null>({ required: true })

const { t } = useI18n()
const system = useSystemStore()
const settings = useSettingsStore()

const id = useId()
const ownLabelId = `${id}-label`
const valueId = `${id}-value`
const listId = `${id}-list`
const searchId = `${id}-search`

const open = ref(false)
const query = ref('')
const active = ref(0)

const none = computed(() => props.noneLabel ?? t('language.picker.none'))
const current = computed(() => describeTag(system.languages, model.value))
const currentWritten = computed(() =>
  current.value ? writtenAs(current.value, props.container) : null,
)
const shortCodes = computed(() =>
  currentWritten.value
    ? t('language.picker.shortCodes', {
        iso: currentWritten.value.iso639_2,
        tag: currentWritten.value.tag,
      })
    : '',
)
const emptyText = computed(
  () => props.placeholder ?? (props.clearable ? none.value : t('language.picker.choose')),
)
const labelledBy = computed(() => {
  const name = props.labelledby ?? (props.label ? ownLabelId : null)
  return name ? `${name} ${valueId}` : undefined
})

interface Option {
  key: string
  language: Language | null
  written: WrittenAs | null
}

interface Group {
  key: 'none' | 'favourites' | 'others'
  heading: string | null
  options: { option: Option; index: number }[]
}

const favourites = computed(() => settings.settings?.languages?.favourites ?? [])
const found = computed(() =>
  searchLanguages(system.languages, query.value, favourites.value, props.exclude),
)

const groups = computed<Group[]>(() => {
  const result: Group[] = []
  let index = 0
  const add = (key: Group['key'], heading: string | null, options: Option[]) => {
    if (options.length === 0) return
    result.push({ key, heading, options: options.map((option) => ({ option, index: index++ })) })
  }
  const asOptions = (languages: Language[]) =>
    languages.map((language) => ({
      key: language.tag,
      language,
      written: writtenAs(language, props.container),
    }))
  if (props.clearable && query.value.trim() === '') {
    add('none', null, [{ key: '', language: null, written: null }])
  }
  const { favourites: favs, others } = found.value
  add('favourites', t('language.picker.favourites'), asOptions(favs))
  add('others', favs.length > 0 ? t('language.picker.all') : null, asOptions(others))
  return result
})
const options = computed(() => groups.value.flatMap((group) => group.options.map((o) => o.option)))
const languageCount = computed(() => options.value.filter((option) => option.language).length)

/** `GET /api/languages` failed at the start: nothing can be offered or named. */
const listMissing = computed(() => system.languages.length === 0)
const reading = ref(false)

async function readAgain(): Promise<void> {
  if (reading.value) return
  reading.value = true
  try {
    await system.loadDefinitions()
  } catch (error) {
    // The API client has shown the problem.
    if (!(error instanceof ApiError)) throw error
  } finally {
    reading.value = false
  }
  // The button goes with the message: the focus goes back to the search.
  if (!listMissing.value) {
    await nextTick()
    document.getElementById(searchId)?.focus()
  }
}

function codesText(written: WrittenAs): string {
  return ` · ${t('language.picker.codes', { iso: written.iso639_2, tag: written.tag })}`
}

function optionId(option: Option): string {
  return option.language ? `${id}-option-${option.language.tag}` : `${id}-none`
}

const activeOption = computed(() => options.value[active.value])

function isChosen(option: Option): boolean {
  return option.language ? option.language.tag === current.value?.tag : model.value === null
}

function show(initial = ''): void {
  if (props.disabled) return
  query.value = initial
  open.value = true
  const chosen = initial === '' ? options.value.findIndex(isChosen) : -1
  active.value = Math.max(chosen, 0)
  void revealActive()
}

async function revealActive(): Promise<void> {
  await nextTick()
  const option = activeOption.value
  if (option) document.getElementById(optionId(option))?.scrollIntoView?.({ block: 'nearest' })
}

// Sync: `show` clears the query and then marks the chosen language, which this must not undo.
watch(
  query,
  () => {
    active.value = 0
    void revealActive()
  },
  { flush: 'sync' },
)

function moveActive(by: number): void {
  const last = options.value.length - 1
  if (last < 0) return
  active.value = Math.min(Math.max(active.value + by, 0), last)
  void revealActive()
}

function choose(option: Option | undefined): void {
  if (!option) return
  open.value = false
  const tag = option.language?.tag ?? null
  if (tag !== model.value) model.value = tag
}

function onTriggerKey(event: KeyboardEvent): void {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    show()
    return
  }
  // Typing on the closed control starts the search with that letter.
  const printable = event.key.length === 1 && event.key !== ' '
  if (printable && !event.ctrlKey && !event.metaKey && !event.altKey) {
    event.preventDefault()
    show(event.key)
  }
}

function onSearchKey(event: KeyboardEvent): void {
  switch (event.key) {
    case 'ArrowDown':
      moveActive(1)
      break
    case 'ArrowUp':
      moveActive(-1)
      break
    case 'PageDown':
      moveActive(10)
      break
    case 'PageUp':
      moveActive(-10)
      break
    case 'Enter':
      choose(activeOption.value)
      break
    default:
      return
  }
  event.preventDefault()
}

/** Escape closes the picker only: the Dialog's own Escape would also close a dialog around it. */
function onDialogKey(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  event.stopPropagation()
  open.value = false
}
</script>

<template>
  <span class="language-picker">
    <span v-if="label && !labelledby" :id="ownLabelId" class="rf-sr-only">{{ label }}</span>
    <button
      :id="inputId"
      type="button"
      class="language-picker__trigger"
      :class="{ 'language-picker__trigger--invalid': invalid }"
      :disabled="disabled"
      aria-haspopup="dialog"
      :aria-expanded="open"
      :aria-labelledby="labelledBy"
      :aria-invalid="invalid || undefined"
      :data-tag="model ?? undefined"
      @click="show()"
      @keydown="onTriggerKey"
    >
      <span :id="valueId" class="language-picker__value">
        <template v-if="currentWritten">
          <span class="language-picker__name">{{ currentWritten.name }}</span>
          <!-- The space keeps the name and the codes apart for a screen reader. -->
          <span class="language-picker__codes">{{ ` ${shortCodes}` }}</span>
        </template>
        <template v-else-if="model">
          <span class="language-picker__name">{{ model }}</span>
          <span v-if="listMissing" class="language-picker__codes" data-state="unnamed">{{
            ` ${t('language.picker.notNamed')}`
          }}</span>
        </template>
        <span v-else class="language-picker__empty">{{ emptyText }}</span>
      </span>
      <ChevronDown class="language-picker__chevron" :size="16" aria-hidden="true" />
    </button>
    <Dialog
      v-model:visible="open"
      modal
      :header="label ?? t('language.picker.title')"
      class="language-picker-dialog"
      :style="{ width: 'min(34rem, calc(100vw - 2rem))' }"
      :draggable="false"
      :close-on-escape="false"
      :pt="{ root: { onKeydown: onDialogKey } }"
    >
      <div class="language-picker__panel">
        <InputText
          :id="searchId"
          :model-value="query"
          autofocus
          fluid
          role="combobox"
          aria-autocomplete="list"
          aria-expanded="true"
          :aria-controls="listId"
          :aria-activedescendant="activeOption ? optionId(activeOption) : undefined"
          :aria-describedby="listMissing ? `${id}-failed` : undefined"
          :aria-label="t('language.picker.search')"
          :placeholder="t('language.picker.searchPlaceholder')"
          autocomplete="off"
          spellcheck="false"
          data-role="search"
          @update:model-value="query = $event ?? ''"
          @keydown="onSearchKey"
        />
        <span class="rf-sr-only" aria-live="polite">
          {{ listMissing ? '' : t('language.picker.count', languageCount) }}
        </span>
        <div v-if="listMissing" class="language-picker__failed" data-state="failed">
          <p :id="`${id}-failed`">{{ t('language.picker.failed') }}</p>
          <Button
            size="small"
            severity="secondary"
            :label="t('language.picker.readAgain')"
            :loading="reading"
            data-action="read-languages"
            @click="readAgain"
          />
        </div>
        <div
          :id="listId"
          class="language-picker__list"
          role="listbox"
          tabindex="-1"
          :aria-label="t('language.picker.list')"
        >
          <div
            v-for="group in groups"
            :key="group.key"
            role="group"
            :aria-labelledby="group.heading ? `${id}-${group.key}` : undefined"
            :data-group="group.key"
          >
            <div
              v-if="group.heading"
              :id="`${id}-${group.key}`"
              role="presentation"
              class="language-picker__heading"
            >
              {{ group.heading }}
            </div>
            <div
              v-for="{ option, index } in group.options"
              :id="optionId(option)"
              :key="option.key"
              role="option"
              class="language-picker__option"
              :class="{ 'language-picker__option--active': index === active }"
              :aria-selected="isChosen(option)"
              :data-tag="option.language?.tag ?? ''"
              @mousedown.prevent
              @mousemove="active = index"
              @click="choose(option)"
            >
              <Check
                class="language-picker__check"
                :class="{ 'language-picker__check--shown': isChosen(option) }"
                :size="16"
                aria-hidden="true"
              />
              <span v-if="option.language && option.written" class="language-picker__option-text">
                <span class="language-picker__written">
                  <strong>{{ option.written.name }}</strong>
                  <span>{{ codesText(option.written) }}</span>
                </span>
                <span
                  v-if="option.language.native_name !== option.language.english_name"
                  class="language-picker__native"
                  :lang="option.language.tag"
                >
                  {{ option.language.native_name }}
                </span>
              </span>
              <span v-else class="language-picker__option-text">{{ none }}</span>
            </div>
          </div>
        </div>
        <p
          v-if="options.length === 0 && !listMissing"
          class="language-picker__no-match"
          data-state="empty"
        >
          {{ t('language.picker.noMatch', { query: query.trim() }) }}
        </p>
      </div>
    </Dialog>
  </span>
</template>

<style scoped>
.language-picker {
  display: inline-flex;
  max-width: 100%;
}

.language-picker__trigger {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-2);
  min-width: 14rem;
  max-width: 100%;
  padding-block: var(--p-inputtext-padding-y);
  padding-inline: var(--p-inputtext-padding-x);
  border: 1px solid var(--p-inputtext-border-color);
  border-radius: var(--p-inputtext-border-radius);
  background: var(--p-inputtext-background);
  box-shadow: var(--p-inputtext-shadow);
  color: var(--p-inputtext-color);
  font: inherit;
  text-align: start;
  cursor: pointer;
  transition:
    border-color var(--rf-duration),
    outline-color var(--rf-duration);
}

.language-picker__trigger:enabled:hover {
  border-color: var(--p-inputtext-hover-border-color);
}

/* The app's focus ring: a field's own ring has no width, and its border change alone is faint. */
.language-picker__trigger:focus-visible {
  border-color: var(--p-inputtext-focus-border-color);
  outline: var(--p-focus-ring-width) var(--p-focus-ring-style) var(--p-focus-ring-color);
  outline-offset: var(--p-focus-ring-offset);
}

.language-picker__trigger--invalid {
  border-color: var(--p-inputtext-invalid-border-color);
}

.language-picker__trigger:disabled {
  background: var(--p-inputtext-disabled-background);
  color: var(--p-inputtext-disabled-color);
  cursor: default;
}

.language-picker__value {
  display: flex;
  flex: 1;
  align-items: baseline;
  gap: var(--rf-space-2);
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}

.language-picker__name {
  overflow: hidden;
  text-overflow: ellipsis;
}

.language-picker__codes,
.language-picker__empty {
  color: var(--rf-color-text-muted);
}

.language-picker__codes {
  font-size: var(--rf-font-size-sm);
}

.language-picker__chevron {
  flex: none;
  color: var(--rf-color-text-muted);
}

.language-picker__panel {
  display: grid;
  gap: var(--rf-space-3);
}

.language-picker__list {
  max-height: min(26rem, 55vh);
  overflow: auto;
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md);
}

.language-picker__list:empty {
  display: none;
}

.language-picker__heading {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: var(--rf-space-1) var(--rf-space-3);
  border-bottom: 1px solid var(--rf-color-border);
  background: var(--rf-color-surface);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
  font-weight: var(--rf-font-weight-medium);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.language-picker__option {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: var(--rf-space-2);
  padding: var(--rf-space-2) var(--rf-space-3);
  cursor: pointer;
  user-select: none;
}

.language-picker__option--active {
  outline: 2px solid var(--rf-color-primary);
  outline-offset: -2px;
  background: var(--rf-color-surface-hover);
}

.language-picker__option[aria-selected='true'] {
  background: color-mix(in srgb, var(--rf-color-primary) 8%, transparent);
}

.language-picker__check {
  visibility: hidden;
  margin-top: 0.15em;
  color: var(--rf-color-primary);
}

.language-picker__check--shown {
  visibility: visible;
}

.language-picker__option-text {
  display: grid;
  min-width: 0;
}

.language-picker__written strong {
  font-weight: var(--rf-font-weight-medium);
}

.language-picker__written span {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.language-picker__native {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.language-picker__failed {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2) var(--rf-space-3);
  padding: var(--rf-space-3);
  border-radius: var(--rf-radius-md);
  background: var(--p-status-error-background);
  color: var(--p-status-error-color);
}

.language-picker__failed p {
  flex: 1 1 14rem;
  margin: 0;
}

.language-picker__no-match {
  margin: 0;
  padding: var(--rf-space-4);
  color: var(--rf-color-text-muted);
  text-align: center;
}
</style>
