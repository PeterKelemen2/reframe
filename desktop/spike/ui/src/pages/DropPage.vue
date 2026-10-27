<script setup>
import { onMounted, ref } from "vue";

import { inTauri, log } from "../spike.js";

const shown = ref([]);
let overs = 0;

function show(record) {
  shown.value = [record, ...shown.value].slice(0, 6);
  log({ check: "drop", ...record });
}

function describeTransfer(transfer) {
  if (!transfer) return null;
  const data = (type) => {
    try {
      return transfer.getData(type);
    } catch (error) {
      return `getData threw ${error}`;
    }
  };
  return {
    types: [...transfer.types],
    files: [...transfer.files].map((file) => ({
      name: file.name,
      size: file.size,
      type: file.type,
      webkitRelativePath: file.webkitRelativePath,
    })),
    items: [...transfer.items].map((item) => ({ kind: item.kind, type: item.type })),
    uriList: data("text/uri-list"),
    plain: data("text/plain"),
    html: data("text/html"),
    dropEffect: transfer.dropEffect,
    effectAllowed: transfer.effectAllowed,
  };
}

let entered = false;

function onDom(event) {
  event.preventDefault();
  if (event.type === "dragover") {
    overs += 1;
    return;
  }
  // dragenter and dragleave fire at every element border: keep the first enter and the leave
  // out of the window.
  if (event.type === "dragenter" && entered) return;
  if (event.type === "dragleave" && event.relatedTarget !== null) return;
  entered = event.type === "dragenter";
  const record = { source: "dom", type: event.type, transfer: describeTransfer(event.dataTransfer) };
  if (event.type === "drop") {
    record.overs = overs;
    overs = 0;
  }
  show(record);
}

onMounted(async () => {
  for (const type of ["dragenter", "dragover", "dragleave", "drop"]) {
    document.addEventListener(type, onDom);
  }
  // Shows that the real pointer's buttons reach the page.
  for (const type of ["pointerdown", "pointerup"]) {
    document.addEventListener(type, (event) =>
      log({
        check: "drop",
        source: "pointer",
        type,
        x: event.screenX,
        y: event.screenY,
        client: [event.clientX, event.clientY],
        pointerType: event.pointerType,
        button: event.button,
      }),
    );
  }
  if (inTauri) {
    const { getCurrentWebview } = await import("@tauri-apps/api/webview");
    await getCurrentWebview().onDragDropEvent((event) => {
      const { type, paths, position } = event.payload;
      if (type !== "over") show({ source: "tauri", type, paths, position });
    });
  }
  log({ check: "drop", source: "page", type: "ready", inTauri });
});
</script>

<template>
  <main class="drop">
    <h1>Drop files here</h1>
    <p>Each drop is logged: Tauri's drag-drop event and the DOM's drop event.</p>
    <ol>
      <li v-for="(record, index) in shown" :key="index">
        <code>{{ record.source }} {{ record.type }}</code>
        <pre>{{ JSON.stringify(record.paths ?? record.transfer, null, 1) }}</pre>
      </li>
    </ol>
  </main>
</template>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
}
.drop {
  box-sizing: border-box;
  min-height: 100%;
  padding: 1rem 2rem;
  font-family: system-ui, sans-serif;
  border: 6px dashed #6366f1;
}
.drop pre {
  max-height: 8rem;
  overflow: auto;
  background: #f3f3f3;
  white-space: pre-wrap;
}
</style>
