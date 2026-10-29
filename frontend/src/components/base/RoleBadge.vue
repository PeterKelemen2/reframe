<script setup lang="ts">
import type { TrackRoleInfo } from '@/api/types'

/** Solid when a disposition flag sets the role, outlined for a title or heuristic; the tooltip names the evidence. */
defineProps<{ role: TrackRoleInfo }>()
</script>

<template>
  <span class="role-badge" />
</template>
