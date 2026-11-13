<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import Card from '@/components/base/Card.vue'
import KeyValue from '@/components/base/KeyValue.vue'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'

import SummaryLink from './SummaryLink.vue'

const { t, n } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()

const video = computed(() => editor.job?.video ?? null)
const encoder = computed(() => {
  const id = video.value?.encoder
  return id === undefined ? null : (system.definitions?.video_encoders?.[id] ?? null)
})
const encoderLabel = computed(() => encoder.value?.label ?? video.value?.encoder ?? '')

const quality = computed(() => {
  const control = video.value?.rate_control
  if (control === undefined) return ''
  if (control.mode === 'bitrate') {
    const kbps = n(control.kbps)
    if (!control.two_pass) return t('summary.video.bitrate', { kbps })
    return control.turbo_first_pass
      ? t('summary.video.bitrateTwoPassTurbo', { kbps })
      : t('summary.video.bitrateTwoPass', { kbps })
  }
  const scale = encoder.value?.rate_control?.quality?.label
  const value = n(control.value, { maximumFractionDigits: 3 })
  return t('summary.video.quality', {
    value: scale ? t('video.quality.valueText', { scale, value }) : value,
  })
})

const speed = computed(() => {
  const preset = video.value?.preset
  if (preset === null || preset === undefined) return t('summary.video.encoderDefault')
  return encoder.value?.presets?.choices.find((choice) => choice.value === preset)?.label ?? preset
})

const advanced = computed(() => Object.keys(video.value?.advanced ?? {}).length)
</script>

<template>
  <Card class="summary-card summary-video" :title="t('summary.video.title')" data-card="video">
    <template v-if="video">
      <SummaryLink v-if="video.passthrough" path="video.passthrough">
        <span data-field="passthrough">{{ t('summary.video.passthrough') }}</span>
      </SummaryLink>
      <dl v-else class="rf-kv-list">
        <KeyValue :label="t('summary.video.encoder')">
          <SummaryLink path="video.encoder">
            <span data-field="encoder">{{ encoderLabel }}</span>
          </SummaryLink>
        </KeyValue>
        <KeyValue :label="t('summary.video.rateControl')">
          <SummaryLink path="video.rate_control">
            <span data-field="quality">{{ quality }}</span>
          </SummaryLink>
        </KeyValue>
        <KeyValue :label="t('summary.video.speed')">
          <SummaryLink path="video.preset">
            <span data-field="speed">{{ speed }}</span>
          </SummaryLink>
        </KeyValue>
        <KeyValue :label="t('summary.video.bitDepth')">
          <SummaryLink path="video.bit_depth">
            <span data-field="bit-depth">{{
              t('summary.video.bits', { bits: video.bit_depth })
            }}</span>
          </SummaryLink>
        </KeyValue>
        <KeyValue :label="t('summary.video.advanced')">
          <SummaryLink path="video.advanced">
            <span data-field="advanced">{{ t('summary.video.changed', advanced) }}</span>
          </SummaryLink>
        </KeyValue>
      </dl>
    </template>
  </Card>
</template>
