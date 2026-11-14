import { createApp } from 'vue'

import { boot } from '@/api/boot'
import App from '@/App.vue'
import { installDialogFocus } from '@/components/base/dialogFocus'
import { installKeyboardFixes } from '@/components/base/keyboard'
import { installReducedMotionScrolling } from '@/components/base/motion'
import { initTheme } from '@/composables/useTheme'
import { createAppRouter } from '@/router'
import { installPlugins } from '@/setup'

import '@/styles/main.css'

initTheme()
installKeyboardFixes()
installDialogFocus()
installReducedMotionScrolling()
installPlugins(createApp(App), createAppRouter()).mount('#app')
void boot()
