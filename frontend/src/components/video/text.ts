import { useI18n } from 'vue-i18n'

import type { EncoderAvailability } from './encoders'

/** An encoder's status as one line: "Available", "Unavailable: NVIDIA driver not found", … */
export function useAvailabilityText(): (availability: EncoderAvailability) => string {
  const { t } = useI18n()
  return ({ kind, reason }) => {
    switch (kind) {
      case 'available':
        return t('video.status.available')
      case 'checking':
        return t('video.status.checking')
      case 'rechecking':
        return reason === null
          ? t('video.status.checking')
          : t('video.status.rechecking', { reason })
      case 'untested':
        // The server's reason already starts with "Not tested".
        return reason ?? t('video.status.untested')
      case 'unavailable':
        return reason === null
          ? t('video.status.unavailable')
          : t('video.status.unavailableBecause', { reason })
      case 'failed':
        return reason === null
          ? t('video.status.failed')
          : t('video.status.failedBecause', { reason })
      case 'unknown':
        return t('video.status.unknown')
    }
  }
}
