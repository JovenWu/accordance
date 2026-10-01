/// <reference types="vite/client" />

// Fontsource ships CSS-only packages; TS needs a module stub for the bare
// side-effect import in main.tsx.
declare module "@fontsource-variable/inter";
