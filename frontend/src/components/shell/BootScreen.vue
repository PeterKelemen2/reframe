<script setup lang="ts">
import { CloudOff, LoaderCircle } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

/** `offline`: the server could not be reached; boot keeps trying on its own. */
defineProps<{ offline?: boolean }>()

const { t } = useI18n()
</script>

<template>
  <main class="boot-screen" :data-phase="offline ? 'offline' : 'booting'">
    <div class="boot-screen__box" role="status">
      <template v-if="offline">
        <CloudOff
          class="boot-screen__icon boot-screen__icon--offline"
          :size="40"
          aria-hidden="true"
        />
        <h1 class="boot-screen__title">{{ t('shell.boot.offline') }}</h1>
        <p class="boot-screen__text">{{ t('shell.boot.offlineDetail') }}</p>
      </template>
      <template v-else>
        <LoaderCircle
          class="boot-screen__icon boot-screen__spinner"
          :size="40"
          aria-hidden="true"
        />
        <p class="boot-screen__text">{{ t('shell.boot.connecting') }}</p>
      </template>
    </div>
  </main>
</template>

<style scoped>
.boot-screen {
  display: grid;
  min-height: 100vh;
  place-items: center;
  padding: var(--rf-space-4);
}

.boot-screen__box {
  display: grid;
  justify-items: center;
  gap: var(--rf-space-3);
  max-width: 28rem;
  text-align: center;
}

.boot-screen__icon {
  color: var(--rf-color-text-muted);
}

.boot-screen__icon--offline {
  color: var(--p-status-warn-color);
}

.boot-screen__spinner {
  animation: boot-spin 1s linear infinite;
}

.boot-screen__title {
  margin: 0;
  font-size: var(--rf-font-size-xl);
}

.boot-screen__text {
  margin: 0;
  color: var(--rf-color-text-muted);
}

@keyframes boot-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
