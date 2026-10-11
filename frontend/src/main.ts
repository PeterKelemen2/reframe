import { createApp } from 'vue'

import App from '@/App.vue'
import { createAppRouter } from '@/router'
import { installPlugins } from '@/setup'

import '@/styles/main.css'

installPlugins(createApp(App), createAppRouter()).mount('#app')
