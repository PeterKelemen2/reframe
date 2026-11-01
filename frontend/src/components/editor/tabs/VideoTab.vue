<script setup lang="ts">
import InputNumber from 'primevue/inputnumber'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { JsonPatchOp } from '@/api/types'
import Field from '@/components/base/Field.vue'
import Section from '@/components/base/Section.vue'
import TrackMetadataEditor from '@/components/tracks/TrackMetadataEditor.vue'
import ChoiceSelect from '@/components/video/ChoiceSelect.vue'
import CommandPreview from '@/components/video/CommandPreview.vue'
import EncoderBanner from '@/components/video/EncoderBanner.vue'
import EncoderPicker from '@/components/video/EncoderPicker.vue'
import {
  type AverageBitrate,
  bandFor,
  bitDepthOps,
  defaultBitrate,
  no10BitReason,
  switchEncoderOps,
} from '@/components/video/encoders'
import { FRAME_RATES, rateKey, SAME_RATE } from '@/components/video/frameRates'
import QualitySlider from '@/components/video/QualitySlider.vue'
import SpeedPresetSlider from '@/components/video/SpeedPresetSlider.vue'
import { useOutputLines } from '@/components/video/useOutputLines'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'
import { useToastStore } from '@/stores/toasts'

const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()
const toasts = useToastStore()
const picker = useTemplateRef<InstanceType<typeof EncoderPicker>>('picker')
const { lines } = useOutputLines()

const video = computed(() => editor.job?.video ?? null)
const encoders = computed(() => system.definitions?.video_encoders ?? {})
const encoder = computed(() => (video.value ? (encoders.value[video.value.encoder] ?? null) : null))
const passthrough = computed(() => video.value?.passthrough === true)
const quality = computed(() => encoder.value?.rate_control?.quality ?? null)
const bitrate = computed(() => encoder.value?.rate_control?.bitrate ?? null)
const rc = computed(() => video.value?.rate_control ?? null)
const band = computed(() => (quality.value ? bandFor(quality.value, lines.value) : null))

// What the other rate-control mode had, so that switching back brings it back (per job).
let rememberedQuality: number | null = null
let rememberedBitrate: AverageBitrate | null = null
watch(
  () => editor.session,
  () => {
    rememberedQuality = null
    rememberedBitrate = null
  },
)

function patch(ops: JsonPatchOp[]): void {
  editor.patch(ops)
}

function chooseEncoder(id: string): void {
  const current = video.value
  if (current === null) return
  editor.patch(switchEncoderOps(current, id, encoders.value, system.capabilities))
  if (current.custom_params !== '') {
    toasts.push({
      severity: 'info',
      summary: t('video.encoder.paramsCleared'),
      detail: t('video.encoder.paramsClearedDetail', { encoder: current.encoder }),
      life: 8000,
    })
  }
}

const modeOptions = computed(() => [
  ...(quality.value ? [{ value: 'quality', label: t('video.rate.quality') }] : []),
  ...(bitrate.value ? [{ value: 'bitrate', label: t('video.rate.bitrate') }] : []),
])

function setMode(mode: unknown): void {
  const current = rc.value
  if (current === null || mode === current.mode) return
  if (mode === 'quality' && quality.value) {
    if (current.mode === 'bitrate') rememberedBitrate = current
    const value = rememberedQuality ?? quality.value.default
    editor.set('/video/rate_control', { mode: 'quality', value })
  } else if (mode === 'bitrate' && bitrate.value) {
    if (current.mode === 'quality') rememberedQuality = current.value
    const limits = bitrate.value
    const kept = rememberedBitrate
    editor.set(
      '/video/rate_control',
      kept === null
        ? defaultBitrate(limits)
        : { ...kept, kbps: Math.min(Math.max(kept.kbps, limits.min_kbps), limits.max_kbps) },
    )
  }
}

function setQuality(value: number): void {
  editor.set('/video/rate_control/value', value, { coalesce: 'video.rate_control.value' })
}

function setKbps(value: number | null | undefined): void {
  if (typeof value === 'number' && rc.value?.mode === 'bitrate' && value !== rc.value.kbps) {
    editor.set('/video/rate_control/kbps', value)
  }
}

function setTwoPass(on: boolean): void {
  const ops: JsonPatchOp[] = [{ op: 'replace', path: '/video/rate_control/two_pass', value: on }]
  if (!on) ops.push({ op: 'replace', path: '/video/rate_control/turbo_first_pass', value: false })
  patch(ops)
}

