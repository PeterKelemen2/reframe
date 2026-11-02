<script setup lang="ts">
import { useId } from 'vue'
import { useI18n } from 'vue-i18n'

import type { FilterDef } from '@/api/types'

/** The help panel of a filter: the definitions' text, each implementation's presets and tunes. */
defineProps<{ filter: FilterDef }>()

const { t } = useI18n()
const headingId = useId()
</script>

<template>
  <aside class="filter-help" :aria-labelledby="headingId" :data-help="filter.id">
    <h3 :id="headingId" class="filter-help__title">{{ filter.label }}</h3>
    <dl class="filter-help__text">
      <dt>{{ t('filters.help.what') }}</dt>
      <dd data-help-part="what">{{ filter.help.what }}</dd>
      <dt>{{ t('filters.help.useWhen') }}</dt>
      <dd data-help-part="use-when">{{ filter.help.use_when }}</dd>
      <dt>{{ t('filters.help.avoidWhen') }}</dt>
      <dd data-help-part="avoid-when">{{ filter.help.avoid_when }}</dd>
      <dt>{{ t('filters.help.speedCost') }}</dt>
      <dd data-help-part="speed-cost" :data-speed="filter.help.speed_cost">
        {{ t(`filters.help.speed.${filter.help.speed_cost}`) }}
      </dd>
      <dt>{{ t('filters.help.settings') }}</dt>
      <dd data-help-part="settings">{{ filter.help.settings }}</dd>
    </dl>
    <section
      v-for="implementation in filter.implementations"
      :key="implementation.id"
      class="filter-help__implementation"
      :data-implementation="implementation.id"
    >
      <h4 v-if="filter.implementations.length > 1" class="filter-help__subtitle">
        {{ implementation.label }}
      </h4>
      <p v-if="implementation.note" class="filter-help__note">{{ implementation.note }}</p>
      <dl class="filter-help__choices">
        <dt>{{ t('filters.help.presets') }}</dt>
        <dd>
          <ul>
            <li v-for="preset in implementation.presets" :key="preset.id">
              <strong>{{ preset.label }}</strong
              ><template v-if="preset.help"> · {{ preset.help }}</template>
            </li>
          </ul>
        </dd>
        <template v-if="(implementation.tunes ?? []).length > 0">
          <dt>{{ t('filters.help.tunes') }}</dt>
          <dd>
            <ul>
              <li v-for="tune in implementation.tunes" :key="tune.id">
                <strong>{{ tune.label }}</strong
                ><template v-if="tune.help"> · {{ tune.help }}</template>
              </li>
            </ul>
          </dd>
        </template>
      </dl>
    </section>
  </aside>
</template>

<style scoped>
.filter-help {
  display: grid;
  gap: var(--rf-space-3);
  padding: var(--rf-space-3);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md);
  background: var(--rf-color-surface);
}

.filter-help__title,
.filter-help__subtitle {
  margin: 0;
  color: var(--rf-color-text);
  font-size: var(--rf-font-size-lg);
  font-weight: var(--rf-font-weight-bold);
}

.filter-help__subtitle {
  font-size: var(--rf-font-size-md);
}

.filter-help__text,
.filter-help__choices {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
}

.filter-help dt {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  font-weight: var(--rf-font-weight-medium);
}

.filter-help dd {
  margin: 0 0 var(--rf-space-2);
  color: var(--rf-color-text);
}

.filter-help ul {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
  padding-inline-start: var(--rf-space-4);
}

.filter-help__implementation {
  display: grid;
  gap: var(--rf-space-2);
  padding-top: var(--rf-space-2);
  border-top: 1px solid var(--rf-color-border);
}

.filter-help__note {
  margin: 0;
  color: var(--rf-color-text);
}
</style>
