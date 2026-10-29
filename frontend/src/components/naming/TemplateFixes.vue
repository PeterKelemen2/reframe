<script setup lang="ts">
import Button from 'primevue/button'
import { computed } from 'vue'

import type { ValidationIssue } from '@/api/types'

import { fixedTemplate } from './preview'

/**
 * The "did you mean" fixes of template issues as buttons. They put the fixed template into the
 * field being edited, wherever its value lives (a job, the naming options).
 */
const props = defineProps<{ issues: ValidationIssue[]; disabled?: boolean }>()

const emit = defineEmits<{ use: [template: string] }>()

const fixes = computed(() => {
  const seen = new Set<string>()
  const result: { label: string; template: string }[] = []
  for (const issue of props.issues) {
    for (const fix of issue.fixes ?? []) {
      const template = fixedTemplate(fix)
      if (template === null || seen.has(template)) continue
      seen.add(template)
      result.push({ label: fix.label, template })
    }
  }
  return result
})
</script>

<template>
  <div v-if="fixes.length > 0" class="naming-fixes">
    <Button
      v-for="fix in fixes"
      :key="fix.template"
      size="small"
      severity="secondary"
      outlined
      :label="fix.label"
      :disabled="disabled"
      @click="emit('use', fix.template)"
    />
  </div>
</template>

<style scoped>
.naming-fixes {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-1);
}
</style>