const twoPassSupported = computed(() => (bitrate.value?.two_pass ?? null) !== null)

const rateOptions = computed(() => {
  const current = video.value?.framerate ?? null
  const options = [
    { value: SAME_RATE, label: t('video.framerate.same') },
    ...FRAME_RATES.map((rate) => ({ value: rateKey(rate), label: rate.label })),
  ]
  if (current !== null && !FRAME_RATES.some((rate) => rateKey(rate) === rateKey(current))) {
    options.push({ value: rateKey(current), label: rateKey(current) })
  }
  return options
})

function setRate(value: unknown): void {
  const [num, den] =
    typeof value === 'string' && value !== SAME_RATE ? value.split('/').map(Number) : []
  editor.set('/video/framerate', num && den ? { num, den } : null)
}

const frameModes = computed(() => [
  { value: 'variable', label: t('video.framerate.variable') },
  { value: 'constant', label: t('video.framerate.constant') },
  { value: 'peak', label: t('video.framerate.peak') },
])

const status = computed(() => (video.value ? system.encoderStatus(video.value.encoder) : undefined))
const tenBitBlocked = computed(() =>
  encoder.value === null
    ? 'no_mode'
    : no10BitReason(encoder.value, status.value, system.capabilities),
)
const showBitDepth = computed(
  () =>
    encoder.value !== null &&
    ('10' in (encoder.value.pix_fmts ?? {}) || video.value?.bit_depth === 10),
)
const depthOptions = computed(() => [
  { value: 8, label: t('video.bitDepth.bits', { bits: 8 }), disabled: false },
  {
    value: 10,
    label: t('video.bitDepth.bits', { bits: 10 }),
    disabled: tenBitBlocked.value !== null,
  },
])
const tenBitNote = computed(() => {
  switch (tenBitBlocked.value) {
    case 'no_mode':
      return t('video.bitDepth.noMode')
    case 'test_failed':
      return status.value?.reason_10bit ?? t('video.bitDepth.testFailed')
    default:
      return null
  }
})

function setBitDepth(depth: unknown): void {
  if (
    (depth === 8 || depth === 10) &&
    video.value &&
    encoder.value &&
    depth !== video.value.bit_depth
  ) {
    patch(bitDepthOps(video.value, encoder.value, depth))
  }
}

function defaultLabel(field: 'tune' | 'profile' | 'level'): string {
  const setting = encoder.value?.[`${field}s`] ?? null
  const depth = String(video.value?.bit_depth ?? 8)
  const value = setting?.default_by_depth?.[depth] ?? setting?.default ?? null
  const choice = setting?.choices.find((candidate) => candidate.value === value)
  if (choice !== undefined) return t('video.choice.default', { label: choice.label })
  switch (field) {
    case 'tune':
      return t('video.choice.noTune')
    case 'profile':
      return t('video.choice.auto')
    case 'level':
      return t('video.choice.auto')
  }
}
</script>

