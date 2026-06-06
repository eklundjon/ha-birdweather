// Seeded from ha-haikubox/haikubox-details-card.js via scripts/sync-cards.sh,
// then FORKED — BirdWeather-only photo attribution lives here now.
// Hand-maintained: do NOT re-run sync-cards.sh over this file (it would drop
// that). See scripts/sync-cards.sh.
function _esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Confidence band → display label. The integration derives the low/medium/high
// band from each detection's numeric confidence and surfaces it as
// `confidence_band`; the card just labels it (the raw number stays hidden).
function _bandLabel(band) {
  return { low: "Low", medium: "Medium", high: "High" }[band] ?? "";
}

// Render a 24-bucket hourly array (the integration's `hourly` diel field) as a
// Unicode sparkline, one block per hour, scaled to the array's own max. Returns
// "" for an empty/all-zero array.
function _sparkline(arr) {
  if (!Array.isArray(arr) || arr.length === 0) return "";
  const blocks = "▁▂▃▄▅▆▇█";
  const max = Math.max(...arr);
  if (max <= 0) return "";
  return arr
    .map((v) => blocks[v <= 0 ? 0 : Math.min(blocks.length - 1, Math.round((v / max) * (blocks.length - 1)))])
    .join("");
}

// "HH:00" of the busiest hour in a 24-bucket array, or "".
function _peakHourLabel(arr) {
  if (!Array.isArray(arr) || arr.length === 0) return "";
  let max = -1;
  let idx = -1;
  arr.forEach((v, h) => {
    if (v > max) {
      max = v;
      idx = h;
    }
  });
  return idx >= 0 && max > 0 ? String(idx).padStart(2, "0") + ":00" : "";
}

// Editor entity-picker filter: only show BirdWeather sensors that expose
// a `detections` list (so the bird/list cards have something to render).
// Excludes daily_count, which is a numeric-only total. Returns true
// (allow) when we can't read the registry, so the picker degrades to
// "all matching sensors" rather than "no sensors" on older HA.
function _isBirdWeatherListEntity(hass, state) {
  if (!Array.isArray(state?.attributes?.detections)) return false;
  const entries = hass?.entities;
  if (!entries) return true;
  const entry = entries[state.entity_id];
  if (!entry) return true;
  return entry.platform === "birdweather";
}

// ── Editor ────────────────────────────────────────────────────────────────────

class BirdWeatherBirdListCardEditor extends HTMLElement {
  // No shadow DOM — light DOM avoids isolation issues with ha-entity-picker

  setConfig(config) {
    this._config = config;
    if (!this._built) {
      this._built = true;
      this._init();
    } else {
      if (this._picker)     this._picker.value     = config.entity ?? "";
      if (this._titleField) this._titleField.value = config.title ?? "";
      if (this._topField)   this._topField.value   = config.top ?? 10;
      if (this._sizeField)  this._sizeField.value  = config.row_size ?? "small";
      if (this._ebirdField) this._ebirdField.value = !!config.show_ebird;
      if (this._aabField)   this._aabField.value   = !!config.show_allaboutbirds;
      if (this._mlField)    this._mlField.value    = !!config.show_macaulay;
      if (this._bwField)    this._bwField.value    = !!config.show_birdweather;
      if (this._confField)  this._confField.value  = config.show_confidence !== false;
      if (this._descField)  this._descField.value  = config.show_description !== false;
      if (this._actField)   this._actField.value   = config.show_activity !== false;
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._built = true;
      this._init();
    } else {
      if (this._picker)     this._picker.hass     = hass;
      if (this._titleField) this._titleField.hass = hass;
      if (this._topField)   this._topField.hass   = hass;
      if (this._sizeField)  this._sizeField.hass  = hass;
      if (this._ebirdField) this._ebirdField.hass = hass;
      if (this._aabField)   this._aabField.hass   = hass;
      if (this._mlField)    this._mlField.hass    = hass;
      if (this._bwField)    this._bwField.hass    = hass;
      if (this._confField)  this._confField.hass  = hass;
      if (this._descField)  this._descField.hass  = hass;
      if (this._actField)   this._actField.hass   = hass;
    }
  }

