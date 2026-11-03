import { createRouter, createWebHistory, type RouteRecordRaw, type RouterHistory } from 'vue-router'

import WorkspaceView from '@/views/WorkspaceView.vue'

/** The component sandbox of the design system; the production build leaves it out. */
const devRoutes: RouteRecordRaw[] = import.meta.env.DEV
  ? [{ path: '/sandbox', name: 'sandbox', component: () => import('@/views/SandboxView.vue') }]
  : []

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({
    history,
    routes: [
      { path: '/', name: 'workspace', component: WorkspaceView },
      { path: '/queue', name: 'queue', component: () => import('@/views/QueueView.vue') },
      { path: '/presets', name: 'presets', component: () => import('@/views/PresetsView.vue') },
      { path: '/activity', name: 'activity', component: () => import('@/views/ActivityView.vue') },
      { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
      {
        // The desktop app's detached preview window: the view alone, without the app shell.
        path: '/preview/:sourceId',
        name: 'preview-window',
        component: () => import('@/views/PreviewWindowView.vue'),
        meta: { bare: true },
      },
      ...devRoutes,
      { path: '/:pathMatch(.*)*', redirect: '/' },
    ],
  })
}
