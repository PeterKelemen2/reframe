import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'

import WorkspaceView from '@/views/WorkspaceView.vue'

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({
    history,
    routes: [
      { path: '/', name: 'workspace', component: WorkspaceView },
      { path: '/:pathMatch(.*)*', redirect: '/' },
    ],
  })
}
