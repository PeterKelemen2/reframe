import { reactive } from 'vue'

/** What the advanced panel shows, for the page: a tab switch unmounts the panel. */
export const panelView = reactive({
  /** The chosen category's id; `null` (or one the encoder lacks) shows the first category. */
  category: null as string | null,
  query: '',
  changedOnly: false,
})