  _fire(update) {
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: { ...this._config, ...update } },
      bubbles: true,
      composed: true,
    }));
  }

  async _init() {
    try {
      if (window.loadCardHelpers) await window.loadCardHelpers();
    } catch (_) { /* ignore */ }

    const form = document.createElement("div");
    form.style.cssText = "display:flex;flex-direction:column;gap:4px;padding:0 16px 16px";

    let entityField;
    if (customElements.get("ha-entity-picker")) {
      entityField = document.createElement("ha-entity-picker");
      entityField.label = "Entity";
      entityField.setAttribute("allow-custom-entity", "");
      entityField.includeDomains = ["sensor"];
      entityField.entityFilter = (state) => _isBirdWeatherListEntity(this._hass, state);
      if (this._hass) entityField.hass = this._hass;
      entityField.value = this._config?.entity ?? "";
      entityField.addEventListener("value-changed", (e) => this._fire({ entity: e.detail.value }));
    } else if (customElements.get("ha-selector")) {
      entityField = document.createElement("ha-selector");
      entityField.label = "Entity";
      entityField.selector = { entity: { domain: ["sensor"], integration: "birdweather" } };
      if (this._hass) entityField.hass = this._hass;
      entityField.value = this._config?.entity ?? "";
      entityField.addEventListener("value-changed", (e) => this._fire({ entity: e.detail.value }));
    } else {
      entityField = document.createElement("ha-textfield");
      entityField.label = "Entity ID";
      entityField.value = this._config?.entity ?? "";
      entityField.addEventListener("change", (e) => this._fire({ entity: e.target.value }));
    }
    entityField.style.cssText = "display:block;width:100%";
    this._picker = entityField;

    // Title + Max-items use ha-selector (not ha-textfield): ha-textfield
    // isn't reliably registered in the card-editor context across
    // browsers and renders invisibly, whereas ha-selector always is.
    const titleField = document.createElement("ha-selector");
    titleField.label = "Title (optional)";
    titleField.selector = { text: {} };
    if (this._hass) titleField.hass = this._hass;
    titleField.value = this._config?.title ?? "";
    titleField.style.cssText = "display:block;width:100%";
    titleField.addEventListener("value-changed", (e) => this._fire({ title: e.detail.value ?? "" }));
    this._titleField = titleField;

    const topField = document.createElement("ha-selector");
    topField.label = "Max items";
    topField.selector = { number: { min: 1, step: 1, mode: "box" } };
    if (this._hass) topField.hass = this._hass;
    topField.value = this._config?.top ?? 10;
    topField.style.cssText = "display:block;width:100%";
    topField.addEventListener("value-changed", (e) => {
      const v = parseInt(e.detail.value, 10);
      this._fire({ top: Number.isFinite(v) && v >= 1 ? v : 10 });
    });
    this._topField = topField;

    form.append(entityField, titleField, topField);

    // Row size (density) — scales the compact-row photo, padding, and text.
    // ha-selector dropdown; skipped on older HA without ha-selector (the
    // YAML key still works).
    if (customElements.get("ha-selector")) {
      const sizeField = document.createElement("ha-selector");
      sizeField.label = "Row size";
      sizeField.selector = {
        select: {
          mode: "dropdown",
          options: [
            { value: "small", label: "Small" },
            { value: "medium", label: "Medium" },
            { value: "large", label: "Large" },
          ],
        },
      };
      if (this._hass) sizeField.hass = this._hass;
      sizeField.value = this._config?.row_size ?? "small";
      sizeField.style.cssText = "display:block;width:100%";
      sizeField.addEventListener("value-changed", (e) => this._fire({ row_size: e.detail.value }));
      this._sizeField = sizeField;
      form.append(sizeField);
    }

    // Optional per-row external reference link toggles. ha-selector
    // boolean renders a themed switch; skipped entirely on older HA
    // without ha-selector (the YAML keys still work).
    if (customElements.get("ha-selector")) {
      const ebirdField = document.createElement("ha-selector");
      ebirdField.label = "eBird links in compact view";
      ebirdField.selector = { boolean: {} };
      if (this._hass) ebirdField.hass = this._hass;
      ebirdField.value = !!this._config?.show_ebird;
      ebirdField.addEventListener("value-changed", (e) => this._fire({ show_ebird: e.detail.value }));
      this._ebirdField = ebirdField;

      const aabField = document.createElement("ha-selector");
      aabField.label = "All About Birds links in compact view";
      aabField.selector = { boolean: {} };
      if (this._hass) aabField.hass = this._hass;
      aabField.value = !!this._config?.show_allaboutbirds;
      aabField.addEventListener("value-changed", (e) => this._fire({ show_allaboutbirds: e.detail.value }));
      this._aabField = aabField;

      const mlField = document.createElement("ha-selector");
      mlField.label = "Macaulay Library links in compact view";
      mlField.selector = { boolean: {} };
      if (this._hass) mlField.hass = this._hass;
      mlField.value = !!this._config?.show_macaulay;
      mlField.addEventListener("value-changed", (e) => this._fire({ show_macaulay: e.detail.value }));
      this._mlField = mlField;

      const bwField = document.createElement("ha-selector");
      bwField.label = "BirdWeather links in compact view";
      bwField.selector = { boolean: {} };
      if (this._hass) bwField.hass = this._hass;
      bwField.value = !!this._config?.show_birdweather;
      bwField.addEventListener("value-changed", (e) => this._fire({ show_birdweather: e.detail.value }));
      this._bwField = bwField;

      // Confidence band in the expanded detail view (default on). Shows a
      // low/medium/high chip alongside the count / last-heard metrics.
      const confField = document.createElement("ha-selector");
      confField.label = "Show confidence in detail view";
      confField.selector = { boolean: {} };
      if (this._hass) confField.hass = this._hass;
      confField.value = this._config?.show_confidence !== false;
      confField.addEventListener("value-changed", (e) => this._fire({ show_confidence: e.detail.value }));
      this._confField = confField;

      // Wikipedia description blurb in the detail view (default on). Fetched
      // on demand from Wikipedia when a row is opened.
      const descField = document.createElement("ha-selector");
      descField.label = "Show description in detail view";
      descField.selector = { boolean: {} };
      if (this._hass) descField.hass = this._hass;
      descField.value = this._config?.show_description !== false;
      descField.addEventListener("value-changed", (e) => this._fire({ show_description: e.detail.value }));
      this._descField = descField;

      // Diel activity sparkline in the detail view (default on).
      const actField = document.createElement("ha-selector");
      actField.label = "Show activity sparkline in detail view";
      actField.selector = { boolean: {} };
      if (this._hass) actField.hass = this._hass;
      actField.value = this._config?.show_activity !== false;
      actField.addEventListener("value-changed", (e) => this._fire({ show_activity: e.detail.value }));
      this._actField = actField;

      form.append(ebirdField, aabField, mlField, bwField, confField, descField, actField);
    }

    this.appendChild(form);
  }
}

