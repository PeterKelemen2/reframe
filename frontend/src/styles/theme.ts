import { definePreset } from '@primeuix/themes'
import Aura from '@primeuix/themes/aura'

/** PrimeVue's coloured severities and the palette each one uses. */
const SEVERITIES = {
  info: 'sky',
  success: 'green',
  warn: 'orange',
  help: 'purple',
  danger: 'red',
} as const

function perSeverity<T>(make: (palette: string) => T): Record<keyof typeof SEVERITIES, T> {
  return Object.fromEntries(
    Object.entries(SEVERITIES).map(([severity, palette]) => [severity, make(palette)]),
  ) as Record<keyof typeof SEVERITIES, T>
}

/** A solid light button: white text needs the 700 shade; on Aura's 500 it is below 4.5:1. */
function solidLight(palette: string) {
  return {
    background: `{${palette}.700}`,
    hoverBackground: `{${palette}.800}`,
    activeBackground: `{${palette}.900}`,
    borderColor: `{${palette}.700}`,
    hoverBorderColor: `{${palette}.800}`,
    activeBorderColor: `{${palette}.900}`,
    color: '#ffffff',
    hoverColor: '#ffffff',
    activeColor: '#ffffff',
    focusRing: { color: `{${palette}.700}`, shadow: 'none' },
  }
}

/** A toast or message: an opaque tint, so that the page under a toast does not show through. */
function notice(palette: string, scheme: 'light' | 'dark') {
  return scheme === 'light'
    ? { background: `{${palette}.50}`, borderColor: `{${palette}.200}`, color: `{${palette}.700}` }
    : { background: `{${palette}.950}`, borderColor: `{${palette}.800}`, color: `{${palette}.300}` }
}

function message(palette: string, scheme: 'light' | 'dark') {
  const tone = notice(palette, scheme)
  return {
    ...tone,
    outlined: { color: tone.color, borderColor: tone.color },
    simple: { color: tone.color },
  }
}

/** Aura's yellow 600 is below 4.5:1 on its own tint: warnings use the 800 shade in light. */
const WARN_NOTICE_LIGHT = {
  background: '{yellow.50}',
  borderColor: '{yellow.200}',
  color: '{yellow.800}',
}

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
    // Aura shows a focused field by its border colour alone, 1.3:1 against the grey it replaces.
    formField: {
      focusRing: {
        width: '2px',
        style: 'solid',
        color: '{primary.color}',
        offset: '-1px',
        shadow: 'none',
      },
    },
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
  components: {
    button: {
      colorScheme: {
        light: {
          root: perSeverity(solidLight),
          outlined: {
            // An outlined button's border is its only edge: 3:1 against the surface.
            primary: { borderColor: '{primary.500}' },
            secondary: { borderColor: '{surface.500}', color: '{surface.600}' },
            ...perSeverity((palette) => ({
              borderColor: `{${palette}.600}`,
              color: `{${palette}.700}`,
            })),
            plain: { borderColor: '{surface.500}' },
          },
          text: {
            secondary: { color: '{surface.600}' },
            ...perSeverity((palette) => ({ color: `{${palette}.700}` })),
          },
        },
        dark: {
          outlined: {
            primary: { borderColor: '{primary.500}' },
            secondary: { borderColor: '{surface.500}', color: '{surface.300}' },
            ...perSeverity((palette) => ({ borderColor: `{${palette}.600}` })),
            plain: { borderColor: '{surface.500}' },
          },
          text: { secondary: { color: '{surface.300}' } },
        },
      },
    },
    toast: {
      colorScheme: {
        light: {
          info: notice('blue', 'light'),
          success: notice('green', 'light'),
          warn: WARN_NOTICE_LIGHT,
          error: notice('red', 'light'),
        },
        dark: {
          info: notice('blue', 'dark'),
          success: notice('green', 'dark'),
          warn: notice('yellow', 'dark'),
          error: notice('red', 'dark'),
        },
      },
    },
    message: {
      colorScheme: {
        light: {
          info: message('blue', 'light'),
          success: message('green', 'light'),
          warn: {
            ...WARN_NOTICE_LIGHT,
            outlined: { color: '{yellow.800}', borderColor: '{yellow.800}' },
            simple: { color: '{yellow.800}' },
          },
          error: message('red', 'light'),
        },
        dark: {
          info: message('blue', 'dark'),
          success: message('green', 'dark'),
          warn: message('yellow', 'dark'),
          error: message('red', 'dark'),
        },
      },
    },
    // A SelectButton's options: the checked one is filled with the primary colour, since a white
    // chip in a light grey group is 1.1:1.
    togglebutton: {
      colorScheme: {
        light: {
          root: { color: '{surface.600}', checkedColor: '{primary.contrast.color}' },
          content: { checkedBackground: '{primary.color}' },
          icon: { color: '{surface.600}', checkedColor: '{primary.contrast.color}' },
        },
        dark: {
          root: { checkedColor: '{primary.contrast.color}' },
          content: { checkedBackground: '{primary.color}' },
          icon: { checkedColor: '{primary.contrast.color}' },
        },
      },
    },
    toggleswitch: {
      colorScheme: {
        light: {
          root: { background: '{surface.500}', hoverBackground: '{surface.600}' },
        },
        dark: {
          root: { background: '{surface.500}', hoverBackground: '{surface.400}' },
          handle: { background: '{surface.950}', hoverBackground: '{surface.950}' },
        },
      },
    },
    slider: {
      track: { background: '{surface.500}' },
      handle: { background: '{primary.color}', hoverBackground: '{primary.hover.color}' },
    },
  },
})

/** CSS class on `<html>` that switches to the dark colour scheme. */
export const DARK_MODE_CLASS = 'reframe-dark'

/** `<html data-density="…">`: `tokens.css` tightens the spacing for `compact`. */
export const DENSITY_ATTRIBUTE = 'data-density'
