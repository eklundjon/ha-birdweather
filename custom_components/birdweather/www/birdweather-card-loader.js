// Startup loader for the BirdWeather cards.
//
// Why this exists: the integration injects the card modules with
// add_extra_js_url, which HA bakes into index.html at page-render time. HA's
// web server comes up (and serves index.html) before stage-2 integrations like
// this one have set up, and the frontend never loads extra modules added after
// the page was rendered. A page loaded in that window — which is exactly when
// a browser or Companion app reconnecting after a restart reloads — gets no
// card JS, and every BirdWeather card stays a "Custom element doesn't exist"
// error until a manual refresh.
//
// This file is copied into config/www and registered as a Lovelace resource,
// so it's served from /local (mounted before the web server starts) and listed
// in the page from the first render. It imports the real card modules from
// the integration's own static path, retrying until that path is registered.
// Once the element is defined, Lovelace rebuilds any error cards on its own.
//
// The integration version rides in on this file's ?v= query (the resource URL)
// and is forwarded to the card URLs, so they match the add_extra_js_url URLs
// exactly — the browser's module map then normally runs each card module only
// once no matter which path loads it first.
//
// The one exception is browsers without native scoped custom element
// registries (e.g. WebKit before iPadOS/Safari 26), where HA's app bundle
// installs a polyfill that replaces window.customElements. index.html starts
// the app bundle and the add_extra_js_url modules in parallel; if a card
// module wins, it defines its element on the native registry, which the
// polyfill's get()/whenDefined() can't see — so Lovelace never finds the card,
// on every reload. Importing the same URL again is a no-op (the module has
// already run), so a resolved import only counts once the tag is visible on
// the current registry; otherwise the retry path re-runs the module under a
// fresh URL, which defines it on the polyfilled registry.

// Keep in sync with _CARDS in __init__.py: [custom element tag, module URL].
const CARDS = [
  ["birdweather-bird-card", "/birdweather/birdweather-bird-card.js"],
  ["birdweather-bird-list-card", "/birdweather/birdweather-bird-list-card.js"],
];

const version = new URL(import.meta.url).searchParams.get("v") ?? "dev";

// Retry schedule: 1s doubling to a 30s cap, for up to ~10 minutes. Stage 2
// can take minutes on a slow box (its timeout is 300s); past that the
// integration most likely failed to load, and we stop rather than poll a 404
// forever.
const FIRST_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;
const GIVE_UP_MS = 10 * 60_000;

// The options are seams for tests/js/card_loader.test.mjs; the page calls
// load(tag, path).
export async function load(tag, path, {
  importModule = (url) => import(url),
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  now = Date.now,
} = {}) {
  const started = now();
  let delay = FIRST_DELAY_MS;
  for (let attempt = 0; ; attempt++) {
    // Already defined (add_extra_js_url got there first, or an earlier try).
    if (customElements.get(tag)) return;
    // The first try uses the exact add_extra_js_url URL. Retries add a unique
    // param: a failed fetch may be remembered by the module map or the HTTP
    // cache (404s are heuristically cacheable), so the same URL could keep
    // failing even after the path is registered. It also forces the module to
    // run again in the polyfill case above. A card module that ends up loaded
    // under two URLs is harmless — its define and customCards entry are guarded.
    const url = `${path}?v=${encodeURIComponent(version)}` +
      (attempt ? `&retry=${attempt}` : "");
    let error;
    try {
      await importModule(url);
      // Resolving only means the module has run at some point, not that the
      // current registry can see the element (see the polyfill note above).
      if (customElements.get(tag)) return;
    } catch (err) {
      error = err;
    }
    if (now() - started > GIVE_UP_MS) {
      console.warn(`BirdWeather: giving up loading ${path}`, error ?? `${tag} was never defined`);
      return;
    }
    await sleep(delay);
    delay = Math.min(delay * 2, MAX_DELAY_MS);
  }
}

// Only in a page: the tests import this file under Node, which has no
// custom element registry.
if (typeof customElements !== "undefined") {
  for (const [tag, path] of CARDS) load(tag, path);
}