// Idempotent define: if the script gets loaded twice in the same page
// (cache flap during an HA upgrade, version-bust transient, etc.) a
// second `define` would throw and abort the script mid-execution,
// stranding window.customCards in an inconsistent state. The same
// guard appears around the card itself and customCards.push below.
if (!customElements.get("birdweather-bird-list-card-editor")) {
  customElements.define("birdweather-bird-list-card-editor", BirdWeatherBirdListCardEditor);
}

// ── Card ──────────────────────────────────────────────────────────────────────

class BirdWeatherBirdListCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  static getConfigElement() {
    return document.createElement("birdweather-bird-list-card-editor");
  }

  static getStubConfig() {
    return { entity: "", title: "", top: 10, row_size: "small" };
  }

  setConfig(config) {
    if (config.entity === undefined) throw new Error("'entity' is required");
    this._config = { top: 10, row_size: "small", ...config };
  }

  set hass(hass) {
    this._hass = hass;
    const stateObj = hass?.states[this._config?.entity];
    // Gate on last_updated, not last_changed: this entity's state is an
    // item count that rarely changes, while the ranked `detections`
    // attribute re-orders frequently. last_changed only moves when
    // .state changes, so it would freeze on attribute-only updates.
    // Always render at least once, even when the entity is missing
    // (lastUpdated undefined): otherwise a misconfigured card would
    // short-circuit forever and stay permanently blank instead of
    // showing its empty state.
    const lastUpdated = stateObj?.last_updated;
    if (this._rendered && lastUpdated === this._lastUpdated) return;
    this._lastUpdated = lastUpdated;
    this._rendered = true;
    this._render();
  }

  // Lifecycle: a 60s ticker keeps the "last heard" labels honest between
  // polls. We don't re-render — just rewrite the text content of each
  // element carrying a data-last-seen attribute, so the open detail view
  // and image loads stay undisturbed.
  connectedCallback() {
    if (this._timeTicker) return;
    this._timeTicker = setInterval(() => this._updateTimes(), 60_000);
  }
  disconnectedCallback() {
    if (this._timeTicker) {
      clearInterval(this._timeTicker);
      this._timeTicker = null;
    }
  }
  _updateTimes() {
    if (!this.shadowRoot) return;
    this.shadowRoot.querySelectorAll("[data-last-seen]").forEach((el) => {
      el.textContent = this._relativeTime(el.dataset.lastSeen) ?? "";
    });
  }

  _rank(item, index) {
    // Every sensor stamps `rank` per its own criterion; index is a
    // defensive fallback only.
    return `#${item.rank ?? index + 1}`;
  }

  // External reference link anchors. eBird keys on the species code we
  // already carry as sp_code; All About Birds keys on the common name
  // with spaces → underscores (e.g. "Downy_Woodpecker", hyphens
  // preserved). `ebird`/`aab` flags gate each; an anchor is skipped if
  // its source field is missing. Returns "" when nothing applies.
  // Reference links are surfaced by the integration as per-record URL fields
  // (`ebird_url` / `allaboutbirds_url` / `wikipedia_url`) — the card just renders
  // the ones present and enabled; it no longer constructs URLs itself. This is
  // the shared link logic the BirdWeather and Haikubox cards converge on; each
  // integration decides which URLs to surface.
  _linkAnchors(item, f) {
    const btn = (url, label) =>
      `<a class="link-btn" href="${_esc(url)}" target="_blank" rel="noreferrer noopener" title="${_esc(item.species)} on ${label}">${label}</a>`;
    const parts = [];
    if (f.ebird && item.ebird_url) parts.push(btn(item.ebird_url, "eBird"));
    if (f.aab && item.allaboutbirds_url) parts.push(btn(item.allaboutbirds_url, "All About Birds"));
    if (f.ml && item.macaulay_url) parts.push(btn(item.macaulay_url, "Macaulay Library"));
    if (f.bw && item.birdweather_url) parts.push(btn(item.birdweather_url, "BirdWeather"));
    // Wikipedia is intentionally not a button: it's reached by tapping the
    // description blurb (which is sourced from Wikipedia), so a separate pill
    // would be redundant.
    return parts.join("");
  }

  // Wrap the requested anchors in a container, or "" if none. `cls`
  // distinguishes the compact-row block from the roomy detail block. `f` is a
  // flags object {ebird, aab, ml, bw} gating each link (Wikipedia is reached via
  // the description blurb, not a button).
  _linksBlock(item, f, cls) {
    const anchors = this._linkAnchors(item, f);
    return anchors ? `<div class="${cls}">${anchors}</div>` : "";
  }

  // Lazily fetch a species' Wikipedia summary (REST API, CORS-enabled) when its
  // detail row is open. Static metadata, so the integration doesn't poll/store
  // it — the card fetches on demand and caches per species for the session. The
  // article title is derived from the integration-supplied wikipedia_url, so the
  // same logic works on any source that has one (BirdWeather, Haikubox). Fails
  // silently (no blurb) when offline / unavailable.
  _loadDescription(species, wikiUrl, el) {
    if (!el || !wikiUrl) return;
    this._descCache ??= new Map();
    if (this._descCache.has(species)) {
      el.textContent = this._descCache.get(species);
      return;
    }
    let api;
    try {
      const u = new URL(wikiUrl);
      const title = u.pathname.split("/wiki/")[1];
      if (!title) return;
      api = `${u.origin}/api/rest_v1/page/summary/${title}`;
    } catch (_) {
      return;
    }
    el.textContent = "…";
    fetch(api, { headers: { Accept: "application/json" } })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((j) => {
        const text = j.extract || "";
        this._descCache.set(species, text);
        // The list may have re-rendered/re-ordered during the fetch; only write
        // if this element is still showing this species.
        if (el.isConnected && el.dataset.species === species) el.textContent = text;
      })
      .catch(() => {
        if (el.isConnected && el.dataset.species === species) el.textContent = "";
      });
  }

  // Fetch the description for whichever row is currently open (only the open
  // row's detail is visible, so we never fan out fetches across the whole list).
  _maybeLoadDescription() {
    if (!this._openSpecies || this._config?.show_description === false) return;
    const el = this.shadowRoot?.querySelector(".item.is-open .detail-desc-text");
    if (!el) return;
    const item = this._items?.find((i) => i.species === this._openSpecies);
    if (item?.wikipedia_url) this._loadDescription(item.species, item.wikipedia_url, el);
  }

  // Photo credit/license for the expanded view. The coordinator sanitises
  // BirdWeather's HTML credit to plain text + URL, so these are safe to link.
  // The station photos are CC-licensed, which requires attribution.
  _attributionBlock(item) {
    if (this._config?.show_attribution === false || !item.image_url) return "";
    const link = (text, url) =>
      url
        ? `<a href="${_esc(url)}" target="_blank" rel="noopener noreferrer">${_esc(text)}</a>`
        : _esc(text);
    const parts = [];
    if (item.image_credit) parts.push(link(item.image_credit, item.image_credit_url));
    if (item.image_license) parts.push(link(item.image_license, item.image_license_url));
    if (!parts.length) return "";
    return `<div class="detail-attribution">📷 ${parts.join(" · ")}</div>`;
  }

  _relativeTime(isoString) {
    if (!isoString) return null;
    // Clamp: a future timestamp (clock skew) must not show "-3s ago".
    const diff = Math.max(0, Math.floor((Date.now() - new Date(isoString)) / 1000));
    if (diff < 60)    return `${diff}s ago`;
    if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  _render() {
    // Defensive: HA's card lifecycle is normally setConfig → set hass
    // (which calls _render), but during a reload or first-mount edge
    // case `set hass` can arrive before `setConfig` lands. Bail until
    // the config exists rather than throwing on `this._config.entity`.
    if (!this._config) return;
    const stateObj = this._hass?.states[this._config.entity];
    const attrs = stateObj?.attributes ?? {};
    const items = (attrs.detections ?? []).slice(0, this._config.top);
    this._items = items;  // referenced by the row toggle handler
    // Fall back to the entity's friendly name when no title is set.
    // The stub config and editor write title:"" (not nullish), so a
    // plain `??` chain never reached the fallback for UI-created cards.
    const configured = this._config.title;
    const title = (configured && configured.trim())
      ? configured
      : (attrs.friendly_name ?? "");

    // Row density → class on .list. Default (small) needs no class.
    const size = this._config.row_size;
    const sizeClass = size === "medium" ? " size-medium" : size === "large" ? " size-large" : "";

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; height: 100%; }
        ha-card {
          overflow: hidden;
          height: 100%;
          padding: 0;
        }
        .layout {
          display: flex;
          flex-direction: column;
          height: 100%;
          padding-bottom: 4px;
        }

        .card-header {
          padding: 14px 16px 10px;
          font-size: 1.15em;
          font-weight: 600;
          text-align: center;
          color: var(--primary-text-color);
          border-bottom: 1px solid var(--divider-color);
          flex-shrink: 0;
        }

        .list {
          flex: 1;
          overflow-y: auto;
          min-height: 0;
        }
        .list::-webkit-scrollbar { width: 4px; }
        .list::-webkit-scrollbar-track { background: transparent; }
        .list::-webkit-scrollbar-thumb {
          background: var(--scrollbar-thumb-color, var(--divider-color));
          border-radius: 2px;
        }

        /* Each list item is a clickable container holding a compact view
           and a detail view. .is-open swaps which is shown, so the detail
           replaces the compact row in place rather than opening below it. */
        .item {
          border-bottom: 1px solid var(--divider-color);
          cursor: pointer;
          user-select: none;
          /* Width-only containment so the open detail view can respond to
             the card's width via @container queries (see .detail below).
             inline-size doesn't constrain height, so rows still grow to
             fit their content. */
          container-type: inline-size;
        }
        .item:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: -2px;
        }

        /* Compact (resting) view */
        .compact {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 6px 16px;
        }
        .item.is-open .compact { display: none; }

        .thumb,
        .thumb-placeholder {
          width: 40px;
          height: 40px;
          border-radius: 50%;
          flex-shrink: 0;
          background: var(--secondary-background-color);
        }
        .thumb { object-fit: cover; }
        .thumb-placeholder {
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 1.1em;
        }

        .rank {
          min-width: 1.6em;
          font-size: 0.9em;
          font-weight: 700;
          color: var(--secondary-text-color);
          text-align: right;
          flex-shrink: 0;
        }

        .info { flex: 1; min-width: 0; }
        .name {
          font-size: 0.9em;
          font-weight: 500;
          color: var(--primary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .sub {
          font-size: 0.78em;
          font-style: italic;
          color: var(--secondary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        /* Row density — scales the compact view. Default (small) matches
           the CSS above; medium/large grow photo, padding, and text. */
        .list.size-medium .compact { gap: 14px; padding: 9px 16px; }
        .list.size-medium .thumb,
        .list.size-medium .thumb-placeholder { width: 56px; height: 56px; }
        .list.size-medium .name { font-size: 1.15em; }
        .list.size-medium .sub { font-size: 0.92em; }
        .list.size-medium .rank { font-size: 1.15em; }
        .list.size-medium .detail-name { font-size: 1.25em; }
        .list.size-medium .detail-sci { font-size: 1em; }

        .list.size-large .compact { gap: 16px; padding: 13px 16px; }
        .list.size-large .thumb,
        .list.size-large .thumb-placeholder { width: 76px; height: 76px; }
        .list.size-large .name { font-size: 1.45em; }
        .list.size-large .sub { font-size: 1.1em; }
        .list.size-large .rank { font-size: 1.45em; }
        .list.size-large .detail-name { font-size: 1.55em; }
        .list.size-large .detail-sci { font-size: 1.2em; }

        /* External reference link buttons (eBird / Wikipedia / All About Birds /
           Macaulay Library / BirdWeather). The species name takes priority: the
           cluster is capped and allowed to shrink, so once it's wide enough the
           buttons stack into a second/third row instead of squeezing the name. */
        .row-links {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          flex-shrink: 1;
          min-width: 0;
          max-width: 50%;
          justify-content: flex-end;
          align-content: center;
        }
        .link-btn {
          display: inline-flex;
          align-items: center;
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
          border-radius: 6px;
          padding: 3px 8px;
          font-size: 0.72em;
          font-weight: 500;
          line-height: 1.4;
          white-space: nowrap;
          text-decoration: none;
        }
        .link-btn:hover { opacity: 0.9; }
        .link-btn:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }

        /* Detail (open) view — replaces the compact row in place.
           Responsive to the card width via the @container query below:
           narrow → photo stacked above the text; wide → photo beside the
           text, scaling up with available width. */
        .detail { display: none; }
        .item.is-open .detail {
          display: flex;
          flex-direction: column;
          gap: 12px;
          align-items: flex-start;
          padding: 12px 16px 14px;
        }
        /* Stacked (narrow) photo: whole image at its natural aspect ratio,
           width-capped — no square crop, so nothing is clipped on the
           sides. */
        .detail-photo {
          width: min(100%, 240px);
          height: auto;
          border-radius: var(--ha-card-border-radius, 4px);
          flex-shrink: 0;
        }
        .detail-photo-placeholder {
          width: min(100%, 240px);
          aspect-ratio: 1 / 1;
          border-radius: var(--ha-card-border-radius, 4px);
          flex-shrink: 0;
          background: var(--secondary-background-color);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 2.5em;
        }
        .detail-text { flex: 1; min-width: 0; }

        @container (min-width: 380px) {
          .item.is-open .detail {
            flex-direction: row;
            align-items: center;
            gap: 16px;
          }
          /* Beside the text, a uniform square (cropped) reads tidiest and
             scales with the card width. */
          .detail-photo,
          .detail-photo-placeholder {
            width: clamp(120px, 26cqw, 220px);
            aspect-ratio: 1 / 1;
          }
          .detail-photo {
            height: auto;
            object-fit: cover;
          }
        }
        .detail-name {
          font-size: 1.05em;
          font-weight: 600;
          color: var(--primary-text-color);
          margin-bottom: 2px;
        }
        .detail-sci {
          font-size: 0.875em;
          font-style: italic;
          color: var(--secondary-text-color);
          margin-bottom: 10px;
        }
        /* Wikipedia summary blurb, fetched on demand when a row is opened. The
           whole block is a link to the article — the clamped teaser plus a
           persistent "Read more" cue so the affordance is discoverable on touch
           (not just on hover). */
        .detail-desc {
          display: block;
          margin-bottom: 10px;
          text-decoration: none;
          cursor: pointer;
          color: var(--primary-text-color);
        }
        .detail-desc-text {
          /* Cap very long extracts so the row doesn't grow unboundedly. */
          display: -webkit-box;
          -webkit-line-clamp: 4;
          -webkit-box-orient: vertical;
          overflow: hidden;
          font-size: 0.85em;
          line-height: 1.45;
          color: var(--primary-text-color);
        }
        .detail-desc::after {
          content: "Read more on Wikipedia ›";
          display: block;
          margin-top: 3px;
          font-size: 0.78em;
          font-weight: 500;
          color: var(--primary-color);
        }
        .detail-desc:hover::after,
        .detail-desc:focus-visible::after { text-decoration: underline; }
        .detail-links {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 10px;
        }
        .detail-attribution {
          margin-top: 10px;
          font-size: 0.72em;
          color: var(--secondary-text-color);
        }
        .detail-attribution a { color: inherit; }
        .metrics {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .metric {
          background: var(--secondary-background-color);
          border-radius: 6px;
          padding: 3px 8px;
          font-size: 0.78em;
          color: var(--secondary-text-color);
          white-space: nowrap;
        }
        .metric strong {
          color: var(--primary-text-color);
          font-weight: 600;
        }
        /* Confidence band chip — a colored dot keys the low/medium/high level;
           the chip itself stays neutral so it sits quietly with the others. */
        .metric .conf-dot {
          display: inline-block;
          width: 0.6em;
          height: 0.6em;
          border-radius: 50%;
          margin-right: 5px;
          background: var(--secondary-text-color);
        }
        .metric.conf-high .conf-dot { background: var(--success-color, #43a047); }
        .metric.conf-medium .conf-dot { background: var(--warning-color, #fb8c00); }
        .metric.conf-low .conf-dot { background: var(--error-color, #e53935); }

        /* Diel activity sparkline — one Unicode block per hour (0–23), in a
           monospace face so the bars align; the peak-hour label sits beside it. */
        .detail-activity {
          display: flex;
          align-items: baseline;
          flex-wrap: wrap;
          gap: 4px 8px;
          margin-top: 10px;
          font-size: 0.8em;
          color: var(--secondary-text-color);
        }
        .detail-activity .spark {
          font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
          letter-spacing: 1px;
          line-height: 1;
          color: var(--primary-color);
          white-space: nowrap;
        }

        .empty {
          padding: 10px 16px;
          font-size: 0.85em;
          font-style: italic;
          color: var(--disabled-text-color);
        }
      </style>
      <ha-card>
        <div class="layout">
        ${title ? `<div class="card-header">${_esc(title)}</div>` : ""}
        <div class="list${sizeClass}">
          ${items.length === 0
            ? `<div class="empty">No data yet</div>`
            : items.map((item, i) => {
                const open = item.species === this._openSpecies;
                const t = this._relativeTime(item.last_seen);
                return `
                <div class="item${open ? " is-open" : ""}" data-idx="${i}" role="button" tabindex="0" aria-expanded="${open ? "true" : "false"}">
                  <div class="compact">
                    ${item.image_url
                      ? `<img class="thumb" src="${_esc(item.image_url)}" alt="${_esc(item.species)}" loading="lazy">`
                      : `<div class="thumb-placeholder">🐦</div>`}
                    <div class="rank">${_esc(this._rank(item, i))}</div>
                    <div class="info">
                      <div class="name">${_esc(item.species)}</div>
                      ${item.scientific_name ? `<div class="sub">${_esc(item.scientific_name)}</div>` : ""}
                    </div>
                    ${this._linksBlock(item, { ebird: this._config.show_ebird, aab: this._config.show_allaboutbirds, ml: this._config.show_macaulay, bw: this._config.show_birdweather }, "row-links")}
                  </div>
                  <div class="detail">
                    ${item.image_url
                      ? `<img class="detail-photo" src="${_esc(item.image_url)}" alt="${_esc(item.species)}" loading="lazy">`
                      : `<div class="detail-photo-placeholder">🐦</div>`}
                    <div class="detail-text">
                      <div class="detail-name">${_esc(item.species)}</div>
                      ${item.scientific_name ? `<div class="detail-sci">${_esc(item.scientific_name)}</div>` : ""}
                      ${this._config.show_description !== false && item.wikipedia_url
                        ? `<a class="detail-desc" href="${_esc(item.wikipedia_url)}" target="_blank" rel="noreferrer noopener" title="Read more on Wikipedia"><span class="detail-desc-text" data-species="${_esc(item.species)}">${_esc(this._descCache?.get(item.species) ?? "")}</span></a>`
                        : ""}
                      <div class="metrics">
                        ${item.count != null ? `<div class="metric"><strong>${_esc(item.count)}×</strong></div>` : ""}
                        ${t ? `<div class="metric">last heard <strong data-last-seen="${_esc(item.last_seen)}">${_esc(t)}</strong></div>` : ""}
                        ${this._config.show_confidence !== false && item.confidence_band
                          ? `<div class="metric conf-${_esc(item.confidence_band)}" title="Detection confidence"><span class="conf-dot"></span><strong>${_esc(_bandLabel(item.confidence_band))}</strong> confidence</div>`
                          : ""}
                        ${item.alpha ? `<div class="metric" title="Alpha banding code"><strong>${_esc(item.alpha)}</strong></div>` : ""}
                      </div>
                      ${this._config.show_activity !== false && Array.isArray(item.hourly) && item.hourly.some((v) => v > 0)
                        ? `<div class="detail-activity" title="Hourly activity (last 7 days)"><span class="spark">${_sparkline(item.hourly)}</span><span class="peak">most active ~${_peakHourLabel(item.hourly)}</span></div>`
                        : ""}
                      ${this._linksBlock(item, { ebird: true, aab: true, ml: true, bw: true }, "detail-links")}
                      ${this._attributionBlock(item)}
                    </div>
                  </div>
                </div>
              `;
              }).join("")}
        </div>
        </div>
      </ha-card>
    `;

    const list = this.shadowRoot.querySelector(".list");
    list.addEventListener("click", (e) => {
      // A link button lives inside the item; let it navigate without
      // also toggling the detail view.
      if (e.target.closest("a")) return;
      const item = e.target.closest(".item");
      if (item) this._toggleItem(item);
    });
    list.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      // Enter on a focused link navigates; don't also toggle the item.
      if (e.target.closest("a")) return;
      const item = e.target.closest(".item");
      if (!item) return;
      e.preventDefault();  // Space would otherwise scroll the list
      this._toggleItem(item);
    });

    // Replace broken images (S3 404, network drop) with the placeholder
    // glyph so users don't see the browser's broken-image icon. Wired per
    // <img> via event listener rather than inline onerror to keep the
    // template clean and CSP-friendly.
    this.shadowRoot.querySelectorAll(".thumb, .detail-photo").forEach((img) => {
      img.addEventListener("error", () => {
        const placeholder = document.createElement("div");
        placeholder.className = img.classList.contains("thumb")
          ? "thumb-placeholder"
          : "detail-photo-placeholder";
        placeholder.textContent = "🐦";
        img.replaceWith(placeholder);
      });
    });

    // An open row survived this re-render (re-ordered list) — (re)load its blurb.
    this._maybeLoadDescription();
  }

  // Toggle an item between its compact and detail views in place (the
  // detail replaces the compact row rather than opening a panel below).
  // Class-toggle only — no re-render — so scroll position is preserved.
  // Single-open: opening one closes any other.
  _toggleItem(item) {
    const idx = item.dataset.idx;
    const species = this._items?.[idx]?.species ?? null;
    const opening = !item.classList.contains("is-open");
    this.shadowRoot.querySelectorAll(".item").forEach((el) => {
      el.classList.remove("is-open");
      el.setAttribute("aria-expanded", "false");
    });
    if (opening) {
      item.classList.add("is-open");
      item.setAttribute("aria-expanded", "true");
    }
    // Remember the open species so it survives the next poll re-render —
    // the list re-orders, so track species not index.
    this._openSpecies = opening ? species : null;
    if (opening) this._maybeLoadDescription();
  }

  getCardSize() {
    const attrs = this._hass?.states[this._config.entity]?.attributes ?? {};
    return Math.min(attrs.detections?.length ?? 0, this._config.top) + 2;
  }

  getGridOptions() {
    // Sections grid is a 12-column scale. A ranked list wants full
    // width and height; users can shrink to half / 3 rows.
    return {
      columns: 12,
      rows: 6,
      min_columns: 6,
      min_rows: 3,
    };
  }
}

if (!customElements.get("birdweather-bird-list-card")) {
  customElements.define("birdweather-bird-list-card", BirdWeatherBirdListCard);

  window.customCards ??= [];
  window.customCards.push({
    type: "birdweather-bird-list-card",
    name: "BirdWeather Bird List Card",
    description: "Ranked bird species list — works with yearly, daily, or 7-day rarity sensors.",
  });
}
