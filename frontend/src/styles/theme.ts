import { definePreset } from '@primeuix/themes'
import Aura from '@primeuix/themes/aura'

/**
 * Reframe's PrimeVue preset: Aura with colours that meet WCAG AA in both schemes, and the
 * app's own colour tokens (`--p-app-*`, `--p-status-*`). `contrast.test.ts` checks the pairs.
 */
export const ReframePreset = definePreset(Aura, {
  semantic: {
    primary: {
      50: '{indigo.50}',
      100: '{indigo.100}',
      200: '{indigo.200}',
      300: '{indigo.300}',
      400: '{indigo.400}',
      500: '{indigo.500}',
      600: '{indigo.600}',
      700: '{indigo.700}',
      800: '{indigo.800}',
      900: '{indigo.900}',
      950: '{indigo.950}',
    },
    focusRing: { width: '2px' },
    colorScheme: {
      light: {
        // Aura's 500 shades are below 4.5:1 for white text.
        primary: {
          color: '{primary.600}',
          contrastColor: '#ffffff',
          hoverColor: '{primary.700}',
          activeColor: '{primary.800}',
        },
        highlight: { color: '{primary.800}', focusColor: '{primary.900}' },
        text: {
          color: '{surface.800}',
          hoverColor: '{surface.900}',
          mutedColor: '{surface.600}',
          hoverMutedColor: '{surface.700}',
        },
        // Input borders need 3:1 against the field (WCAG 1.4.11).
        formField: {
          borderColor: '{surface.500}',
          hoverBorderColor: '{surface.600}',
          invalidBorderColor: '{red.600}',
          invalidPlaceholderColor: '{red.700}',
          color: '{surface.800}',
          placeholderColor: '{surface.500}',
          iconColor: '{surface.500}',
        },
        app: { background: '{surface.50}', borderColor: '{surface.200}' },
        status: {
          error: { color: '{red.700}', background: '{red.50}', borderColor: '{red.600}' },
          warn: { color: '{amber.800}', background: '{amber.50}', borderColor: '{amber.700}' },
          info: { color: '{blue.700}', background: '{blue.50}', borderColor: '{blue.600}' },
          ok: { color: '{green.700}', background: '{green.50}', borderColor: '{green.700}' },
          busy: {
            color: '{primary.600}',
            background: '{primary.50}',
            borderColor: '{primary.600}',
          },
          off: {
            color: '{surface.600}',
            background: '{surface.100}',
            borderColor: '{surface.500}',
          },
        },
      },
      dark: {
        formField: {
          borderColor: '{surface.500}',
          hoverBorderColor: '{surface.400}',
          invalidBorderColor: '{red.400}',
        },
        text: { mutedColor: '{surface.400}', hoverMutedColor: '{surface.300}' },
        app: { background: '{surface.950}', borderColor: '{surface.800}' },
        status: {
          error: { color: '{red.300}', background: '{red.950}', borderColor: '{red.400}' },
          warn: { color: '{amber.300}', background: '{amber.950}', borderColor: '{amber.400}' },
          info: { color: '{blue.300}', background: '{blue.950}', borderColor: '{blue.400}' },
          ok: { color: '{green.400}', background: '{green.950}', borderColor: '{green.500}' },
          busy: {
            color: '{primary.300}',
            background: '{primary.950}',
            borderColor: '{primary.400}',
          },
          off: {
            color: '{surface.400}',
            background: '{surface.800}',
            borderColor: '{surface.500}',
          },
        },
      },
    },
  },
})

/** CSS class on `<html>` that switches to the dark colour scheme. */
export const DARK_MODE_CLASS = 'reframe-dark'

/** `<html data-density="…">`: `tokens.css` tightens the spacing for `compact`. */
export const DENSITY_ATTRIBUTE = 'data-density'
