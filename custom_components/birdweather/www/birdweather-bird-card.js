// Seeded from ha-haikubox/haikubox-bird-card.js via scripts/sync-cards.sh, then
// FORKED — BirdWeather-only changes live here now (photo attribution; blur-fill
// image handling for BirdWeather's square photos). Hand-maintained: do NOT
// re-run sync-cards.sh over this file — it would drop those. See sync-cards.sh.
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

class BirdWeatherBirdCardEditor extends HTMLElement {
  // No shadow DOM — light DOM avoids isolation issues with ha-entity-picker

  setConfig(config) {
    this._config = config;
    if (!this._built) {
      this._built = true;
      this._init();
    } else {
      if (this._picker) this._picker.value = config.entity ?? "";
      if (this._positionField) this._positionField.value = config.position ?? 1;
      const ta = config.tap_action ?? { action: "more-info" };
      this._actionValue = ta.action ?? "more-info";
      this._pathValue = ta.navigation_path ?? ta.url_path ?? "";
      if (this._actionField) this._actionField.value = this._actionValue;
      if (this._pathField) {
        this._pathField.value = this._pathValue;
        this._syncPathField();
      }
      if (this._attrField) this._attrField.value = config.show_attribution !== false;
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._built = true;
      this._init();
    } else {
      if (this._picker) this._picker.hass = hass;
      if (this._positionField) this._positionField.hass = hass;
      if (this._actionField) this._actionField.hass = hass;
      if (this._pathField) this._pathField.hass = hass;
    }
  }

