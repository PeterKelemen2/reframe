<script setup lang="ts">
// Stub: the current frame (view modes, zoom, the strip, seek) with its overlay layer.
import CropLoupe from '@/components/crop/CropLoupe.vue'
import CropOverlay from '@/components/dimensions/CropOverlay.vue'
</script>

<template>
  <div class="frame-viewer" data-stub="frame-viewer">
    <div class="frame-viewer__overlay">
      <CropOverlay />
      <CropLoupe />
    </div>
  </div>
</template>
