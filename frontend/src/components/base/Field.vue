<script setup lang="ts">
import { Info } from '@lucide/vue'
import Button from 'primevue/button'
import Menu from 'primevue/menu'
import Popover from 'primevue/popover'
import vTooltip from 'primevue/tooltip'
import { computed, nextTick, ref, useId, useTemplateRef, watchPostEffect } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ValidationIssue } from '@/api/types'
import { useReveal } from '@/composables/useReveal'
import { useEditorStore } from '@/stores/editor'
import { useValidationStore } from '@/stores/validation'

import { bySeverity, SEVERITY_ICON, useSeverityLabel } from './severity'
import type { FieldSlotProps } from './types'

const props = withDefaults(
  defineProps<{
    /** Already translated. */
    label: string
    /** The value's validation path (`video.encoder`): its issues show here, and `ui.reveal` finds it. */
    path?: string
    /** The ⓘ popover's text; already translated. */
    help?: string
    /** Shown instead of the validation store's issues for `path` (settings forms, the sandbox). */
    issues?: ValidationIssue[]
    /**
     * Shows the override dot without its menu (the sandbox). Without it, the dot and its menu show
     * while the edited group's shown file overrides `path`.
     */
    overridden?: boolean
    /** The label above the control instead of beside it. */
    stacked?: boolean
  }>(),
  { overridden: undefined },
)

defineSlots<{ default(props: FieldSlotProps): unknown }>()

const { t } = useI18n()
const severityLabel = useSeverityLabel()
const validation = useValidationStore()
const editor = useEditorStore()

const id = useId()
const labelId = `${id}-label`
const issuesId = `${id}-issues`
const root = useTemplateRef<HTMLElement>('root')
const helpPopover = useTemplateRef<InstanceType<typeof Popover>>('helpPopover')
const helpOpen = ref(false)
const overrideMenu = useTemplateRef<InstanceType<typeof Menu>>('overrideMenu')

function toggleHelp(event: Event): void {
  helpOpen.value = !helpOpen.value
  helpPopover.value?.toggle(event)
}

const shown = computed<ValidationIssue[]>(() => {
  if (props.issues) return bySeverity(props.issues)
  return props.path ? validation.issuesFor(props.path) : []
})
const severity = computed(() => shown.value[0]?.severity ?? null)
const slotProps = computed<FieldSlotProps>(() => ({
  id,
  labelId,
  invalid: severity.value === 'error',
  describedBy: shown.value.length > 0 ? issuesId : undefined,
}))

// Several PrimeVue controls (InputNumber, Select, ToggleSwitch) do not pass
// `aria-describedby` on to their input, so the field sets it on the element with its id.
watchPostEffect(() => {
  const { describedBy } = slotProps.value
  const control = root.value?.ownerDocument.getElementById(id)
  if (!control || !root.value?.contains(control)) return
  if (describedBy) control.setAttribute('aria-describedby', describedBy)
  else control.removeAttribute('aria-describedby')
})

useReveal(() => props.path, root)

const overrideMenuShown = computed(
  () =>
    props.overridden === undefined && props.path !== undefined && editor.overriddenAt(props.path),
)

/** The dot goes away with the override: the focus goes back to the field's control. */
async function focusControl(): Promise<void> {
  await nextTick()
  root.value
    ?.querySelector<HTMLElement>(
      '.rf-field__control :is(input, select, textarea, button, [tabindex]:not([tabindex="-1"]))',
    )
    ?.focus()
}

const overrideItems = computed(() => {
  const path = props.path as string
  const perFile = editor.perFile(path)
  return [
    {
      label: t('base.field.resetToGroup'),
      command: () => {
        editor.resetToGroup(path)
        void focusControl()
      },
    },
    {
      label: t('base.field.applyToGroup'),
      reason: perFile ? t('base.field.perFile') : null,
      disabled: perFile,
      command: async () => {
        await editor.applyToWholeGroup(path)
        await focusControl()
      },
    },
  ]
})
</script>

