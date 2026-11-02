<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import ColourBox from '@/components/filters/ColourBox.vue'
import FilterHelp from '@/components/filters/FilterHelp.vue'
import FilterRow from '@/components/filters/FilterRow.vue'
import { filtersInOrder } from '@/components/filters/filters'
import { useCustomCheck } from '@/components/filters/useCustomCheck'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'

const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()
const checks = useCustomCheck()

const filters = computed(() => filtersInOrder(system.definitions))
const passthrough = computed(() => editor.job?.video?.passthrough === true)
const selectedId = ref<string | null>(null)
const selected = computed(
  () => filters.value.find((filter) => filter.id === selectedId.value) ?? filters.value[0] ?? null,
)
</script>

<template>
  <section class="editor-tab filters-tab" data-tab="filters">
    <p v-if="editor.job === null" class="filters-tab__empty" data-state="empty">
      {{ editor.loading ? t('filters.loading') : t('filters.noJob') }}
    </p>
    <template v-else>
      <p v-if="passthrough" class="filters-tab__note" data-note="passthrough">
        {{ t('filters.passthrough') }}
      </p>
      <div class="filters-tab__columns">
        <div class="filters-tab__list" role="group" :aria-label="t('filters.list')">
          <FilterRow
            v-for="filter in filters"
            :key="filter.id"
            :filter="filter"
            :selected="filter.id === selected?.id"
            :disabled="passthrough"
            :check="checks.of(filter.id, editor.job.filters?.[filter.id]?.custom ?? '')"
            @select="selectedId = filter.id"
            @typed="checks.changed(filter.id, $event)"
          >
            <ColourBox v-if="filter.id === 'colorspace'" :filter="filter" :disabled="passthrough" />
          </FilterRow>
        </div>
        <FilterHelp v-if="selected !== null" class="filters-tab__help" :filter="selected" />
      </div>
    </template>
  </section>
</template>

<style scoped>
.filters-tab {
  display: grid;
  gap: var(--rf-space-4);
  padding: var(--rf-space-4);
}

.filters-tab__empty {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.filters-tab__note {
  margin: 0;
  padding: var(--rf-space-2) var(--rf-space-3);
  border: 1px solid var(--p-status-info-border-color);
  border-radius: var(--rf-radius-md);
  background: var(--p-status-info-background);
  color: var(--rf-color-text);
}

.filters-tab__columns {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 22rem), 1fr));
  align-items: start;
  gap: var(--rf-space-4);
}

.filters-tab__list {
  display: grid;
  gap: var(--rf-space-1);
}

/* The help stays in view while the list scrolls past it. */
.filters-tab__help {
  position: sticky;
  top: 0;
}
</style>
