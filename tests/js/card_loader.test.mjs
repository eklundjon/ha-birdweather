// Tests for www/birdweather-card-loader.js and the card modules' load-twice
// guards. Run with `node --test "tests/js/*.test.mjs"` (no dependencies).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { beforeEach, test } from "node:test";

import { load } from "../../custom_components/birdweather/www/birdweather-card-loader.js";

const WWW = new URL("../../custom_components/birdweather/www/", import.meta.url);
const TAG = "birdweather-bird-card";
const PATH = "/birdweather/birdweather-bird-card.js";

// A bare-bones registry. Swapping in a new one mimics HA's scoped-registry
// polyfill replacing window.customElements: anything defined on the old one
// is invisible to the new one.
class Registry {
  #defs = new Map();
  define(tag, cls) {
    if (this.#defs.has(tag)) throw new Error(`${tag} already defined`);
    this.#defs.set(tag, cls);
  }
  get(tag) {
    return this.#defs.get(tag);
  }
}

// Stands in for the loader's timing, so the tests don't wait on real timers.
function fakeClock() {
  const clock = { time: 0, delays: [] };
  clock.now = () => clock.time;
  clock.sleep = async (ms) => {
    clock.delays.push(ms);
    clock.time += ms;
  };
  return clock;
}

beforeEach(() => {
  globalThis.customElements = new Registry();
});

test("stops after one import when the import defines the tag", async () => {
  const clock = fakeClock();
  const urls = [];
  await load(TAG, PATH, {
    ...clock,
    importModule: async (url) => {
      urls.push(url);
      customElements.define(TAG, class {});
    },
  });
  // The first try must use the exact add_extra_js_url URL.
  assert.deepEqual(urls, [`${PATH}?v=dev`]);
  assert.deepEqual(clock.delays, []);
});

test("doesn't import at all when the tag is already defined", async () => {
  customElements.define(TAG, class {});
  let imports = 0;
  await load(TAG, PATH, {
    ...fakeClock(),
    importModule: async () => {
      imports++;
    },
  });
  assert.equal(imports, 0);
});

test("retries under a new URL when the import resolves but the tag isn't defined", async () => {
  // The polyfill case: the module already ran and defined itself on a
  // registry that is no longer current, so re-importing its URL is a no-op.
  // Only a fresh URL runs it again.
  const clock = fakeClock();
  const urls = [];
  await load(TAG, PATH, {
    ...clock,
    importModule: async (url) => {
      urls.push(url);
      if (url.includes("&retry=")) customElements.define(TAG, class {});
    },
  });
  assert.deepEqual(urls, [`${PATH}?v=dev`, `${PATH}?v=dev&retry=1`]);
  assert.deepEqual(clock.delays, [1_000]);
});

test("keeps retrying with backoff while the import rejects", async () => {
  const clock = fakeClock();
  const urls = [];
  await load(TAG, PATH, {
    ...clock,
    importModule: async (url) => {
      urls.push(url);
      if (urls.length < 3) throw new TypeError("404");
      customElements.define(TAG, class {});
    },
  });
  assert.deepEqual(urls, [
    `${PATH}?v=dev`,
    `${PATH}?v=dev&retry=1`,
    `${PATH}?v=dev&retry=2`,
  ]);
  assert.deepEqual(clock.delays, [1_000, 2_000]);
});

test("gives up after about ten minutes if the tag never appears", async (t) => {
  const warn = t.mock.method(console, "warn", () => {});
  const clock = fakeClock();
  await load(TAG, PATH, { ...clock, importModule: async () => {} });
  assert.equal(warn.mock.callCount(), 1);
  // 1s doubling to a 30s cap, stopping once more than 10 minutes have passed.
  assert.equal(Math.max(...clock.delays), 30_000);
  assert.ok(clock.time > 10 * 60_000);
  assert.ok(clock.time < 11 * 60_000);
});

// Runs a card module as a fresh ES module each time, as the browser does for
// each distinct URL. (Importing the file itself wouldn't: with no import or
// export, Node loads it as CommonJS, which is cached by path.)
let runs = 0;
async function runCardModule(file) {
  const source = await readFile(new URL(file, WWW), "utf8");
  await import(
    `data:text/javascript,${encodeURIComponent(`${source}\n// run ${++runs}`)}`
  );
}

// The retry above runs a card module a second time. That has to leave one
// definition per registry and one card-picker entry.
for (const [file, tag] of [
  ["birdweather-bird-card.js", "birdweather-bird-card"],
  ["birdweather-details-card.js", "birdweather-bird-list-card"],
]) {
  test(`${file} defines on the new registry without duplicating its card-picker entry`, async () => {
    globalThis.HTMLElement ??= class {};
    globalThis.window = globalThis;
    delete globalThis.customCards;

    const native = customElements;
    await runCardModule(file);
    assert.ok(native.get(tag));

    // The polyfill replaces the registry; the loader's retry runs the module again.
    globalThis.customElements = new Registry();
    await runCardModule(file);
    assert.ok(customElements.get(tag));
    assert.ok(customElements.get(`${tag}-editor`));
    assert.deepEqual(
      window.customCards.map((c) => c.type),
      [tag],
    );
  });
}
