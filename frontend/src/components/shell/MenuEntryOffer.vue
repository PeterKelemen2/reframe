<script setup lang="ts">
import { useLocalStorage } from '@vueuse/core'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import Message from 'primevue/message'
import { computed, onMounted, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'

import { useFirstRun } from '@/components/shell/firstRun'
import { focusLost } from '@/components/shell/focus'
import type { DesktopMenuEntry, DesktopShell } from '@/platform/types'

/** The AppImage's one question at its first start: add Reframe to the application menu? */
const props = defineProps<{ shell: DesktopShell }>()

const { t } = useI18n()
const textId = useId()
/**
 * Set once the entry has been offered, whatever the answer. Losing it only offers the entry once
 * more, so this webview's storage is enough.
 */
const offered = useLocalStorage('reframe.menuEntry.offered', false, { writeDefaults: false })
const firstRun = useFirstRun()
const entry = ref<DesktopMenuEntry | null>(null)
const open = ref(false)
const failure = ref<string | null>(null)
const adding = ref(false)

/** After the first-run screen: one first-start question at a time. */
const visible = computed(() => open.value && !firstRun.shown.value)
const addable = computed(() => failure.value === null && entry.value?.percentInPath !== true)

onMounted(async () => {
  if (offered.value) return
  try {
    entry.value = await props.shell.menuEntry()
  } catch {
    // The preview window may not ask; the main window asks.
    return
  }
  open.value = entry.value.appimage !== null && !entry.value.added && entry.value.other === null
})

function close(): void {
  offered.value = true
  open.value = false
}

async function add(): Promise<void> {
  offered.value = true
  adding.value = true
  failure.value = null
  try {
    entry.value = await props.shell.setMenuEntry(true)
    open.value = false
  } catch (error) {
    failure.value = t('menuEntry.offer.failed', { reason: String(error) })
  } finally {
    adding.value = false
  }
}

// PrimeVue gives the focus back to where it was; with none there, it would be on no control.
function afterHide(): void {
  if (focusLost()) document.querySelector<HTMLElement>('.nav-rail [aria-current="page"]')?.focus()
}
</script>

<template>
  <Dialog
    :visible
    modal
    :header="t('menuEntry.offer.title')"
    :style="{ width: 'min(34rem, calc(100vw - 2rem))' }"
    data-dialog="menu-entry"
    :pt="{ root: { 'aria-describedby': textId } }"
    @update:visible="(shown) => shown || close()"
    @after-hide="afterHide"
  >
    <div v-if="entry?.percentInPath" :id="textId" class="menu-entry-offer__text">
      <p data-field="percent">{{ t('menuEntry.offer.percent', { file: entry.appimage }) }}</p>
    </div>
    <div v-else :id="textId" class="menu-entry-offer__text">
      <p>{{ t('menuEntry.offer.text', { file: entry?.appimage ?? '' }) }}</p>
      <p>{{ t('menuEntry.offer.later') }}</p>
    </div>
    <Message v-if="failure !== null" severity="error" :closable="false" data-field="failure">
      {{ failure }}
    </Message>
    <template #footer>
      <Button
        severity="secondary"
        text
        :label="addable ? t('menuEntry.offer.skip') : t('menuEntry.offer.close')"
        data-action="menu-entry-skip"
        @click="close"
      />
      <Button
        v-if="addable"
        :label="t('menuEntry.offer.add')"
        :loading="adding"
        data-action="menu-entry-add"
        @click="add"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.menu-entry-offer__text p {
  margin: 0 0 0.75rem;
}
</style>
