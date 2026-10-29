<script setup lang="ts">
import { useId } from 'vue'

import type { ValidationIssue } from '@/api/types'

import type { FieldSlotProps } from './types'

defineProps<{
  /** Already translated. */
  label: string
  /** The value's validation path (`video.encoder`): its issues show here, and `ui.reveal` finds it. */
  path?: string
  /** The ⓘ popover's text; already translated. */
  help?: string
  /** Shown instead of the validation store's issues for `path` (settings forms, the sandbox). */
  issues?: ValidationIssue[]
  /** The value differs from the batch group's (the override dot; M7). */
  overridden?: boolean
  /** The label above the control instead of beside it. */
  stacked?: boolean
}>()

defineSlots<{ default(props: FieldSlotProps): unknown }>()

const id = useId()
</script>

<template>
  <div class="field">
    <label :for="id">{{ label }}</label>
    <slot :id="id" :invalid="false" :described-by="undefined" />
  </div>
</template>