<template>
  <div
    ref="root"
    class="rf-field"
    :class="[
      stacked ? 'rf-field--stacked' : 'rf-field--inline',
      severity && `rf-field--${severity}`,
    ]"
    :data-path="path"
  >
    <div class="rf-field__label">
      <label :id="labelId" :for="id">{{ label }}</label>
      <span
        v-if="overridden"
        v-tooltip.top="t('base.field.overridden')"
        class="rf-field__override"
        role="img"
        :aria-label="t('base.field.overridden')"
      />
      <template v-else-if="overrideMenuShown">
        <Button
          v-tooltip.top="t('base.field.overridden')"
          class="rf-field__override-button"
          text
          rounded
          size="small"
          :aria-label="t('base.field.overrideMenu', { label })"
          aria-haspopup="menu"
          :aria-controls="`${id}-override`"
          data-action="override-menu"
          @click="overrideMenu?.toggle($event)"
        >
          <template #icon><span class="rf-field__override" aria-hidden="true" /></template>
        </Button>
        <Menu
          ref="overrideMenu"
          :pt="{ root: { id: `${id}-override` } }"
          :model="overrideItems"
          popup
        >
          <template #item="{ item, props: itemProps }">
            <a v-bind="itemProps.action" class="rf-field__override-item">
              <span>{{ item.label }}</span>
              <small v-if="item.reason" class="rf-field__override-reason">{{ item.reason }}</small>
            </a>
          </template>
        </Menu>
      </template>
      <template v-if="help">
        <Button
          class="rf-field__help"
          text
          rounded
          size="small"
          :aria-label="t('base.field.help', { label })"
          :aria-expanded="helpOpen"
          @click="toggleHelp"
        >
          <template #icon>
            <Info :size="16" aria-hidden="true" />
          </template>
        </Button>
        <Popover ref="helpPopover" @show="helpOpen = true" @hide="helpOpen = false">
          <p class="rf-field__help-text">{{ help }}</p>
        </Popover>
      </template>
    </div>
    <div class="rf-field__control">
      <slot v-bind="slotProps" />
    </div>
    <ul v-if="shown.length > 0" :id="issuesId" class="rf-field__issues">
      <li
        v-for="(issue, index) in shown"
        :key="`${issue.code}:${index}`"
        class="rf-field__issue"
        :class="`rf-field__issue--${issue.severity}`"
      >
        <component :is="SEVERITY_ICON[issue.severity]" :size="14" aria-hidden="true" />
        <span class="rf-sr-only">{{ severityLabel(issue.severity) }}: </span>
        <span>{{ issue.message }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.rf-field {
  position: relative;
  display: grid;
  gap: var(--rf-space-1) var(--rf-space-3);
  min-width: 0;
}

.rf-field--inline {
  grid-template-columns: minmax(8rem, 12rem) minmax(0, 1fr);
  align-items: center;
}

.rf-field--inline .rf-field__issues {
  grid-column: 2;
}

.rf-field--stacked {
  grid-template-columns: minmax(0, 1fr);
}

.rf-field__label {
  display: flex;
  align-items: center;
  gap: var(--rf-space-1);
  min-width: 0;
  color: var(--rf-color-text);
  font-weight: var(--rf-font-weight-medium);
}

.rf-field__help {
  width: 1.75rem;
  height: 1.75rem;
  padding: 0;
  color: var(--rf-color-text-muted);
}

.rf-field__help-text {
  max-width: 22rem;
  margin: 0;
}

.rf-field__override {
  flex: none;
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: var(--rf-color-primary);
}

.rf-field__override-button {
  width: 1.75rem;
  height: 1.75rem;
  padding: 0;
}

.rf-field__override-item {
  display: grid;
}

.rf-field__override-reason {
  max-width: 18rem;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.rf-field__control {
  min-width: 0;
}

.rf-field__issues {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--rf-font-size-sm);
}

.rf-field__issue {
  display: flex;
  align-items: flex-start;
  gap: var(--rf-space-1);
}

.rf-field__issue svg {
  flex: none;
  margin-top: 0.15em;
}

.rf-field__issue--error {
  color: var(--p-status-error-color);
}

.rf-field__issue--warning {
  color: var(--p-status-warn-color);
}

.rf-field__issue--info {
  color: var(--p-status-info-color);
}

/* A bar in the gutter marks the field whatever its control is; known controls get the outline,
   except while focused, so that the focus stays visible. */
.rf-field--error {
  --rf-field-tone: var(--p-status-error-border-color);
}

.rf-field--warning {
  --rf-field-tone: var(--p-status-warn-border-color);
}

.rf-field--error::before,
.rf-field--warning::before {
  position: absolute;
  inset-block: 0;
  inset-inline-start: calc(-1 * var(--rf-space-2));
  width: 3px;
  border-radius: 2px;
  background: var(--rf-field-tone);
  content: '';
}

.rf-field--error .rf-field__control,
.rf-field--warning .rf-field__control {
  --p-inputtext-border-color: var(--rf-field-tone);
  --p-inputtext-hover-border-color: var(--rf-field-tone);
  --p-inputtext-invalid-border-color: var(--rf-field-tone);
  --p-select-border-color: var(--rf-field-tone);
  --p-select-hover-border-color: var(--rf-field-tone);
  --p-select-invalid-border-color: var(--rf-field-tone);
  --p-multiselect-border-color: var(--rf-field-tone);
  --p-multiselect-hover-border-color: var(--rf-field-tone);
  --p-multiselect-invalid-border-color: var(--rf-field-tone);
  --p-textarea-border-color: var(--rf-field-tone);
  --p-textarea-hover-border-color: var(--rf-field-tone);
  --p-textarea-invalid-border-color: var(--rf-field-tone);
  --p-autocomplete-border-color: var(--rf-field-tone);
  --p-autocomplete-hover-border-color: var(--rf-field-tone);
  --p-autocomplete-invalid-border-color: var(--rf-field-tone);
  --p-checkbox-border-color: var(--rf-field-tone);
  --p-checkbox-hover-border-color: var(--rf-field-tone);
  --p-checkbox-invalid-border-color: var(--rf-field-tone);
  --p-radiobutton-border-color: var(--rf-field-tone);
  --p-radiobutton-hover-border-color: var(--rf-field-tone);
  --p-radiobutton-invalid-border-color: var(--rf-field-tone);
  --p-toggleswitch-border-color: var(--rf-field-tone);
  --p-toggleswitch-hover-border-color: var(--rf-field-tone);
  --p-toggleswitch-invalid-border-color: var(--rf-field-tone);
}

/* A SelectButton is one control: the outline goes round the group, checked option included. */
.rf-field--error .rf-field__control :deep(.p-selectbutton),
.rf-field--warning .rf-field__control :deep(.p-selectbutton) {
  outline: 1px solid var(--rf-field-tone);
  outline-offset: 0;
}
</style>
