import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import ConfirmationService from 'primevue/confirmationservice'
import ToastService from 'primevue/toastservice'
import Tooltip from 'primevue/tooltip'
import type { App } from 'vue'
import type { Router } from 'vue-router'

import { createAppI18n } from '@/i18n'
import { DARK_MODE_CLASS, ReframePreset } from '@/styles/theme'

export function installPlugins(app: App, router: Router): App {
  return app
    .use(createPinia())
    .use(router)
    .use(createAppI18n())
    .use(PrimeVue, {
      theme: {
        preset: ReframePreset,
        options: {
          darkModeSelector: `.${DARK_MODE_CLASS}`,
        },
      },
    })
    .use(ToastService)
    .use(ConfirmationService)
    .directive('tooltip', Tooltip)
}
