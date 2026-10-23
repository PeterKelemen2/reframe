<script setup>
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { nextTick, onMounted, ref } from "vue";

const status = ref("starting");
const error = ref(null);
const baseUrl = ref(null);
const health = ref(null);
// Milliseconds since the page's navigation started (performance.now()).
const times = ref({});

function mark(name) {
  times.value[name] = Math.round(performance.now());
}

async function fail(message) {
  status.value = "failed";
  error.value = message;
  await nextTick();
  invoke("page_failed", { message });
}

onMounted(async () => {
  mark("mounted");
  await listen("sidecar-ended", (event) => fail(event.payload));
  let info;
  try {
    info = await invoke("backend_info");
  } catch (message) {
    fail(String(message));
    return;
  }
  mark("backend_info");
  baseUrl.value = info.baseUrl;
  try {
    const response = await fetch(`${info.baseUrl}/api/health`);
    health.value = await response.json();
  } catch (exc) {
    fail(`GET /api/health failed: ${exc}`);
    return;
  }
  status.value = "ready";
  await nextTick();
  // The next frame is the first one that shows the answer.
  requestAnimationFrame(() => {
    mark("health_shown");
    invoke("page_ready", { origin: window.location.origin, times: times.value });
  });
});
</script>

<template>
  <main>
    <h1>Reframe spike</h1>
    <p v-if="status === 'starting'">Starting the server…</p>
    <section v-else-if="status === 'failed'" class="error">
      <h2>The server is not running</h2>
      <pre>{{ error }}</pre>
    </section>
    <section v-else>
      <p>Server: <code>{{ baseUrl }}</code></p>
      <h2>GET /api/health</h2>
      <pre id="health">{{ JSON.stringify(health, null, 2) }}</pre>
    </section>
    <h2>Page times (ms)</h2>
    <pre>{{ JSON.stringify(times, null, 2) }}</pre>
  </main>
</template>

<style>
body {
  font-family: system-ui, sans-serif;
  margin: 2rem;
}
.error {
  color: #a40000;
}
pre {
  background: #f3f3f3;
  padding: 0.75rem;
  white-space: pre-wrap;
}
</style>
