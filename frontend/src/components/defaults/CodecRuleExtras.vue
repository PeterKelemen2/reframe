<script setup lang="ts">
import { Plus, Trash2 } from '@lucide/vue'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import InputNumber from 'primevue/inputnumber'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import { computed, nextTick, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { AudioCodecRule } from '@/api/types'
import Field from '@/components/base/Field.vue'
import { describeTag } from '@/components/language/catalog'
import LanguageListEditor from '@/components/language/LanguageListEditor.vue'
import { kiloHertz } from '@/components/media/streams'
import { useDefaultsStore } from '@/stores/defaults'
import { useSystemStore } from '@/stores/system'

import IssueLines from './IssueLines.vue'
import { useCodecOptions } from './codecs'
import { type AudioRuleExtras, type ExtraAudioOutput, rulePath } from './model'
import { labelOf, useDefaultsOptions } from './options'
import ShownValue from './ShownValue.vue'

/** A codec rule's optional settings, shown in the rule's expanded row. */
const props = defineProps<{
  rule: AudioCodecRule
  index: number
  ruleKey: number
  /** The catch-all takes any language. */
  catchAll: boolean
}>()

const { t } = useI18n()
const defaults = useDefaultsStore()
const system = useSystemStore()
const choices = useDefaultsOptions()
const codecs = useCodecOptions()
const id = useId()
const root = useTemplateRef<HTMLElement>('root')

// Select shows its placeholder for `null`, so "same as the source" is a named value.
const SAME = 'same'

const path = computed(() => rulePath(props.ruleKey))
const extras = computed(() => props.rule.extras as AudioRuleExtras)
const outputs = computed<ExtraAudioOutput[]>(() => extras.value.extra_outputs ?? [])
const number = computed(() => props.index + 1)

function issuesAt(suffix: string) {
  return defaults.issuesAt(`${path.value}.${suffix}`)
}

function setRule(next: Partial<AudioCodecRule>): void {
  defaults.setRule(props.index, { ...props.rule, ...next })
}

function setExtras(next: Partial<AudioRuleExtras>): void {
  setRule({ extras: { ...extras.value, ...next } })
}

function setLanguages(languages: string[]): void {
  setRule({ languages: languages.length === 0 ? null : languages })
}

const samplerateOptions = computed(() => {
  const encoder = codecs.encoderOf(props.rule.codec)
  const rates = new Set(encoder?.samplerates ?? [])
  const current = extras.value.samplerate ?? null
  if (current !== null) rates.add(current)
  return [
    { value: SAME, label: t('defaults.rules.sameAsSource') },
    ...[...rates]
      .toSorted((a, b) => a - b)
      .map((rate) => ({
        value: String(rate),
        label: t('defaults.units.khz', { value: kiloHertz(rate) }),
      })),
  ]
})

function setNumber(key: 'gain' | 'drc', value: unknown): void {
  if (typeof value === 'number' && value !== extras.value[key]) setExtras({ [key]: value })
}

function setOutput(at: number, next: Partial<ExtraAudioOutput>): void {
  const list = outputs.value.map((output, index) =>
    index === at ? { ...output, ...next } : output,
  )
  setExtras({ extra_outputs: list })
}

function onOutputBitrate(at: number, value: unknown): void {
  const bitrate = typeof value === 'number' && value > 0 ? value : null
  if (bitrate !== (outputs.value[at]?.bitrate ?? null)) setOutput(at, { bitrate })
}

async function addOutput(): Promise<void> {
  setExtras({
    extra_outputs: [...outputs.value, { codec: 'aac', mixdown: 'stereo', bitrate: null }],
  })
  await nextTick()
  const rows = root.value?.querySelectorAll<HTMLElement>('[data-role="extra-output"]')
  rows?.[rows.length - 1]
    ?.querySelector<HTMLElement>('[data-field="codec"] input, [data-field="codec"]')
    ?.focus()
}

async function removeOutput(at: number): Promise<void> {
  setExtras({ extra_outputs: outputs.value.filter((_, index) => index !== at) })
  await nextTick()
  root.value?.querySelector<HTMLElement>('[data-action="add-output"]')?.focus()
}

/** The values as text, for a read-only preset. */
const shown = computed(() => {
  const value = extras.value
  return {
    languages: choices.list(
      (props.rule.languages ?? []).map(
        (tag) => describeTag(system.languages, tag)?.english_name ?? tag,
      ),
    ),
    samplerate: labelOf(
      samplerateOptions.value,
      value.samplerate == null ? SAME : String(value.samplerate),
    ),
    gain: t('defaults.units.db', { value: value.gain ?? 0 }),
    drc: value.drc ? String(value.drc) : t('defaults.shown.off'),
    loudness: labelOf(choices.loudness, value.loudness ?? 'off'),
    name: value.name_template || t('defaults.rules.nameFromSource'),
    first: value.first_track_of_language_only ? t('defaults.shown.yes') : t('defaults.shown.no'),
  }
})

function outputText(output: ExtraAudioOutput): string {
  return t('defaults.rules.extraOutputShown', {
    codec: codecs.label(output.codec),
    mixdown: labelOf(choices.mixdown, output.mixdown),
    bitrate:
      output.bitrate == null
        ? t('defaults.rules.encoderDefault')
        : t('defaults.units.kbps', { value: output.bitrate }),
  })
}
</script>

<template>
  <div v-if="defaults.readOnly" class="rule-extras" :data-rule-extras="ruleKey">
    <dl class="rule-extras__shown">
      <div v-if="!catchAll" class="rule-extras__pair">
        <dt>{{ t('defaults.rules.languages', { n: number }) }}</dt>
        <dd>
          <ShownValue
            :text="
              (rule.languages ?? []).length > 0 ? shown.languages : t('defaults.rules.anyLanguage')
            "
          />
        </dd>
      </div>
      <div class="rule-extras__pair">
        <dt>{{ t('defaults.rules.samplerate') }}</dt>
        <dd><ShownValue :text="shown.samplerate" /></dd>
      </div>
      <div class="rule-extras__pair">
        <dt>{{ t('defaults.rules.gain') }}</dt>
        <dd><ShownValue :text="shown.gain" /></dd>
      </div>
      <div class="rule-extras__pair">
        <dt>{{ t('defaults.rules.drc') }}</dt>
        <dd><ShownValue :text="shown.drc" /></dd>
      </div>
      <div class="rule-extras__pair">
        <dt>{{ t('defaults.rules.loudness') }}</dt>
        <dd><ShownValue :text="shown.loudness" /></dd>
      </div>
      <div class="rule-extras__pair">
        <dt>{{ t('defaults.rules.nameTemplate') }}</dt>
        <dd><ShownValue :text="shown.name" /></dd>
      </div>
      <div class="rule-extras__pair">
        <dt>{{ t('defaults.rules.firstTrackOnly') }}</dt>
        <dd><ShownValue :text="shown.first" /></dd>
      </div>
      <div class="rule-extras__pair">
        <dt>{{ t('defaults.rules.extraOutputs') }}</dt>
        <dd>
          <ShownValue v-for="(output, at) in outputs" :key="at" :text="outputText(output)" />
          <ShownValue v-if="outputs.length === 0" :text="t('defaults.rules.noExtraOutputs')" />
        </dd>
      </div>
    </dl>
  </div>
  <!-- Every expanded rule has the same fields: each control's name says which rule it is in. -->
  <div v-else ref="root" class="rule-extras" :data-rule-extras="ruleKey">
    <div v-if="!catchAll" class="rule-extras__languages">
      <span :id="`${id}-languages`" class="rule-extras__label">
        {{ t('defaults.rules.languages', { n: number }) }}
      </span>
      <LanguageListEditor
        :model-value="rule.languages ?? []"
        :label="t('defaults.rules.languages', { n: number })"
        :labelledby="`${id}-languages`"
        :container="defaults.container ?? undefined"
        @update:model-value="setLanguages"
      />
      <p v-if="(rule.languages ?? []).length === 0" class="rule-extras__hint">
        {{ t('defaults.rules.anyLanguageHint') }}
      </p>
    </div>
    <div class="rule-extras__grid">
      <Field
        :label="t('defaults.rules.samplerate')"
        :issues="issuesAt('extras.samplerate')"
        stacked
      >
        <template #default="{ id: inputId, invalid }">
          <Select
            :input-id="inputId"
            :ariaLabel="t('defaults.rules.named.samplerate', { n: number })"
            :invalid="invalid"
            :model-value="extras.samplerate == null ? SAME : String(extras.samplerate)"
            :options="samplerateOptions"
            option-label="label"
            option-value="value"
            fluid
            @update:model-value="setExtras({ samplerate: $event === SAME ? null : Number($event) })"
          />
        </template>
      </Field>
      <Field :label="t('defaults.rules.gain')" :issues="issuesAt('extras.gain')" stacked>
        <template #default="{ id: inputId, invalid }">
          <InputNumber
            :input-id="inputId"
            :ariaLabel="t('defaults.rules.named.gain', { n: number })"
            :model-value="extras.gain"
            :min="-20"
            :max="20"
            :step="1"
            :max-fraction-digits="1"
            :suffix="t('defaults.units.dbSuffix')"
            show-buttons
            :invalid="invalid"
            fluid
            @update:model-value="setNumber('gain', $event)"
          />
        </template>
      </Field>
      <Field
        :label="t('defaults.rules.drc')"
        :help="t('defaults.rules.drcHelp')"
        :issues="issuesAt('extras.drc')"
        stacked
      >
        <template #default="{ id: inputId, invalid }">
          <InputNumber
            :input-id="inputId"
            :ariaLabel="t('defaults.rules.named.drc', { n: number })"
            :model-value="extras.drc"
            :min="0"
            :max="4"
            :step="0.1"
            :max-fraction-digits="1"
            show-buttons
            :invalid="invalid"
            fluid
            @update:model-value="setNumber('drc', $event)"
          />
        </template>
      </Field>
      <Field :label="t('defaults.rules.loudness')" :issues="issuesAt('extras.loudness')" stacked>
        <template #default="{ id: inputId, invalid }">
          <Select
            :input-id="inputId"
            :ariaLabel="t('defaults.rules.named.loudness', { n: number })"
            :invalid="invalid"
            :model-value="extras.loudness"
            :options="choices.loudness"
            option-label="label"
            option-value="value"
            fluid
            @update:model-value="setExtras({ loudness: $event })"
          />
        </template>
      </Field>
      <Field
        :label="t('defaults.rules.nameTemplate')"
        :help="t('defaults.rules.nameTemplateHelp')"
        :issues="issuesAt('extras.name_template')"
        stacked
      >
        <template #default="{ id: inputId, invalid }">
          <InputText
            :id="inputId"
            :aria-label="t('defaults.rules.named.nameTemplate', { n: number })"
            :model-value="extras.name_template ?? ''"
            :placeholder="t('defaults.rules.nameTemplatePlaceholder')"
            :invalid="invalid"
            spellcheck="false"
            autocomplete="off"
            fluid
            @update:model-value="setExtras({ name_template: $event ? $event : null })"
          />
        </template>
      </Field>
    </div>
    <span class="rule-extras__check">
      <Checkbox
        :input-id="`${id}-first`"
        :ariaLabel="t('defaults.rules.named.firstTrackOnly', { n: number })"
        binary
        :model-value="extras.first_track_of_language_only"
        @update:model-value="setExtras({ first_track_of_language_only: $event === true })"
      />
      <label :for="`${id}-first`">{{ t('defaults.rules.firstTrackOnly') }}</label>
    </span>
    <div class="rule-extras__outputs">
      <span :id="`${id}-outputs`" class="rule-extras__label">
        {{ t('defaults.rules.extraOutputs') }}
      </span>
      <p class="rule-extras__hint">{{ t('defaults.rules.extraOutputsHelp') }}</p>
      <ul
        v-if="outputs.length > 0"
        class="rule-extras__output-list"
        :aria-labelledby="`${id}-outputs`"
      >
        <li
          v-for="(output, at) in outputs"
          :key="at"
          class="rule-extras__output"
          data-role="extra-output"
        >
          <Field
            :label="t('defaults.rules.codec')"
            :issues="issuesAt(`extras.extra_outputs[${at}].codec`)"
            stacked
          >
            <template #default="{ id: inputId, invalid }">
              <Select
                :input-id="inputId"
                :ariaLabel="t('defaults.rules.named.outputCodec', { n: number, output: at + 1 })"
                :invalid="invalid"
                :model-value="output.codec"
                :options="codecs.options(output.codec)"
                option-label="label"
                option-value="value"
                fluid
                data-field="codec"
                @update:model-value="setOutput(at, { codec: $event })"
              />
            </template>
          </Field>
          <Field
            :label="t('defaults.rules.mixdown')"
            :issues="issuesAt(`extras.extra_outputs[${at}].mixdown`)"
            stacked
          >
            <template #default="{ id: inputId, invalid }">
              <Select
                :input-id="inputId"
                :ariaLabel="t('defaults.rules.named.outputMixdown', { n: number, output: at + 1 })"
                :invalid="invalid"
                :model-value="output.mixdown"
                :options="choices.mixdown"
                option-label="label"
                option-value="value"
                fluid
                @update:model-value="setOutput(at, { mixdown: $event })"
              />
            </template>
          </Field>
          <Field
            :label="t('defaults.rules.bitrate')"
            :issues="issuesAt(`extras.extra_outputs[${at}].bitrate`)"
            stacked
          >
            <template #default="{ id: inputId, invalid }">
              <InputNumber
                :input-id="inputId"
                :ariaLabel="t('defaults.rules.named.outputBitrate', { n: number, output: at + 1 })"
                :model-value="output.bitrate ?? null"
                :min="1"
                :max="10000"
                :use-grouping="false"
                :suffix="t('defaults.units.kbpsSuffix')"
                :placeholder="t('defaults.rules.encoderDefault')"
                :invalid="invalid"
                fluid
                @update:model-value="onOutputBitrate(at, $event)"
              />
            </template>
          </Field>
          <Button
            class="rule-extras__remove"
            text
            rounded
            size="small"
            severity="secondary"
            data-action="remove-output"
            :aria-label="t('defaults.rules.named.removeOutput', { n: number, output: at + 1 })"
            @click="removeOutput(at)"
          >
            <template #icon><Trash2 :size="16" aria-hidden="true" /></template>
          </Button>
        </li>
      </ul>
      <Button
        class="rule-extras__add"
        size="small"
        severity="secondary"
        outlined
        data-action="add-output"
        :label="t('defaults.rules.addOutput')"
        :aria-label="t('defaults.rules.named.addOutput', { n: number })"
        @click="addOutput"
      >
        <template #icon><Plus :size="16" aria-hidden="true" /></template>
      </Button>
    </div>
    <IssueLines :issues="issuesAt('extras')" />
  </div>
</template>

<style scoped>
.rule-extras {
  display: grid;
  gap: var(--rf-space-3);
  padding: var(--rf-space-3) var(--rf-space-4);
  border-radius: var(--rf-radius-md);
  background: var(--rf-color-surface-hover);
}

.rule-extras__label {
  font-weight: var(--rf-font-weight-medium);
}

.rule-extras__languages,
.rule-extras__outputs {
  display: grid;
  gap: var(--rf-space-2);
  justify-items: start;
}

.rule-extras__hint {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.rule-extras__grid,
.rule-extras__shown {
  display: grid;
  align-items: end;
  grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr));
  gap: var(--rf-space-3) var(--rf-space-4);
}

.rule-extras__shown {
  align-items: start;
  margin: 0;
}

.rule-extras__pair {
  display: grid;
  gap: var(--rf-space-1);
  min-width: 0;
}

.rule-extras__pair dt {
  font-weight: var(--rf-font-weight-medium);
}

.rule-extras__pair dd {
  margin: 0;
}

.rule-extras__check {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.rule-extras__output-list {
  display: grid;
  gap: var(--rf-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.rule-extras__output {
  display: grid;
  grid-template-columns: repeat(3, minmax(9rem, 12rem)) auto;
  align-items: end;
  gap: var(--rf-space-2) var(--rf-space-3);
}

@media (width < 40rem) {
  .rule-extras__output {
    grid-template-columns: minmax(0, 1fr) auto;
  }
}
</style>
