// Tests for the card modules: defining their elements (including after HA's
// scoped registry polyfill replaces window.customElements), the load-twice
// guards, and card-picker suggestions. Run with
// `node --test "tests/js/*.test.mjs"` (no dependencies).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { beforeEach, test } from "node:test";

const WWW = new URL("../../custom_components/birdweather/www/", import.meta.url);

// A bare-bones registry. Swapping in a new one mimics HA's scoped registry
// polyfill replacing window.customElements: anything defined on the old one
// is invisible to the new one.
class Registry {
  #defs = new Map();
  #pending = new Map();
  define(tag, cls) {
    if (this.#defs.has(tag)) throw new Error(`${tag} already defined`);
    this.#defs.set(tag, cls);
    this.#pending.get(tag)?.resolve(cls);
  }
  get(tag) {
    return this.#defs.get(tag);
  }
  whenDefined(tag) {
    if (this.#defs.has(tag)) return Promise.resolve(this.#defs.get(tag));
    if (!this.#pending.has(tag)) this.#pending.set(tag, Promise.withResolvers());
    return this.#pending.get(tag).promise;
  }
}

beforeEach(() => {
  globalThis.HTMLElement ??= class {};
  globalThis.window = globalThis;
  globalThis.customElements = new Registry();
  delete globalThis.customCards;
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

// Lets the cards' whenDefined callbacks run.
const settle = () => new Promise((resolve) => setTimeout(resolve));

for (const [file, tag] of [
  ["birdweather-bird-card.js", "birdweather-bird-card"],
  ["birdweather-details-card.js", "birdweather-bird-list-card"],
]) {
  test(`${file} defines its elements again when the polyfill replaces the registry`, async () => {
    const native = customElements;
    await runCardModule(file);
    assert.ok(native.get(tag));

    // HA's app bundle installs the polyfill, then defines <home-assistant> on
    // it, which defines a stand-in for it on the native registry.
    const polyfilled = new Registry();
    globalThis.customElements = polyfilled;
    const waiting = polyfilled.whenDefined(tag); // Lovelace's error card
    polyfilled.define("home-assistant", class {});
    native.define("home-assistant", class {});
    await settle();

    assert.equal(polyfilled.get(tag), native.get(tag));
    assert.equal(polyfilled.get(`${tag}-editor`), native.get(`${tag}-editor`));
    assert.equal(await waiting, native.get(tag));
  });

  test(`${file} defines once when the polyfill was already in place`, async () => {
    customElements.define("home-assistant", class {});
    await runCardModule(file);
    await settle();

    assert.ok(customElements.get(tag));
    assert.ok(customElements.get(`${tag}-editor`));
  });

  test(`${file} run twice keeps one definition and one card-picker entry`, async () => {
    await runCardModule(file);
    const first = customElements.get(tag);
    await runCardModule(file);
    customElements.define("home-assistant", class {});
    await settle();

    assert.equal(customElements.get(tag), first);
    assert.deepEqual(
      window.customCards.map((c) => c.type),
      [tag],
    );
  });
}

// Card-picker suggestions ("By entity", Home Assistant 2026.6+).
async function customCardEntry(file, type) {
  await runCardModule(file);
  return window.customCards.find((c) => c.type === type);
}

function fakeHass() {
  const sensor = (translation_key, platform = "birdweather", detections = []) => ({
    state: { attributes: { detections } },
    entry: { platform, translation_key },
  });
  const all = {
    "sensor.box_top_species_today": sensor("daily_top_species"),
    "sensor.box_last_bat_detection": sensor("last_bat_detection"),
    "sensor.box_detections_today": { state: { attributes: {} }, entry: { platform: "birdweather" } },
    "sensor.other_list": sensor("whatever", "some_other_integration"),
  };
  return {
    states: Object.fromEntries(Object.entries(all).map(([id, v]) => [id, v.state])),
    entities: Object.fromEntries(Object.entries(all).map(([id, v]) => [id, v.entry])),
  };
}

test("the bird card suggests itself for this integration's list sensors only", async () => {
  const entry = await customCardEntry("birdweather-bird-card.js", "birdweather-bird-card");
  const hass = fakeHass();
  assert.deepEqual(entry.getEntitySuggestion(hass, "sensor.box_last_bat_detection"), {
    config: { type: "custom:birdweather-bird-card", entity: "sensor.box_last_bat_detection" },
  });
  assert.ok(entry.getEntitySuggestion(hass, "sensor.box_top_species_today"));
  assert.equal(entry.getEntitySuggestion(hass, "sensor.box_detections_today"), null);
  assert.equal(entry.getEntitySuggestion(hass, "sensor.other_list"), null);
  assert.equal(entry.getEntitySuggestion(hass, "sensor.missing"), null);
  assert.match(entry.documentationURL, /docs\/cards\.md$/);
});

test("the list card skips single-record sensors", async () => {
  const entry = await customCardEntry("birdweather-details-card.js", "birdweather-bird-list-card");
  const hass = fakeHass();
  assert.deepEqual(entry.getEntitySuggestion(hass, "sensor.box_top_species_today"), {
    config: { type: "custom:birdweather-bird-list-card", entity: "sensor.box_top_species_today" },
  });
  assert.equal(entry.getEntitySuggestion(hass, "sensor.box_last_bat_detection"), null);
  assert.equal(entry.getEntitySuggestion(hass, "sensor.other_list"), null);
});
