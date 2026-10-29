import type { PrimeVueLocaleOptions } from 'primevue/config'

import type { createAppI18n } from '@/i18n'

type Translate = ReturnType<typeof createAppI18n>['global']['t']

/**
 * The texts PrimeVue's own components show or announce (empty lists, live regions, close
 * buttons), from the app's messages. PrimeVue keeps its defaults for the texts of components
 * the app does not use.
 */
export function primeVueLocale(t: Translate): Partial<PrimeVueLocaleOptions> {
  // PrimeVue puts the count where `{0}` stands, after us: the wording reads right for any count.
  const count = { count: '{0}' }
  return {
    accept: t('base.primevue.accept'),
    reject: t('base.primevue.reject'),
    emptyMessage: t('base.primevue.emptyMessage'),
    emptyFilterMessage: t('base.primevue.emptySearchMessage'),
    emptySearchMessage: t('base.primevue.emptySearchMessage'),
    emptySelectionMessage: t('base.primevue.emptySelectionMessage'),
    searchMessage: t('base.primevue.searchMessage', count),
    selectionMessage: t('base.primevue.selectionMessage', count),
    aria: {
      close: t('base.primevue.aria.close'),
      previous: t('base.primevue.aria.previous'),
      next: t('base.primevue.aria.next'),
      selectAll: t('base.primevue.aria.selectAll'),
      unselectAll: t('base.primevue.aria.unselectAll'),
      selectRow: t('base.primevue.aria.selectRow'),
      unselectRow: t('base.primevue.aria.unselectRow'),
      expandRow: t('base.primevue.aria.expandRow'),
      collapseRow: t('base.primevue.aria.collapseRow'),
    },
  }
}
