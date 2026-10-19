import { definePreset } from '@primeuix/themes'
import Aura from '@primeuix/themes/aura'

/** Reframe's PrimeVue preset: Aura with our own tokens on top (styled mode). */
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
  },
})

/** CSS class on `<html>` that switches to the dark colour scheme. */
export const DARK_MODE_CLASS = 'reframe-dark'
