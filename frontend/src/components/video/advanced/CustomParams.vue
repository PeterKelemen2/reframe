<script setup lang="ts">
import InputText from 'primevue/inputtext'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ValidationIssue } from '@/api/types'
import Field from '@/components/base/Field.vue'
import { useEditorStore } from '@/stores/editor'
import { useValidationStore } from '@/stores/validation'

import { useParamsCheck } from './useParamsCheck'

const PATH = 'video.custom_params'

const { t } = useI18n()
const editor = useEditorStore()
const validation = useValidationStore()
const check = useParamsCheck()

const text = computed(() => editor.job?.video?.custom_params ?? '')
const passthrough = computed(() => editor.job?.video?.passthrough === true)

const failedText = computed(() =>
  check.value?.state === 'failed' ? t('params.check.failed', { reason: check.value.reason }) : '',
)
const checkState = computed(() => {
  const current = check.value
  if (current?.state !== 'done') return current?.state
  return current.issues.length > 0 ? 'refused' : 'accepted'
})

const issues = computed<ValidationIssue[]>(() => {
  const own = validation.issuesFor(PATH)
  const current = check.value
  if (current?.state === 'failed') {
    const message = failedText.value
    return [...own, { severity: 'warning', code: 'params.check_failed', path: PATH, message }]
  }
  if (current?.state !== 'done') return own
  // The dry run repeats validation's file rule.
  const known = new Set(own.map((issue) => `${issue.code}:${issue.message}`))
  return [...own, ...current.issues.filter((issue) => !known.has(`${issue.code}:${issue.message}`))]
})

function setText(value: string | undefined): void {
  editor.set('/video/custom_params', value ?? '', { coalesce: PATH })
}
</script>

<template>
  <Field class="custom-params" :label="t('params.label')" :path="PATH" :issues="issues" stacked>
    <template #default="{ id, invalid }">
      <InputText
        :id="id"
        class="custom-params__input"
        :model-value="text"
        :placeholder="t('params.placeholder')"
        :invalid="invalid"
        :disabled="passthrough"
        spellcheck="false"
        autocomplete="off"
        fluid
        @update:model-value="setText"
        @blur="editor.endCoalescing()"
      />
      <!-- Not Field's ⓘ: a reveal focuses the field's first button, and it must reach the text. -->
      <p class="custom-params__hint">{{ t('params.help') }}</p>
      <!-- Always there: a live region added together with its text is not announced. The
           field shows the answer's issues, so the region says them to a screen reader only. -->
      <p class="custom-params__check" role="status" :data-check="checkState">
        <template v-if="check?.state === 'done' && check.issues.length > 0">
          <span v-for="(item, index) in check.issues" :key="index" class="rf-sr-only">
            {{ item.message }}
          </span>
        </template>
        <span v-else-if="check?.state === 'failed'" class="rf-sr-only">{{ failedText }}</span>
        <span v-else-if="check" class="custom-params__check-text">
          {{ check.state === 'checking' ? t('params.check.checking') : t('params.check.accepted') }}
        </span>
      </p>
    </template>
  </Field>
</template>

<style scoped>
.custom-params__input {
  font-family: var(--rf-font-mono);
}

.custom-params__hint,
.custom-params__check-text {
  display: block;
  margin: var(--rf-space-1) 0 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.custom-params__check {
  margin: 0;
}
</style>