  _fire(update) {
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: { ...this._config, ...update } },
      bubbles: true,
      composed: true,
    }));
  }

  // Show the navigate/url path field only for those actions; relabel it
  // to match. Other actions (more-info, show-list, none) take no path.
  _syncPathField() {
    if (!this._pathField) return;
    if (this._actionValue === "navigate") {
      this._pathField.label = "Navigation path";
      this._pathField.style.display = "block";
    } else if (this._actionValue === "url") {
      this._pathField.label = "URL";
      this._pathField.style.display = "block";
    } else {
      this._pathField.style.display = "none";
    }
  }

  // Build the tap_action object from our action dropdown + path field and
  // fire it. navigate/url carry their path under the standard key names
  // so the card's _handleTapAction (and raw-YAML users) see a normal
  // tap_action schema.
  _fireAction() {
    const action = this._actionValue || "more-info";
    const ta = { action };
    if (action === "navigate") ta.navigation_path = this._pathValue || "";
    else if (action === "url") ta.url_path = this._pathValue || "";
    this._fire({ tap_action: ta });
  }

  async _init() {
    try {
      if (window.loadCardHelpers) await window.loadCardHelpers();
    } catch (_) { /* ignore */ }

    let field;
    if (customElements.get("ha-entity-picker")) {
      field = document.createElement("ha-entity-picker");
      field.label = "Entity";
      field.setAttribute("allow-custom-entity", "");
      field.includeDomains = ["sensor"];
      field.entityFilter = (state) => _isBirdWeatherListEntity(this._hass, state);
      if (this._hass) field.hass = this._hass;
      field.value = this._config?.entity ?? "";
      field.addEventListener("value-changed", (e) => this._fire({ entity: e.detail.value }));
    } else if (customElements.get("ha-selector")) {
      field = document.createElement("ha-selector");
      field.label = "Entity";
      field.selector = { entity: { domain: ["sensor"], integration: "birdweather" } };
      if (this._hass) field.hass = this._hass;
      field.value = this._config?.entity ?? "";
      field.addEventListener("value-changed", (e) => this._fire({ entity: e.detail.value }));
    } else {
      field = document.createElement("ha-textfield");
      field.label = "Entity ID";
      field.value = this._config?.entity ?? "";
      field.addEventListener("change", (e) => this._fire({ entity: e.target.value }));
    }
    field.style.cssText = "display:block;padding:0 16px 16px";
    this._picker = field;
    this.appendChild(field);

    // Position (1-based: 1 = top-ranked). For a column of single-bird
    // cards each showing a different rank from the same sensor.
    // Built with ha-selector (not ha-textfield) — ha-textfield isn't
    // reliably registered in the card-editor context across browsers
    // and renders invisibly, whereas ha-selector is always available.
    const pos = document.createElement("ha-selector");
    pos.label = "Position (1 = top-ranked)";
    pos.selector = { number: { min: 1, step: 1, mode: "box" } };
    if (this._hass) pos.hass = this._hass;
    pos.value = this._config?.position ?? 1;
    pos.style.cssText = "display:block;padding:0 16px 16px";
    pos.addEventListener("value-changed", (e) => {
      const v = parseInt(e.detail.value, 10);
      this._fire({ position: Number.isFinite(v) && v >= 1 ? v : 1 });
    });
    this._positionField = pos;
    this.appendChild(pos);

    // Tap action — our own picker (not HA's ui_action selector) so we can
    // offer "Show species list", a custom action HA's selector can't list.
    // navigate/url still set the standard path keys via _fireAction.
    if (customElements.get("ha-selector")) {
      const ta = this._config?.tap_action ?? { action: "more-info" };
      this._actionValue = ta.action ?? "more-info";
      this._pathValue = ta.navigation_path ?? ta.url_path ?? "";

      const action = document.createElement("ha-selector");
      action.label = "Tap action";
      action.selector = {
        select: {
          mode: "dropdown",
          options: [
            { value: "more-info", label: "More info" },
            { value: "show-list", label: "Show species list" },
            { value: "navigate", label: "Navigate" },
            { value: "url", label: "Open URL" },
            { value: "none", label: "None" },
          ],
        },
      };
      if (this._hass) action.hass = this._hass;
      action.value = this._actionValue;
      action.addEventListener("value-changed", (e) => {
        this._actionValue = e.detail.value;
        this._syncPathField();
        this._fireAction();
      });
      action.style.cssText = "display:block;padding:0 16px 16px";
      this._actionField = action;
      this.appendChild(action);

      const path = document.createElement("ha-selector");
      path.selector = { text: {} };
      if (this._hass) path.hass = this._hass;
      path.value = this._pathValue;
      path.style.cssText = "display:block;padding:0 16px 16px";
      path.addEventListener("value-changed", (e) => {
        this._pathValue = e.detail.value ?? "";
        this._fireAction();
      });
      this._pathField = path;
      this.appendChild(path);
      this._syncPathField();

      // Photo credit toggle (default on). The station photos are CC-licensed,
      // so the credit is normally required — hiding it may breach the licence.
      const attr = document.createElement("ha-selector");
      attr.label = "Show photo credit";
      attr.selector = { boolean: {} };
      if (this._hass) attr.hass = this._hass;
      attr.value = this._config?.show_attribution !== false;
      attr.style.cssText = "display:block;padding:0 16px 16px";
      attr.addEventListener("value-changed", (e) =>
        this._fire({ show_attribution: e.detail.value })
      );
      this._attrField = attr;
      this.appendChild(attr);
    }
  }
}

// Idempotent define: if the script gets loaded twice in the same page
// (cache flap during an HA upgrade, version-bust transient, etc.) a
// second `define` would throw and abort the script mid-execution,
// stranding window.customCards in an inconsistent state. The same
// guard appears around the card itself and customCards.push below.
if (!customElements.get("birdweather-bird-card-editor")) {
  customElements.define("birdweather-bird-card-editor", BirdWeatherBirdCardEditor);
}

// ── Card ──────────────────────────────────────────────────────────────────────

class BirdWeatherBirdCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  static getConfigElement() {
    return document.createElement("birdweather-bird-card-editor");
  }

  static getStubConfig() {
    return { entity: "", tap_action: { action: "more-info" }, position: 1 };
  }

  setConfig(config) {
    if (config.entity === undefined) throw new Error("'entity' is required");
    // `position` is 1-based: 1 = top-ranked bird, 2 = second, etc. Lets a
    // column of single-bird cards each show a different rank from the same
    // sensor. Coerced to a positive integer; anything invalid falls to 1.
    const p = parseInt(config.position, 10);
    const position = Number.isFinite(p) && p >= 1 ? p : 1;
    // tap_action follows HA's standard schema. Default to more-info
    // (HA's universal default for entity-bound cards); { action: "none" }
    // restores the card's previous inert behaviour.
    this._config = { tap_action: { action: "more-info" }, ...config, position };
  }

  // 0-based array index into detections[], derived from the 1-based
  // `position` config. Used by both _render and _fillTokens so the tap
  // action targets the same bird the card displays.
  _index() {
    return (this._config?.position ?? 1) - 1;
  }

  set hass(hass) {
    this._hass = hass;
    // Keep an open list popup live across polls.
    if (this._popupListCard && hass) this._popupListCard.hass = hass;
    const stateObj = hass?.states[this._config?.entity];
    // Gate on last_updated, not last_changed: this entity's state is a
    // species name that often stays constant across polls while the
    // attributes (image, timestamp) change. last_changed only moves when
    // .state changes, so it would freeze the card on attribute-only updates.
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

  // Lifecycle: a 60s ticker keeps the "5m ago" label honest between
  // polls. We don't re-render the whole card on the tick — just rewrite
  // the .time text node, which avoids image flicker and animation resets.
  connectedCallback() {
    if (this._timeTicker) return;  // already running (HA can disconnect/reconnect cards)
    this._timeTicker = setInterval(() => this._updateTime(), 60_000);
  }
  disconnectedCallback() {
    if (this._timeTicker) {
      clearInterval(this._timeTicker);
      this._timeTicker = null;
    }
    // Close a list popup if the card is torn down while it's open.
    if (this._popupDialog) this._popupDialog.close();
  }
  _updateTime() {
    if (!this._lastSeenIso || !this.shadowRoot) return;
    const el = this.shadowRoot.querySelector(".time");
    if (el) el.textContent = this._relativeTime(this._lastSeenIso);
  }

  _relativeTime(isoString) {
    if (!isoString) return "";
    // Clamp: a future timestamp (clock skew) must not show "-3s ago".
    const diff = Math.max(0, Math.floor((Date.now() - new Date(isoString)) / 1000));
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  _fillTokens(str) {
    // Pull tokens from the same detections[0] record _render shows, so a
    // tap_action URL like `…/{sp_code}` resolves to the actual bird the
    // user is looking at (not the sensor's sticky state, which may be
    // stale relative to the displayed record).
    //
    // `{species_slug}` is the common name with spaces converted to
    // underscores — the slug format used by sites like
    // allaboutbirds.org. Hyphens (e.g. "White-winged Dove") are
    // preserved by the transform and by URL encoding.
    const stateObj = this._hass?.states[this._config.entity];
    const attrs = stateObj?.attributes ?? {};
    const top = Array.isArray(attrs.detections) ? attrs.detections[this._index()] : null;
    const species = String(top?.species ?? "");
    const fields = {
      species,
      species_slug: species.replace(/ /g, "_"),
      sp_code: top?.sp_code ?? "",
      scientific_name: top?.scientific_name ?? "",
    };
    return String(str).replace(
      /\{(species|species_slug|sp_code|scientific_name)\}/g,
      (_, key) => encodeURIComponent(fields[key] ?? ""),
    );
  }

  _handleTapAction() {
    // Defensive: HA usually calls setConfig before any interaction, but
    // a tap that fires before setConfig completes would otherwise throw.
    if (!this._config) return;
    const cfg = this._config.tap_action ?? { action: "more-info" };
    const action = cfg.action ?? "more-info";
    if (action === "none") return;
    if (action === "more-info") {
      const entityId = cfg.entity ?? this._config.entity;
      if (!entityId) return;
      this.dispatchEvent(new CustomEvent("hass-more-info", {
        detail: { entityId },
        bubbles: true,
        composed: true,
      }));
    } else if (action === "navigate") {
      if (!cfg.navigation_path) return;
      history.pushState(null, "", this._fillTokens(cfg.navigation_path));
      window.dispatchEvent(new Event("location-changed"));
    } else if (action === "url") {
      if (!cfg.url_path) return;
      window.open(this._fillTokens(cfg.url_path), "_blank", "noreferrer");
    } else if (action === "show-list") {
      this._openListPopup();
    }
  }

  // Custom action: pop up a modal showing the full ranked species list
  // for this card's sensor, using the bird-list card. Native <dialog>
  // gives us a backdrop, focus trap, and ESC-to-close for free; no
  // external dependency (e.g. browser_mod) required.
  _openListPopup() {
    const entity = this._config?.entity;
    if (!entity || !customElements.get("birdweather-bird-list-card")) return;
    if (this._popupDialog) return;  // already open

    // One-time backdrop style (document-level; ::backdrop on a body-level
    // dialog can't be reached from our shadow DOM).
    if (!document.getElementById("birdweather-list-popup-style")) {
      const s = document.createElement("style");
      s.id = "birdweather-list-popup-style";
      s.textContent = "dialog.birdweather-list-popup::backdrop{background:rgba(0,0,0,0.55);}";
      document.head.appendChild(s);
    }

    const dialog = document.createElement("dialog");
    dialog.className = "birdweather-list-popup";
    dialog.style.cssText = [
      "padding:0", "border:none", "background:transparent",
      "overflow:visible", "color:inherit",
    ].join(";");

    const listCard = document.createElement("birdweather-bird-list-card");
    try {
      listCard.setConfig({ entity, top: 50, row_size: "large" });
    } catch (_) {
      return;
    }
    // Give the card a concrete box; its internal list scrolls past this.
    listCard.style.cssText = "display:block;width:min(92vw,560px);height:min(80vh,720px)";
    if (this._hass) listCard.hass = this._hass;

    dialog.appendChild(listCard);
    document.body.appendChild(dialog);

    // Backdrop click (target is the dialog itself, outside the card) closes.
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", () => {
      this._popupDialog = null;
      this._popupListCard = null;
      dialog.remove();
    });

    this._popupDialog = dialog;
    this._popupListCard = listCard;
    dialog.showModal();
  }

  // Photo credit/license caption. The coordinator sanitises BirdWeather's
  // (HTML) credit into plain text + a URL, so these are safe to link. Shown
  // because the station photos are CC-licensed and require attribution.
  _attributionHtml(bird) {
    const link = (text, url) =>
      url
        ? `<a href="${_esc(url)}" target="_blank" rel="noopener noreferrer">${_esc(text)}</a>`
        : _esc(text);
    const parts = [];
    if (bird.image_credit) parts.push(link(bird.image_credit, bird.image_credit_url));
    if (bird.image_license) parts.push(link(bird.image_license, bird.image_license_url));
    if (!parts.length) return "";
    return `<div class="attribution" title="Photo credit">📷 ${parts.join(" · ")}</div>`;
  }

  _render() {
    // Defensive: HA's card lifecycle is normally setConfig → set hass
    // (which calls _render), but during a reload or first-mount edge
    // case `set hass` can arrive before `setConfig` lands. Bail until
    // the config exists rather than throwing on `this._config.entity`.
    if (!this._config) return;
    const stateObj = this._hass?.states[this._config.entity];
    const attrs = stateObj?.attributes ?? {};
    // Every BirdWeather sensor exposes a ranked `detections` list under
    // each sensor's own ordering criterion. The top entry is the right
    // thing to show: highest count / rarest / most recent / etc. If the
    // list is empty (no data in the sensor's window), show empty rather
    // than substitute stale state — a blank card is honest signal that
    // something's gone wrong upstream (24h+ silence = likely hardware).
    // `position` (1-based) selects which ranked entry to show.
    const top = Array.isArray(attrs.detections) ? attrs.detections[this._index()] : null;
    const bird = top
      ? {
          species: top.species,
          image_url: top.image_url,
          scientific_name: top.scientific_name,
          last_seen: top.last_seen,
          image_credit: top.image_credit,
          image_credit_url: top.image_credit_url,
          image_license: top.image_license,
          image_license_url: top.image_license_url,
        }
      : null;
    const empty = !bird || !bird.species;
    const actionable = (this._config.tap_action?.action ?? "more-info") !== "none";
    // Stash for the 60s ticker so it can refresh just the .time element
    // without a full re-render.
    this._lastSeenIso = bird?.last_seen ?? null;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
          container-type: size;
        }
        ha-card {
          overflow: hidden;
          height: 100%;
          padding: 0;
        }
        ha-card.actionable { cursor: pointer; }
        ha-card.actionable:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: -2px;
        }
        .layout {
          display: flex;
          flex-direction: column;
          height: 100%;
          overflow: hidden;
        }

        /*
         * Portrait layout — three priorities when vertical space is tight:
         *  1. Crop the photo (fill full width, but no wider than 3:2 aspect ratio)
         *  2. Drop the scientific name   [portrait B query below]
         *  3. Shrink the photo to 3:2, centre horizontally  [portrait C query below]
         */
        .img-wrap {
          flex: 0 0 auto;
          position: relative;
          /*
           * Portrait: photo height = card width (square), but not more than
           * card height minus a text area. The reserve grows with card
           * height (clamped 72–160px) so the responsive species text below
           * has room to grow on large cards instead of being clipped.
           */
          height: min(100cqw, calc(100cqh - clamp(72px, 26cqh, 160px)));
          width: 100%;
          align-self: center;
          overflow: hidden;
          border-radius: var(--ha-card-border-radius, 4px)
            var(--ha-card-border-radius, 4px) 0 0;
        }
        /* Blur-fill: show the whole photo (contain) so the bird is never
         * cropped, over a blurred, zoomed copy of the same image that fills
         * the box. Aspect-agnostic — handles BirdWeather's 1:1 source (and any
         * other ratio) in any card shape without slicing off heads/feet. */
        .img-blur {
          position: absolute;
          inset: 0;
          z-index: 0;
          background-size: cover;
          background-position: center;
          filter: blur(16px) saturate(1.15);
          transform: scale(1.2);  /* overscan to hide the blurred edges */
        }
        img {
          display: block;
          position: relative;
          z-index: 1;
          width: 100%;
          height: 100%;
          object-fit: contain;
        }
        .img-placeholder {
          width: 100%;
          height: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--secondary-background-color);
          font-size: 3em;
        }
        /* Body fills remaining space; justify-content centres text vertically */
        .body {
          flex: 1 1 auto;
          min-height: 0;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 10px 16px;
          text-align: center;
        }

        /* Wide layout: image left, text right */
        @container (aspect-ratio > 3/2) {
          .layout { flex-direction: row; }
          .img-wrap {
            flex: 0 0 auto;
            align-self: stretch;
            border-radius: var(--ha-card-border-radius, 4px) 0 0
              var(--ha-card-border-radius, 4px);
            width: 100cqh; /* square: width = card height */
            height: 100%;  /* override portrait square formula */
          }
          .body {
            flex: 1 1 auto;
            min-height: 0;
            align-items: flex-start;
            text-align: left;
            padding: 16px 20px;
          }
          .text-group { align-items: flex-start; }
        }

        /*
         * Portrait priority 2: drop scientific name when card is wider than ~1:1.
         * max-aspect-ratio: 3/2 limits this rule to portrait mode only.
         */
        @container (min-aspect-ratio: 1.05) and (max-aspect-ratio: 3/2) {
          .scientific { display: none; }
        }

        /*
         * Portrait priority 3: card is too short for full-width 3:2 photo + text.
         * Shrink photo to 3:2, centre horizontally.
         * 54px ≈ 2-line body (20px padding + 18px species + 13px time + 3px gap).
         */
        @container (min-aspect-ratio: 1.2) and (max-aspect-ratio: 3/2) {
          .img-wrap {
            flex: 0 0 auto;
            height: calc(100cqh - clamp(54px, 20cqh, 120px));
            width: min(100cqw, calc((100cqh - clamp(54px, 20cqh, 120px)) * 1.5));
          }
        }

        .text-group {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 3px;
        }
        /*
         * Responsive type: sizes scale with the card via container-query
         * units (cqw/cqh) so the common name reads at a distance on large
         * cards but stays bounded on small ones. The common name is the
         * most aggressive; scientific name and timestamp scale gently to
         * keep the visual hierarchy. clamp(min, preferred, max) — min/max
         * in rem for predictability, preferred blends width and height.
         */
        .species {
          font-size: clamp(1.1rem, 4cqw + 2.5cqh, 2.8rem);
          font-weight: 600;
          line-height: 1.1;
          overflow-wrap: anywhere;
          color: var(--primary-text-color);
        }
        .scientific {
          font-size: clamp(0.8rem, 2.4cqw + 1.4cqh, 1.4rem);
          font-style: italic;
          line-height: 1.15;
          color: var(--secondary-text-color);
        }
        .time {
          font-size: clamp(0.75rem, 2cqw + 1.1cqh, 1.15rem);
          color: var(--secondary-text-color);
        }

        /* Wide layout: drop scientific / shrink fonts when card is very short */
        @container (aspect-ratio > 3/2) and (max-height: 71px) {
          .scientific { display: none; }
        }
        @container (aspect-ratio > 3/2) and (max-height: 51px) {
          .species { font-size: 0.95em; }
          .time { font-size: 0.72em; }
        }
        .empty {
          padding: 24px 16px;
          text-align: center;
          color: var(--secondary-text-color);
          font-style: italic;
        }
        /* Photo credit/license — required for the CC-licensed station photos. */
        .attribution {
          position: absolute;
          right: 0;
          bottom: 0;
          z-index: 2;  /* above the blur layer (0) and the photo (1) */
          max-width: 100%;
          box-sizing: border-box;
          padding: 1px 6px;
          font-size: clamp(0.6rem, 1.3cqw + 0.4cqh, 0.72rem);
          line-height: 1.3;
          color: #fff;
          background: rgba(0, 0, 0, 0.45);
          border-top-left-radius: 4px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .attribution a {
          color: inherit;
          text-decoration: underline;
        }
      </style>
      <ha-card class="${actionable ? "actionable" : ""}"${actionable ? ' role="button" tabindex="0"' : ""}>
        <div class="layout">
          ${empty ? `
            <div class="empty">No recent detections</div>
          ` : `
            <div class="img-wrap">
              ${bird.image_url
                ? `<div class="img-blur" style="background-image:url('${_esc(bird.image_url)}')"></div>
                   <img src="${_esc(bird.image_url)}" alt="${_esc(bird.species)}">`
                : `<div class="img-placeholder">🐦</div>`}
              ${bird.image_url && this._config.show_attribution !== false
                ? this._attributionHtml(bird)
                : ""}
            </div>
            <div class="body">
              <div class="text-group">
                <div class="species">${_esc(bird.species)}</div>
                <div class="scientific">${_esc(bird.scientific_name ?? "")}</div>
                <div class="time">${_esc(this._relativeTime(bird.last_seen))}</div>
              </div>
            </div>
          `}
        </div>
      </ha-card>
    `;

    // If the image fails to load (S3 404, network drop), swap in the
    // placeholder so users don't see the browser's broken-image glyph.
    const img = this.shadowRoot.querySelector(".img-wrap img");
    if (img) {
      img.addEventListener("error", () => {
        // Drop the blurred backdrop too (its background-image is the same
        // broken URL) so a failed load falls back cleanly to the placeholder.
        this.shadowRoot.querySelector(".img-wrap .img-blur")?.remove();
        const placeholder = document.createElement("div");
        placeholder.className = "img-placeholder";
        placeholder.textContent = "🐦";
        img.replaceWith(placeholder);
      });
    }

    // Let credit/license links work without also triggering the card's tap
    // action (more-info), and without keyboard activation bubbling up.
    this.shadowRoot.querySelectorAll(".attribution a").forEach((a) => {
      a.addEventListener("click", (e) => e.stopPropagation());
      a.addEventListener("keydown", (e) => e.stopPropagation());
    });

    if (actionable) {
      const card = this.shadowRoot.querySelector("ha-card");
      card.addEventListener("click", () => this._handleTapAction());
      card.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();  // Space would otherwise scroll the page
        this._handleTapAction();
      });
    }
  }

  getCardSize() {
    return 4;
  }

  getGridOptions() {
    // Sections grid is a 12-column scale (not the small scale the old
    // getLayoutOptions numbers assumed). Half-width photo card.
    return {
      columns: 6,
      rows: 4,
      min_columns: 4,
    };
  }
}

if (!customElements.get("birdweather-bird-card")) {
  customElements.define("birdweather-bird-card", BirdWeatherBirdCard);

  window.customCards ??= [];
  window.customCards.push({
    type: "birdweather-bird-card",
    name: "BirdWeather Bird Card",
    description: "Displays a BirdWeather bird detection with photo, species name, and timestamp.",
  });
}
