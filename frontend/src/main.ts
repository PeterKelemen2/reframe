import { createApp } from 'vue'

import { boot } from '@/api/boot'
import App from '@/App.vue'
import { installKeyboardFixes } from '@/components/base/keyboard'
import { initTheme } from '@/composables/useTheme'
import { createAppRouter } from '@/router'
import { installPlugins } from '@/setup'

import '@/styles/main.css'

initTheme()
installKeyboardFixes()
installPlugins(createApp(App), createAppRouter()).mount('#app')
void boot()
