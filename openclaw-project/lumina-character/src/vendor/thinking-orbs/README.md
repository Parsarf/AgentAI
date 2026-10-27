# thinking-orbs (vendored)

Source: https://github.com/Jakubantalik/thinking-orbs, commit `de85557` ("Cut the favicon's corners back out"), package version 0.3.1.
License: MIT (see `LICENSE`), © Jakub Antalik.

Only the library's `src/` is copied (the component, presets, theme hook and drawing engine). The demo site, build tooling, native port and
golden-spec scripts are not. No runtime dependencies (React is the only peer). Plain 2D canvas, no network, storage or eval.

Why vendored instead of `npm install`: about 1,500 lines, read in full before use, and no new package to trust or keep patched.
Local changes to these files: none. Lumina uses the library's drawing engine (`resolvePreset`, `MODE_DRAWS`) through its own wrapper,
`src/components/Orb.tsx`, instead of the library's `ThinkingOrb` component: that component runs one 60 fps loop per orb, which measurably cost
more than slow dotted motion needs. The wrapper draws every orb from one shared 15 fps clock (`src/lib/frameClock.ts`, also used by the planet),
only while on screen and not while scrolling or typing, pins the dark palette, honours Lumina's and the system's reduced-motion settings, and
lets at most three orbs animate at once. (`ThinkingOrb.tsx` stays in this folder, unused, so the library remains whole.)

To update: re-copy `src/` from a newer commit, re-read the diff, and run the tests.
