import { createApp } from "vue";

import App from "./App.vue";
import { pageName } from "./spike.js";

const pages = import.meta.glob("./pages/*Page.vue");

async function mountPage(name) {
  const file = `./pages/${name[0].toUpperCase()}${name.slice(1)}Page.vue`;
  const load = pages[file];
  if (!load) {
    const known = Object.keys(pages).map((path) => path.slice(8, -8).toLowerCase());
    document.body.textContent = `No spike page "${name}". Pages: ${known.join(", ")}`;
    return;
  }
  const page = await load();
  const app = createApp(page.default);
  // A page that needs plugins (PrimeVue) exports install(app) from a plain <script> block.
  page.install?.(app);
  app.mount("#app");
}

const name = pageName();
if (name) {
  mountPage(name);
} else {
  createApp(App).mount("#app");
}
