<script setup lang="ts">
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import Dialog from 'primevue/dialog'
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { TemplateSection } from '@/api/types'
import { useEditorStore } from '@/stores/editor'
import { useToastStore } from '@/stores/toasts'

import { SECTIONS } from './clipboard'

/** *Apply to group…*: the checked sections of the open job go into the group's template. */
const props = defineProps<{ groupId: string; groupName: string }>()

const visible = defineModel<boolean>('visible', { required: true })
const emit = defineEmits<{ closed: [] }>()

const { t, locale } = useI18n()
const editor = useEditorStore()
const toasts = useToastStore()
const id = useId()

const chosen = ref<TemplateSection[]>([])
const busy = ref(false)

watch(visible, (shown) => {
  if (shown) chosen.value = []
})

const canApply = computed(() => chosen.value.length > 0 && !busy.value)

async function apply(): Promise<void> {
  const target = editor.target
  if (!canApply.value || target?.kind !== 'job') return
  const sections = SECTIONS.filter((section) => chosen.value.includes(section))
  busy.value = true
  try {
    await editor.mergeIntoGroup(props.groupId, target.job, target.sourceId, sections)
  } catch (error) {
    // The request's problem is a toast already; the dialog stays for another try.
    if (!(error instanceof ApiError)) throw error
    return
  } finally {
    busy.value = false
  }
  const names = sections.map((section) => t(`group.sections.${section}`))
  toasts.push({
    severity: 'success',
    summary: t('group.apply.applied', {
      name: props.groupName,
      sections: new Intl.ListFormat(locale.value, { type: 'conjunction' }).format(names),
    }),
    life: 5000,
  })
  visible.value = false
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    class="apply-to-group"
    :header="t('group.apply.title', { name: groupName })"
    :style="{ width: 'min(30rem, calc(100vw - 2rem))' }"
    data-dialog="apply-to-group"
    @after-hide="emit('closed')"
  >
    <form :id="`${id}-form`" class="apply-to-group__body" @submit.prevent="apply">
      <p class="apply-to-group__intro">{{ t('group.apply.intro') }}</p>
      <fieldset class="apply-to-group__sections">
        <legend class="rf-sr-only">{{ t('group.apply.sections') }}</legend>
        <div
          v-for="section in SECTIONS"
          :key="section"
          class="apply-to-group__section"
          :data-section="section"
        >
          <Checkbox v-model="chosen" :input-id="`${id}-${section}`" :value="section" />
          <label :for="`${id}-${section}`">{{ t(`group.sections.${section}`) }}</label>
        </div>
      </fieldset>
    </form>
    <template #footer>
      <Button
        severity="secondary"
        text
        :label="t('group.apply.cancel')"
        data-action="apply-cancel"
        @click="visible = false"
      />
      <Button
        type="submit"
        :form="`${id}-form`"
        :label="t('group.apply.apply')"
        :disabled="!canApply"
        :loading="busy"
        data-action="apply"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.apply-to-group__body {
  display: grid;
  gap: var(--rf-space-3);
}

.apply-to-group__intro {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.apply-to-group__sections {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr));
  gap: var(--rf-space-2) var(--rf-space-4);
  margin: 0;
  padding: 0;
  border: 0;
}

.apply-to-group__section {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}
</style>
