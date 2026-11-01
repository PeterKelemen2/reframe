import { useI18n } from 'vue-i18n'

import type { Schemas } from '@/api/types'
import { useDefaultsStore } from '@/stores/defaults'
import { useSystemStore } from '@/stores/system'

import type { Option } from './options'

type AudioEncoderDef = Schemas['AudioEncoderDef']

/** A rule's codec: an audio encoder id, or this. */
export const PASSTHRU = 'passthru'

/** The codec choices of a rule and an extra output, and the encoder a codec stands for. */
export function useCodecOptions() {
  const { t } = useI18n()
  const system = useSystemStore()
  const defaults = useDefaultsStore()

  /** The encoders this FFmpeg has, then Passthru; `current` is kept when it is missing. */
  function options(current: string): Option<string>[] {
    const encoders = Object.values(system.definitions?.audio_encoders ?? {})
      .filter(
        (encoder) =>
          encoder.id === current || system.encoderStatus(encoder.id)?.state !== 'unavailable',
      )
      .map((encoder) => ({ value: encoder.id, label: encoder.label }))
    const result = [...encoders, { value: PASSTHRU, label: t('defaults.rules.passthru') }]
    if (!result.some((option) => option.value === current)) {
      result.push({ value: current, label: current })
    }
    return result
  }

  /** A passthru rule encodes with the fallback encoder when its source does not fit. */
  function encoderOf(codec: string): AudioEncoderDef | undefined {
    const id = codec === PASSTHRU ? defaults.audio?.passthru?.fallback_encoder : codec
    return id === undefined ? undefined : system.definitions?.audio_encoders?.[id]
  }

  function label(codec: string): string {
    if (codec === PASSTHRU) return t('defaults.rules.passthru')
    return system.definitions?.audio_encoders?.[codec]?.label ?? codec
  }

  return { options, encoderOf, label }
}
