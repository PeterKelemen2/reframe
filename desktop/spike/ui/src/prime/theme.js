// A copy of frontend/src/styles/theme.ts and the dark-mode selector of frontend/src/setup.ts:
// the check renders the preset the frontend uses.
import { definePreset } from "@primeuix/themes";
import Aura from "@primeuix/themes/aura";

export const ReframePreset = definePreset(Aura, {
  semantic: {
    primary: {
      50: "{indigo.50}",
      100: "{indigo.100}",
      200: "{indigo.200}",
      300: "{indigo.300}",
      400: "{indigo.400}",
      500: "{indigo.500}",
      600: "{indigo.600}",
      700: "{indigo.700}",
      800: "{indigo.800}",
      900: "{indigo.900}",
      950: "{indigo.950}",
    },
  },
});

export const DARK_MODE_CLASS = "reframe-dark";

export const primeVueOptions = {
  theme: {
    preset: ReframePreset,
    options: { darkModeSelector: `.${DARK_MODE_CLASS}` },
  },
};
