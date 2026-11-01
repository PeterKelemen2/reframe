import Button from 'primevue/button'
import { defineComponent, h, ref } from 'vue'

/**
 * PrimeVue's Button for an action that can turn unavailable while it has the focus (it runs,
 * or its own result disables it). A disabled button drops the focus to the page, so this one
 * stays focusable with `aria-disabled` until the focus leaves it. A busy state goes in
 * `disabled` too.
 */
const FocusSafeButton = defineComponent({
  name: 'FocusSafeButton',
  inheritAttrs: false,
  props: { disabled: Boolean },
  emits: { click: (_event: MouseEvent) => true },
  setup(props, { attrs, slots, emit }) {
    const focused = ref(false)
    return () =>
      h(
        Button,
        {
          ...attrs,
          disabled: props.disabled && !focused.value,
          'aria-disabled': props.disabled || undefined,
          class: [attrs.class, { 'p-disabled': props.disabled && focused.value }],
          onFocus: () => (focused.value = true),
          onBlur: () => (focused.value = false),
          onClick: (event: MouseEvent) => {
            if (!props.disabled) emit('click', event)
          },
        },
        slots,
      )
  },
})

// Templates see Button's own props.
export default FocusSafeButton as unknown as typeof Button
