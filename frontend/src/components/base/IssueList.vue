<script setup lang="ts">
import type { ValidationIssue } from '@/api/types'

/**
 * Issues, most severe first, each with its fix buttons (`editor.applyFix`) and a link to its
 * field (`ui.reveal(issue.path)`). Used by the Summary tab and the status bar.
 */
defineProps<{
  issues: ValidationIssue[]
  compact?: boolean
}>()
</script>

<template>
  <ul class="issue-list" />
</template>
