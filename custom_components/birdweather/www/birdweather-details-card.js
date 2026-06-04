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

      form.append(ebirdField, aabField);
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
  _linkAnchors(item, ebird, aab) {
    const parts = [];
    if (ebird && item.sp_code) {
      const url = `https://ebird.org/species/${encodeURIComponent(item.sp_code)}`;
      parts.push(
        `<a class="link-btn" href="${_esc(url)}" target="_blank" rel="noreferrer noopener" title="${_esc(item.species)} on eBird">eBird</a>`
      );
    }
    if (aab && item.species) {
      const slug = String(item.species).replace(/ /g, "_");
      const url = `https://www.allaboutbirds.org/guide/${encodeURIComponent(slug)}`;
      parts.push(
        `<a class="link-btn" href="${_esc(url)}" target="_blank" rel="noreferrer noopener" title="${_esc(item.species)} on All About Birds">All About Birds</a>`
      );
    }
    return parts.join("");
  }

  // Wrap the requested anchors in a container, or "" if none. `cls`
  // distinguishes the compact-row block from the roomy detail block.
  _linksBlock(item, ebird, aab, cls) {
    const anchors = this._linkAnchors(item, ebird, aab);
    return anchors ? `<div class="${cls}">${anchors}</div>` : "";
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

        /* External reference link buttons (eBird / All About Birds) */
        .row-links {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          flex-shrink: 0;
          justify-content: flex-end;
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
                    ${this._linksBlock(item, this._config.show_ebird, this._config.show_allaboutbirds, "row-links")}
                  </div>
                  <div class="detail">
                    ${item.image_url
                      ? `<img class="detail-photo" src="${_esc(item.image_url)}" alt="${_esc(item.species)}" loading="lazy">`
                      : `<div class="detail-photo-placeholder">🐦</div>`}
                    <div class="detail-text">
                      <div class="detail-name">${_esc(item.species)}</div>
                      ${item.scientific_name ? `<div class="detail-sci">${_esc(item.scientific_name)}</div>` : ""}
                      <div class="metrics">
                        ${item.count != null ? `<div class="metric"><strong>${_esc(item.count)}×</strong></div>` : ""}
                        ${t ? `<div class="metric">last heard <strong data-last-seen="${_esc(item.last_seen)}">${_esc(t)}</strong></div>` : ""}
                      </div>
                      ${this._linksBlock(item, true, true, "detail-links")}
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
