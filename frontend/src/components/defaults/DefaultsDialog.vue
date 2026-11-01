<script setup lang="ts">
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import Section from '@/components/base/Section.vue'
import PresetNameDialog, {
  type PresetDetailsInput,
} from '@/components/presets/PresetNameDialog.vue'
import { useDefaultsStore } from '@/stores/defaults'

import CodecRuleTable from './CodecRuleTable.vue'
import DefaultsPreview from './DefaultsPreview.vue'
import PassthruForm from './PassthruForm.vue'
import SelectionForm from './SelectionForm.vue'
import SubtitleOptions from './SubtitleOptions.vue'

// The audio or subtitle defaults dialog with its live preview; opened through the defaults
// store, mounted once by `App.vue`.
const { t } = useI18n()
const defaults = useDefaultsStore()

const confirming = ref(false)
const naming = ref(false)

const audio = computed(() => defaults.kind === 'audio')
const ready = computed(() => defaults.audio !== null && defaults.subtitles !== null)
const job = computed(() => defaults.target?.kind === 'job')
const presetName = computed(() => defaults.preset?.name ?? '')
const builtIn = computed(() => defaults.preset?.built_in === true)

const title = computed(() => {
  const what = audio.value ? t('defaults.title.audio') : t('defaults.title.subtitles')
  return presetName.value === '' ? what : t('defaults.title.of', { what, name: presetName.value })
})

const whose = computed(() => {
  const name = presetName.value
  if (job.value) {
    const list = audio.value ? t('defaults.whose.audioTracks') : t('defaults.whose.subtitleTracks')
    return builtIn.value
      ? t('defaults.whose.jobBuiltIn', { name, list })
      : t('defaults.whose.job', { name, list })
  }
  return builtIn.value
    ? t('defaults.whose.builtIn', { name })
    : t('defaults.whose.preset', { name })
})

const newPreset = computed<PresetDetailsInput>(() => ({
  name: t('defaults.save.newName', { name: presetName.value }),
  category: 'Custom',
  description: '',
}))

function onVisible(open: boolean): void {
  if (!open) defaults.close()
}

/** Escape closes this dialog only when it is pressed in it: the dialogs it opens get their own. */
function onKey(event: KeyboardEvent): void {
  if (event.key !== 'Escape' || event.defaultPrevented) return
  event.stopPropagation()
  defaults.close()
}

function onConfirmKey(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  event.stopPropagation()
  confirming.value = false
}

async function confirmSave(): Promise<void> {
  confirming.value = false
  await defaults.save()
}

async function saveAsNew(details: PresetDetailsInput): Promise<void> {
  await defaults.saveAsNew(details)
}
</script>

<template>
  <Dialog
    :visible="defaults.visible"
    modal
    :header="title"
    class="defaults-dialog"
    :style="{ width: 'min(84rem, calc(100vw - 2rem))', height: 'min(60rem, calc(100vh - 2rem))' }"
    :draggable="false"
    :close-on-escape="false"
    :pt="{
      root: { onKeydown: onKey, 'data-kind': defaults.kind },
      content: { class: 'defaults-dialog__content' },
    }"
    @update:visible="onVisible"
  >
    <template v-if="ready">
      <p class="defaults-dialog__whose" data-role="whose">{{ whose }}</p>
      <div class="defaults-dialog__edit" data-role="edit">
        <Section :title="t('defaults.selection.title')">
          <SelectionForm />
        </Section>
        <template v-if="audio">
          <Section :title="t('defaults.rules.title')">
            <p class="defaults-dialog__hint">{{ t('defaults.rules.intro') }}</p>
            <CodecRuleTable />
          </Section>
          <Section :title="t('defaults.passthru.title')">
            <PassthruForm />
          </Section>
        </template>
        <Section v-else :title="t('defaults.subtitles.title')">
          <SubtitleOptions />
        </Section>
      </div>
      <DefaultsPreview class="defaults-dialog__preview" />
    </template>
    <template #footer>
      <div class="defaults-dialog__footer">
        <template v-if="defaults.readOnly">
          <Button
            :label="t('defaults.actions.close')"
            data-action="close"
            @click="defaults.close()"
          />
        </template>
        <template v-else>
          <Button
            :label="t('defaults.actions.cancel')"
            severity="secondary"
            text
            data-action="cancel"
            @click="defaults.close()"
          />
          <template v-if="job">
            <Button
              v-if="builtIn"
              :label="t('defaults.actions.saveAsNew')"
              severity="secondary"
              outlined
              aria-haspopup="dialog"
              data-action="save-as-new"
              :disabled="defaults.busy"
              @click="naming = true"
            />
            <Button
              v-else
              :label="t('defaults.actions.saveToPreset')"
              severity="secondary"
              outlined
              aria-haspopup="dialog"
              data-action="save-to-preset"
              :disabled="defaults.busy || defaults.preset === null"
              @click="confirming = true"
            />
            <Button
              :label="t('defaults.actions.apply')"
              data-action="apply"
              :loading="defaults.busy"
              @click="defaults.apply()"
            />
          </template>
          <Button
            v-else
            :label="t('defaults.actions.save')"
            data-action="save"
            :loading="defaults.busy"
            :disabled="!defaults.changed"
            @click="defaults.save()"
          />
        </template>
      </div>
    </template>
  </Dialog>
  <Dialog
    v-model:visible="confirming"
    modal
    :header="t('defaults.confirm.title', { name: presetName })"
    class="defaults-confirm"
    :style="{ width: 'min(30rem, calc(100vw - 2rem))' }"
    :draggable="false"
    :close-on-escape="false"
    :pt="{ root: { onKeydown: onConfirmKey } }"
  >
    <p class="defaults-confirm__text">
      {{
        audio
          ? t('defaults.confirm.audio', { name: presetName })
          : t('defaults.confirm.subtitles', { name: presetName })
      }}
    </p>
    <template #footer>
      <Button
        :label="t('defaults.actions.cancel')"
        severity="secondary"
        text
        @click="confirming = false"
      />
      <Button
        :label="t('defaults.actions.save')"
        autofocus
        data-action="confirm-save"
        @click="confirmSave"
      />
    </template>
  </Dialog>
  <PresetNameDialog
    v-if="naming"
    v-model:visible="naming"
    :title="t('defaults.save.newTitle')"
    :submit-label="t('defaults.actions.save')"
    :initial="newPreset"
    :save="saveAsNew"
  />
</template>

<style scoped>
.defaults-dialog__whose,
.defaults-dialog__hint {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.defaults-dialog__hint {
  margin-bottom: var(--rf-space-2);
  font-size: var(--rf-font-size-sm);
}

.defaults-dialog__edit {
  display: grid;
  flex: 1 1 0;
  gap: var(--rf-space-4);
  align-content: start;
  min-height: 8rem;
  padding-inline-end: var(--rf-space-2);
  overflow: auto;
}

.defaults-dialog__preview {
  flex: 0 0 auto;
  max-height: 50%;
  padding-top: var(--rf-space-3);
  border-top: 1px solid var(--rf-color-border);
  overflow: auto;
}

.defaults-dialog__footer {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--rf-space-2);
}

.defaults-confirm__text {
  margin: 0;
}
</style>

<style>
/* The dialog's content is teleported out of this component's scope. */
.defaults-dialog__content {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--rf-space-3);
  min-height: 0;
  overflow: hidden;
}
</style>
