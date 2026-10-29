<script setup lang="ts">
import { Clapperboard } from '@lucide/vue'
import Message from 'primevue/message'
import { useI18n } from 'vue-i18n'

import { useValidation } from '@/composables/useValidation'
import { platform } from '@/platform'

const { t } = useI18n()

useValidation()
</script>

<template>
  <main class="workspace" :data-platform="platform.kind">
    <h1 class="workspace__title">
      <Clapperboard :size="28" aria-hidden="true" />
      {{ t('shell.workspace.title') }}
    </h1>
    <Message severity="secondary" :closable="false">{{ t('shell.workspace.placeholder') }}</Message>
  </main>
</template>

<style scoped>
.workspace {
  padding: 1.5rem;
}

.workspace__title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 1rem;
}
</style>
