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

function neutralMessage(scheme: 'light' | 'dark') {
  const tone =
    scheme === 'light'
      ? { background: '{surface.50}', borderColor: '{surface.300}', color: '{surface.800}' }
      : { background: '{surface.800}', borderColor: '{surface.600}', color: '{surface.100}' }
  return {
    ...tone,
    outlined: { color: tone.color, borderColor: '{surface.500}' },
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
 * The light scheme's neutrals: cool greys up to carbon ink. They are the primary palette too: the
 * primary action is ink on paper, not a hue.
 */
const INK = {
  0: '#ffffff',
  50: '#f7f8fa',
  100: '#eef0f3',
  200: '#e3e6eb',
  300: '#cdd2da',
  400: '#9aa3b2',
  500: '#677080',
  600: '#5b6474',
  700: '#434b59',
  800: '#2c3442',
  900: '#1b2330',
  950: '#12161e',
}

/** The dark scheme's neutrals: blue-black panels; 950 is the preview's darker surround. */
const BOOTH = {
  0: '#ffffff',
  50: '#f1f3f6',
  100: '#e4e7ec',
  200: '#d0d5dd',
  300: '#b4bbc6',
  400: '#98a1b0',
  500: '#6e7787',
  600: '#4e5664',
  700: '#343b47',
  800: '#232934',
  900: '#171b22',
  950: '#0d1014',
}

/**
 * Language colours, one per slot (`languageColor.ts` gives each language its slot). No red or
 * amber family: those colours mean a problem. Each is at least 3:1 on its scheme's surfaces.
 */
const LANGUAGE_LIGHT = {
  1: '#1f8a6b',
  2: '#2e5bba',
  3: '#7a4fb5',
  4: '#0f7c8c',
  5: '#a23c8c',
  6: '#5e7d1e',
  7: '#4f6b8a',
  8: '#4f4fb0',
  und: '#848d9c',
}

const LANGUAGE_DARK = {
  1: '#4db894',
  2: '#7a9eea',
  3: '#a98be0',
  4: '#45b5c4',
  5: '#d57ec0',
  6: '#9bbf5a',
  7: '#8fa8c4',
  8: '#9a9cf0',
  und: '#7c8595',
}

/**
 * Reframe's PrimeVue preset: Aura's components in Reframe's own colours (ink and paper, the
 * language colours), meeting WCAG AA in both schemes, plus the app's colour tokens (`--p-app-*`,
 * `--p-status-*`, `--p-language-*`). `contrast.test.ts` checks the pairs.
 */
export const ReframePreset = definePreset(Aura, {
  semantic: {
    primary: INK,
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
        surface: INK,
        primary: {
          color: '{primary.900}',
          contrastColor: '#ffffff',
          hoverColor: '{primary.800}',
          activeColor: '{primary.950}',
        },
        highlight: {
          background: '{primary.100}',
          focusBackground: '{primary.200}',
          color: '{primary.900}',
          focusColor: '{primary.950}',
        },
        text: {
          color: '{surface.900}',
          hoverColor: '{surface.950}',
          mutedColor: '{surface.600}',
          hoverMutedColor: '{surface.700}',
        },
        // Input borders need 3:1 against the field (WCAG 1.4.11).
        formField: {
          borderColor: '{surface.500}',
          hoverBorderColor: '{surface.600}',
          invalidBorderColor: '{red.600}',
          invalidPlaceholderColor: '{red.700}',
          color: '{surface.900}',
          placeholderColor: '{surface.500}',
          iconColor: '{surface.500}',
        },
        app: { background: '{surface.50}', borderColor: '{surface.200}', booth: '{surface.0}' },
        language: LANGUAGE_LIGHT,
        status: {
          error: { color: '{red.700}', background: '{red.50}', borderColor: '{red.600}' },
          warn: { color: '{amber.800}', background: '{amber.50}', borderColor: '{amber.700}' },
          info: { color: '{blue.700}', background: '{blue.50}', borderColor: '{blue.600}' },
          ok: { color: '{green.700}', background: '{green.50}', borderColor: '{green.700}' },
          busy: {
            color: '{primary.900}',
            background: '{primary.100}',
            borderColor: '{primary.700}',
          },
          off: {
            color: '{surface.600}',
            background: '{surface.100}',
            borderColor: '{surface.500}',
          },
        },
      },
      dark: {
        surface: BOOTH,
        // Paper on ink: the primary action turns light.
        primary: {
          color: '{surface.100}',
          contrastColor: '{surface.950}',
          hoverColor: '{surface.0}',
          activeColor: '{surface.300}',
        },
        highlight: {
          background: 'rgba(228, 231, 236, 0.14)',
          focusBackground: 'rgba(228, 231, 236, 0.22)',
          color: '{surface.50}',
          focusColor: '{surface.0}',
        },
        formField: {
          borderColor: '{surface.500}',
          hoverBorderColor: '{surface.400}',
          invalidBorderColor: '{red.400}',
        },
        text: {
          color: '{surface.100}',
          hoverColor: '{surface.0}',
          mutedColor: '{surface.400}',
          hoverMutedColor: '{surface.300}',
        },
        app: { background: '#101318', borderColor: '{surface.700}', booth: '{surface.950}' },
        language: LANGUAGE_DARK,
        status: {
          error: { color: '{red.300}', background: '{red.950}', borderColor: '{red.400}' },
          warn: { color: '{amber.300}', background: '{amber.950}', borderColor: '{amber.400}' },
          info: { color: '{blue.300}', background: '{blue.950}', borderColor: '{blue.400}' },
          ok: { color: '{green.400}', background: '{green.950}', borderColor: '{green.500}' },
          busy: {
            color: '{surface.100}',
            background: '{surface.800}',
            borderColor: '{surface.300}',
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
            primary: { borderColor: '{primary.color}' },
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
            primary: { borderColor: '{primary.color}' },
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
    // A note is information, not a state: ink on a neutral tint, not a saturated blue.
    message: {
      colorScheme: {
        light: {
          info: neutralMessage('light'),
          success: message('green', 'light'),
          warn: {
            ...WARN_NOTICE_LIGHT,
            outlined: { color: '{yellow.800}', borderColor: '{yellow.800}' },
            simple: { color: '{yellow.800}' },
          },
          error: message('red', 'light'),
        },
        dark: {
          info: neutralMessage('dark'),
          success: message('green', 'dark'),
          warn: message('yellow', 'dark'),
          error: message('red', 'dark'),
        },
      },
    },
    // The tray's corners are concentric with its checked chip's: the chip's radius plus the
    // option's padding (togglebutton.padding), not the same radius 4px further out.
    selectbutton: {
      root: { borderRadius: 'calc({content.border.radius} + 0.25rem)' },
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
