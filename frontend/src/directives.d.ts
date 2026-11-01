import type Tooltip from 'primevue/tooltip'

// `setup.ts` registers PrimeVue's tooltip directive for every component; this types `v-tooltip`
// in templates.
declare module 'vue' {
  interface GlobalDirectives {
    vTooltip: typeof Tooltip
  }
}
