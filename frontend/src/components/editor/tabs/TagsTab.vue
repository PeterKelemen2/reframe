<script setup lang="ts">
import Message from 'primevue/message'
import { computed, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { TagName, ValidationIssue } from '@/api/types'
import Field from '@/components/base/Field.vue'
import Section from '@/components/base/Section.vue'
import TemplateField from '@/components/naming/TemplateField.vue'
import TemplateFixes from '@/components/naming/TemplateFixes.vue'
import { TAG_NAMES, writtenValue } from '@/components/tags/tags'
import { useRenderedTags } from '@/components/tags/useRenderedTags'
import { useReveal } from '@/composables/useReveal'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'
import { useValidationStore } from '@/stores/validation'

// Reads and writes the editor store; takes no props.
const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()
const validation = useValidationStore()
const { tags: rendered, failure, pending } = useRenderedTags()

const root = useTemplateRef<HTMLElement>('root')
useReveal('tags', root)

const passthru = computed(() => editor.job?.output?.passthru_metadata === true)

function valueOf(name: TagName): string {
  return editor.job?.tags?.[name] ?? ''
}

function setTag(name: TagName, value: string): void {
  editor.set(`/tags/${name}`, value === '' ? null : value, { coalesce: `tags.${name}` })
}

/** `inputId`: the tag's field, which gets the focus that the fix's button loses with its issue. */
function useFix(name: TagName, template: string, inputId: string): void {
  editor.endCoalescing()
  editor.set(`/tags/${name}`, template)
  root.value?.ownerDocument.getElementById(inputId)?.focus()
}

/**
 * The validation's issues, and those of `jobs/tags` with a code the validation does not report
 * here: the status bar and the Issues card count the validation's, at its severity.
 */
function issuesOf(name: TagName): ValidationIssue[] {
  const path = `tags.${name}`
  const validated = validation.issuesFor(path)
  const codes = new Set(validated.map((issue) => issue.code))
  const rendering = (rendered.value?.issues ?? []).filter(
    (issue) => issue.path === path && !codes.has(issue.code),
  )
  return [...validated, ...rendering]
}

function written(name: TagName): { text: string; state: string } {
  const value = writtenValue(rendered.value, name, passthru.value)
  switch (value.kind) {
    case 'unknown':
      return { text: t('tags.written.unknown'), state: 'unknown' }
    case 'value':
      return { text: value.text === '' ? t('tags.written.empty') : value.text, state: 'value' }
    case 'copied':
      return { text: t('tags.written.copied', { value: value.text }), state: 'copied' }
    case 'none':
      return { text: t('tags.written.none'), state: 'none' }
  }
}

function sourceText(name: TagName): string {
  if (rendered.value === null) return t('tags.written.unknown')
  return rendered.value.source[name] ?? t('tags.source.none')
}
</script>

<template>
  <section ref="root" class="editor-tab tags-tab" data-tab="tags">
    <p v-if="editor.job === null" class="tags-tab__empty" data-state="empty">
      {{ editor.loading ? t('tags.loading') : t('tags.noJob') }}
    </p>
    <Section v-else :title="t('tags.title')">
      <p class="tags-tab__intro">{{ t('tags.intro') }}</p>
      <Message v-if="passthru" severity="info" data-note="passthru">
        {{ t('tags.passthru') }}
      </Message>
      <p v-if="failure !== null" class="tags-tab__failure" role="alert" data-state="failed">
        {{ t('tags.failed', { reason: failure }) }}
      </p>
      <div class="tags-tab__fields" :aria-busy="pending">
        <Field
          v-for="name in TAG_NAMES"
          :key="name"
          :label="t(`tags.name.${name}`)"
          :path="`tags.${name}`"
          :issues="issuesOf(name)"
          stacked
        >
          <template #default="{ id, invalid }">
            <div class="tags-tab__tag" :data-tag="name">
              <TemplateField
                :id="id"
                :model-value="valueOf(name)"
                :variables="system.namingVariables"
                :invalid="invalid"
                @update:model-value="setTag(name, $event)"
                @blur="editor.endCoalescing()"
              />
              <TemplateFixes :issues="issuesOf(name)" @use="useFix(name, $event, id)" />
              <dl class="tags-tab__values" :class="{ 'tags-tab__values--pending': pending }">
                <div class="tags-tab__value">
                  <dt>{{ t('tags.written.label') }}</dt>
                  <dd data-field="written" :data-state="written(name).state">
                    {{ written(name).text }}
                  </dd>
                </div>
                <div class="tags-tab__value">
                  <dt>{{ t('tags.source.label') }}</dt>
                  <dd data-field="source">{{ sourceText(name) }}</dd>
                </div>
              </dl>
            </div>
          </template>
        </Field>
      </div>
    </Section>
  </section>
</template>

<style scoped>
.tags-tab {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--rf-space-5);
  padding: var(--rf-space-4);
}

.tags-tab__empty,
.tags-tab__intro {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.tags-tab__failure {
  margin: 0;
  color: var(--p-status-error-color);
}

.tags-tab__fields {
  display: grid;
  gap: var(--rf-space-4);
}

.tags-tab__tag {
  display: grid;
  gap: var(--rf-space-1);
}

.tags-tab__values {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: var(--rf-space-1) var(--rf-space-4);
  margin: 0;
  font-size: var(--rf-font-size-sm);
}

/* Muted, not faded: the values keep an AA contrast while a newer answer is on its way. */
.tags-tab__values--pending dd {
  color: var(--rf-color-text-muted);
  transition: color var(--rf-duration) ease;
}

.tags-tab__value {
  display: flex;
  gap: var(--rf-space-2);
  min-width: 0;
}

.tags-tab__value dt {
  flex: none;
  color: var(--rf-color-text-muted);
}

.tags-tab__value dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}

.tags-tab__value dd[data-state='none'],
.tags-tab__value dd[data-state='unknown'] {
  color: var(--rf-color-text-muted);
}
</style>
