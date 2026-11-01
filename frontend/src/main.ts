import { createApp } from 'vue'

import { boot } from '@/api/boot'
import App from '@/App.vue'
import { initTheme } from '@/composables/useTheme'
import { createAppRouter } from '@/router'
import { installPlugins } from '@/setup'

import '@/styles/main.css'

initTheme()
installPlugins(createApp(App), createAppRouter()).mount('#app')
void boot()
