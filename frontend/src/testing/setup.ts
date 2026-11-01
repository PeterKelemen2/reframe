// jsdom has no `matchMedia`, and PrimeVue calls it when some components mount (Select, the
// tooltip): a test that mounts a whole view would fail on it. Tests that need the system's colour
// scheme or reduced motion replace it with their own.
if (typeof window.matchMedia !== 'function') {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList
}
