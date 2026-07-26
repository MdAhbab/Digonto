/**
 * `three` ships no bundled type declarations in this version, and adding
 * `@types/three` would mean a new dependency (the brief for this build rules
 * that out). EarthScene.tsx is the only consumer and only needs the runtime
 * export; this ambient module keeps `tsc --noEmit` clean without one.
 */
declare module "three";
