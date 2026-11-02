<script setup lang="ts">
import { RotateCcw } from '@lucide/vue'
import Button from 'primevue/button'
import vTooltip from 'primevue/tooltip'
import { useI18n } from 'vue-i18n'

/** ↺ of one advanced option. */
defineProps<{ label: string; disabled: boolean }>()
const emit = defineEmits<{ click: [] }>()

const { t } = useI18n()
</script>

<template>
  <Button
    v-tooltip.top="t('advanced.reset', { label })"
    class="advanced-reset"
    text
    rounded
    size="small"
    :disabled="disabled"
    :aria-label="t('advanced.reset', { label })"
    data-action="reset"
    @click="emit('click')"
  >
    <template #icon><RotateCcw :size="16" aria-hidden="true" /></template>
  </Button>
</template>

<style scoped>
.advanced-reset {
  flex: none;
  width: 1.75rem;
  height: 1.75rem;
  padding: 0;
}
</style>
