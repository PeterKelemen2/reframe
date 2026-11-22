<script setup lang="ts">
import { KeyRound } from '@lucide/vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import { computed, onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { ValidationIssue } from '@/api/types'
import Field from '@/components/base/Field.vue'
import { useSystemStore } from '@/stores/system'

const { t } = useI18n()
const system = useSystemStore()

const passwordMode = computed(() => system.auth?.mode === 'password')
const value = ref<string | undefined>('')
const busy = ref(false)
const problem = ref<string | null>(null)
const form = useTemplateRef<HTMLFormElement>('form')

onMounted(() => form.value?.querySelector('input')?.focus())

const issues = computed<ValidationIssue[]>(() =>
  problem.value === null
    ? []
    : [{ severity: 'error', code: 'auth.invalid', path: '', message: problem.value }],
)

function failure(error: unknown): string {
  if (!(error instanceof ApiError)) throw error
  const { title, detail } = error.problem
  return detail ? t('shell.login.refused', { title, detail }) : title
}

async function submit(): Promise<void> {
  if (busy.value) return
  const entered = value.value?.trim() ?? ''
  if (entered === '') {
    problem.value = t('shell.login.required')
    return
  }
  busy.value = true
  problem.value = null
  try {
    const accepted = passwordMode.value
      ? await system.login(value.value ?? '')
      : await system.loginWithToken(entered)
    if (!accepted) {
      problem.value = passwordMode.value
        ? t('shell.login.wrongPassword')
        : t('shell.login.wrongToken')
    }
  } catch (error) {
    problem.value = failure(error)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="login-screen" :data-mode="passwordMode ? 'password' : 'token'">
    <form ref="form" class="login-screen__form" novalidate @submit.prevent="submit">
      <KeyRound class="login-screen__icon" :size="36" aria-hidden="true" />
      <h1 class="login-screen__title">{{ t('shell.login.title') }}</h1>
      <p class="login-screen__intro">
        {{ passwordMode ? t('shell.login.passwordIntro') : t('shell.login.tokenIntro') }}
      </p>
      <Field
        :label="passwordMode ? t('shell.login.password') : t('shell.login.token')"
        :issues="issues"
        stacked
      >
        <template #default="{ id, invalid }">
          <InputText
            :id="id"
            v-model="value"
            class="login-screen__input"
            type="password"
            :name="passwordMode ? 'password' : 'token'"
            :autocomplete="passwordMode ? 'current-password' : 'off'"
            :invalid="invalid"
            fluid
          />
        </template>
      </Field>
      <Button
        class="login-screen__submit"
        type="submit"
        :label="t('shell.login.submit')"
        :loading="busy"
      />
    </form>
  </main>
</template>

<style scoped>
.login-screen {
  display: grid;
  min-height: 100vh;
  place-items: center;
  padding: var(--rf-space-4);
}

.login-screen__form {
  display: grid;
  gap: var(--rf-space-4);
  width: min(26rem, 100%);
  padding: var(--rf-space-5);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-lg);
  background: var(--rf-color-surface);
}

.login-screen__icon {
  color: var(--rf-color-primary);
}

.login-screen__title {
  margin: 0;
  font-size: var(--rf-font-size-xl);
}

.login-screen__intro {
  margin: 0;
  color: var(--rf-color-text-muted);
}
</style>
