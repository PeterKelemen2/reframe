<script setup lang="ts">
import { CircleCheck, CircleX, Info, LoaderCircle, TriangleAlert } from '@lucide/vue'
import Button from 'primevue/button'
import Popover from 'primevue/popover'
import { computed, ref, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import IssueList from '@/components/base/IssueList.vue'
import { useUiStore } from '@/stores/ui'
import { useValidationStore } from '@/stores/validation'

const { t } = useI18n()
const validation = useValidationStore()
const ui = useUiStore()

const id = useId()
const popover = useTemplateRef<InstanceType<typeof Popover>>('popover')
const open = ref(false)

const counts = computed(() => validation.counts)
const clean = computed(() => validation.issues.length === 0)

// "Show" in the list takes the user to the field, which the open list would cover.
watch(
  () => ui.revealed,
  (request) => {
    if (request !== null) popover.value?.hide()
  },
)
</script>

<template>
  <Button
    class="validation-summary"
    text
    size="small"
    severity="secondary"
    aria-haspopup="dialog"
    :aria-expanded="open"
    :aria-controls="open ? `${id}-list` : undefined"
    :data-pending="validation.pending || undefined"
    @click="popover?.toggle($event)"
  >
    <span v-if="clean && validation.pending" class="validation-summary__part">
      <LoaderCircle class="validation-summary__spin" :size="16" aria-hidden="true" />
      {{ t('shell.status.issues.checking') }}
    </span>
    <span v-else-if="clean" class="validation-summary__part validation-summary__part--ok">
      <CircleCheck :size="16" aria-hidden="true" />
      {{ t('shell.status.issues.none') }}
    </span>
    <template v-else>
      <span
        v-if="counts.error > 0"
        class="validation-summary__part validation-summary__part--error"
        data-severity="error"
      >
        <CircleX :size="16" aria-hidden="true" />
        {{ t('shell.status.issues.errors', counts.error) }}
      </span>
      <span
        v-if="counts.warning > 0"
        class="validation-summary__part validation-summary__part--warning"
        data-severity="warning"
      >
        <TriangleAlert :size="16" aria-hidden="true" />
        {{ t('shell.status.issues.warnings', counts.warning) }}
      </span>
      <span
        v-if="counts.info > 0"
        class="validation-summary__part validation-summary__part--info"
        data-severity="info"
      >
        <Info :size="16" aria-hidden="true" />
        {{ t('shell.status.issues.infos', counts.info) }}
      </span>
    </template>
  </Button>
  <Popover ref="popover" @show="open = true" @hide="open = false">
    <div
      :id="`${id}-list`"
      class="validation-summary__list"
      role="dialog"
      :aria-label="t('shell.status.issues.title')"
    >
      <h2 class="validation-summary__title">{{ t('shell.status.issues.title') }}</h2>
      <IssueList :issues="validation.issues" compact />
    </div>
  </Popover>
</template>

<style scoped>
.validation-summary {
  gap: var(--rf-space-3);
}

.validation-summary__part {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
  color: var(--rf-color-text);
}

.validation-summary__part--ok {
  color: var(--p-status-ok-color);
}

.validation-summary__part--error {
  color: var(--p-status-error-color);
}

.validation-summary__part--warning {
  color: var(--p-status-warn-color);
}

.validation-summary__part--info {
  color: var(--p-status-info-color);
}

.validation-summary__spin {
  animation: summary-spin 1s linear infinite;
}

.validation-summary__list {
  display: grid;
  gap: var(--rf-space-2);
  width: min(32rem, 90vw);
  max-height: 60vh;
  overflow: auto;
}

.validation-summary__title {
  margin: 0;
  font-size: var(--rf-font-size-md);
}

@keyframes summary-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