<template>
  <section class="editor-tab video-tab" data-tab="video">
    <div v-if="video !== null" class="video-tab__content">
      <EncoderBanner @choose="picker?.open()" />

      <Section :title="t('video.sections.encoder')">
        <Field :label="t('video.passthrough.label')" path="video.passthrough">
          <template #default="{ id, labelId }">
            <div class="video-tab__inline">
              <ToggleSwitch
                :input-id="id"
                :model-value="passthrough"
                :ariaLabelledby="labelId"
                @update:model-value="editor.set('/video/passthrough', $event)"
              />
              <span class="video-tab__hint">{{ t('video.passthrough.hint') }}</span>
            </div>
          </template>
        </Field>
        <p v-if="passthrough" class="video-tab__note" data-note="passthrough">
          {{ t('video.passthrough.note') }}
        </p>
        <Field
          :label="t('video.encoder.label')"
          path="video.encoder"
          :help="encoder?.help || undefined"
        >
          <template #default="{ id, labelId, invalid }">
            <EncoderPicker
              ref="picker"
              :model-value="video.encoder"
              :input-id="id"
              :labelledby="labelId"
              :invalid="invalid"
              :disabled="passthrough"
              @update:model-value="chooseEncoder"
            />
          </template>
        </Field>
      </Section>

      <Section :title="t('video.sections.quality')">
        <Field
          v-if="modeOptions.length > 1"
          :label="t('video.rate.label')"
          path="video.rate_control"
        >
          <template #default="{ id, labelId }">
            <SelectButton
              :pt="{ root: { id } }"
              :model-value="rc?.mode"
              :options="modeOptions"
              option-label="label"
              option-value="value"
              :allow-empty="false"
              :disabled="passthrough"
              :ariaLabelledby="labelId"
              @update:model-value="setMode"
            />
          </template>
        </Field>
        <Field
          v-if="rc?.mode === 'quality' && quality"
          :label="t('video.quality.label', { scale: quality.label })"
          path="video.rate_control.value"
          :help="quality.help || undefined"
        >
          <template #default="{ id, labelId, invalid }">
            <QualitySlider
              :mode="quality"
              :model-value="rc.value"
              :band="band"
              :lines="lines"
              :input-id="id"
              :labelledby="labelId"
              :invalid="invalid"
              :disabled="passthrough"
              @update:model-value="setQuality"
              @commit="editor.endCoalescing()"
            />
          </template>
        </Field>
        <template v-else-if="rc?.mode === 'bitrate'">
          <Field
            :label="t('video.bitrate.label')"
            path="video.rate_control.kbps"
            :help="bitrate?.help || undefined"
          >
            <template #default="{ id, invalid }">
              <InputNumber
                :input-id="id"
                :model-value="rc.kbps"
                :min="bitrate?.min_kbps"
                :max="bitrate?.max_kbps"
                :step="100"
                :suffix="` ${t('video.bitrate.unit')}`"
                :invalid="invalid"
                :disabled="passthrough"
                @update:model-value="setKbps"
              />
            </template>
          </Field>
          <Field :label="t('video.bitrate.twoPass')" path="video.rate_control.two_pass">
            <template #default="{ id, labelId }">
              <div class="video-tab__inline">
                <ToggleSwitch
                  :input-id="id"
                  :model-value="rc.two_pass"
                  :ariaLabelledby="labelId"
                  :disabled="passthrough || (!twoPassSupported && !rc.two_pass)"
                  @update:model-value="setTwoPass"
                />
                <span v-if="!twoPassSupported" class="video-tab__hint">{{
                  t('video.bitrate.noTwoPass')
                }}</span>
              </div>
            </template>
          </Field>
          <Field :label="t('video.bitrate.turbo')" path="video.rate_control.turbo_first_pass">
            <template #default="{ id, labelId }">
              <div class="video-tab__inline">
                <ToggleSwitch
                  :input-id="id"
                  :model-value="rc.turbo_first_pass"
                  :ariaLabelledby="labelId"
                  :disabled="passthrough || (!rc.two_pass && !rc.turbo_first_pass)"
                  @update:model-value="editor.set('/video/rate_control/turbo_first_pass', $event)"
                />
                <span class="video-tab__hint">{{ t('video.bitrate.turboHint') }}</span>
              </div>
            </template>
          </Field>
        </template>
      </Section>

      <Section :title="t('video.sections.framerate')">
        <Field :label="t('video.framerate.label')" path="video.framerate">
          <template #default="{ id, labelId, invalid }">
            <Select
              :input-id="id"
              :model-value="video.framerate ? rateKey(video.framerate) : SAME_RATE"
              :options="rateOptions"
              option-label="label"
              option-value="value"
              :ariaLabelledby="labelId"
              :invalid="invalid"
              :disabled="passthrough"
              fluid
              @update:model-value="setRate"
            />
          </template>
        </Field>
        <Field
          :label="t('video.framerate.mode')"
          path="video.framerate_mode"
          :help="t('video.framerate.modeHelp')"
        >
          <template #default="{ id, labelId }">
            <SelectButton
              :pt="{ root: { id } }"
              :model-value="video.framerate_mode"
              :options="frameModes"
              option-label="label"
              option-value="value"
              :allow-empty="false"
              :disabled="passthrough"
              :ariaLabelledby="labelId"
              @update:model-value="editor.set('/video/framerate_mode', $event)"
            />
          </template>
        </Field>
      </Section>

      <Section v-if="encoder" :title="t('video.sections.encoderSettings')">
        <Field
          v-if="encoder.presets"
          :label="t('video.speed.label')"
          path="video.preset"
          :help="encoder.presets.help || undefined"
        >
          <template #default="{ id, labelId }">
            <SpeedPresetSlider
              :setting="encoder.presets"
              :model-value="video.preset ?? null"
              :input-id="id"
              :labelledby="labelId"
              :disabled="passthrough"
              @update:model-value="
                editor.set('/video/preset', $event, { coalesce: 'video.preset' })
              "
              @commit="editor.endCoalescing()"
            />
          </template>
        </Field>
        <Field
          v-if="encoder.tunes"
          :label="t('video.tune.label')"
          path="video.tune"
          :help="encoder.tunes.help || undefined"
        >
          <template #default="{ id, labelId, invalid }">
            <ChoiceSelect
              :setting="encoder.tunes"
              :model-value="video.tune"
              :none-label="defaultLabel('tune')"
              :input-id="id"
              :labelledby="labelId"
              :invalid="invalid"
              :disabled="passthrough"
              @update:model-value="editor.set('/video/tune', $event)"
            />
          </template>
        </Field>
        <Field
          v-if="encoder.profiles"
          :label="t('video.profile.label')"
          path="video.profile"
          :help="encoder.profiles.help || undefined"
        >
          <template #default="{ id, labelId, invalid }">
            <ChoiceSelect
              :setting="encoder.profiles"
              :model-value="video.profile"
              :none-label="defaultLabel('profile')"
              :bit-depth="video.bit_depth"
              :input-id="id"
              :labelledby="labelId"
              :invalid="invalid"
              :disabled="passthrough"
              @update:model-value="editor.set('/video/profile', $event)"
            />
          </template>
        </Field>
        <Field
          v-if="encoder.levels"
          :label="t('video.level.label')"
          path="video.level"
          :help="encoder.levels.help || undefined"
        >
          <template #default="{ id, labelId, invalid }">
            <ChoiceSelect
              :setting="encoder.levels"
              :model-value="video.level"
              :none-label="defaultLabel('level')"
              :input-id="id"
              :labelledby="labelId"
              :invalid="invalid"
              :disabled="passthrough"
              @update:model-value="editor.set('/video/level', $event)"
            />
          </template>
        </Field>
        <Field
          v-if="encoder.fast_decode || video.fast_decode"
          :label="t('video.fastDecode.label')"
          path="video.fast_decode"
        >
          <template #default="{ id, labelId }">
            <div class="video-tab__inline">
              <ToggleSwitch
                :input-id="id"
                :model-value="video.fast_decode"
                :ariaLabelledby="labelId"
                :disabled="passthrough"
                @update:model-value="editor.set('/video/fast_decode', $event)"
              />
              <span class="video-tab__hint">{{ t('video.fastDecode.hint') }}</span>
            </div>
          </template>
        </Field>
        <Field v-if="showBitDepth" :label="t('video.bitDepth.label')" path="video.bit_depth">
          <template #default="{ id, labelId }">
            <div class="video-tab__inline">
              <SelectButton
                :pt="{ root: { id } }"
                :model-value="video.bit_depth"
                :options="depthOptions"
                option-label="label"
                option-value="value"
                option-disabled="disabled"
                :allow-empty="false"
                :disabled="passthrough"
                :ariaLabelledby="labelId"
                @update:model-value="setBitDepth"
              />
              <span v-if="tenBitNote" class="video-tab__hint" data-note="ten-bit">{{
                tenBitNote
              }}</span>
            </div>
          </template>
        </Field>
        <Field
          v-if="video.custom_params !== ''"
          :label="t('video.customParams.label')"
          path="video.custom_params"
        >
          <template #default="{ id }">
            <code :id="id" class="video-tab__params" tabindex="0">{{ video.custom_params }}</code>
          </template>
        </Field>
      </Section>

      <Section :title="t('video.sections.metadata')">
        <TrackMetadataEditor list="video" />
      </Section>

      <CommandPreview />
    </div>
  </section>
</template>

<style scoped>
.video-tab {
  min-height: 100%;
}

.video-tab__content {
  display: flex;
  flex-direction: column;
  gap: var(--rf-space-5);
  min-height: 100%;
  padding: var(--rf-space-4) var(--rf-space-4) 0;
}

/* The command drawer stays at the panel's foot while the panel scrolls. */
.video-tab__content > :last-child {
  margin-top: auto;
}

.video-tab__inline {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-3);
}

.video-tab__hint {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.video-tab__note {
  margin: 0;
  padding: var(--rf-space-2) var(--rf-space-3);
  border: 1px solid var(--p-status-info-border-color);
  border-radius: var(--rf-radius-md);
  background: var(--p-status-info-background);
  color: var(--rf-color-text);
}

.video-tab__params {
  display: block;
  padding: var(--rf-space-2);
  border-radius: var(--rf-radius-sm);
  background: var(--rf-color-bg);
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-sm);
  overflow-wrap: anywhere;
}
</style>
