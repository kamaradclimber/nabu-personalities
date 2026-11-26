(() => {
  const CARD_TAG = "assist-voice-pipeline-card";
  if (customElements.get(CARD_TAG)) return;

  const escapeHtml = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");

  class AssistVoicePipelineCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
    }

    setConfig(config) {
      this.config = config;
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      this._render();
    }

    getCardSize() {
      return 8;
    }

    _render() {
      if (!this.shadowRoot || !this.config || !this._hass) return;

      const topologyId =
        this.config.entity || "sensor.assist_voice_pipeline_topology";
      const state = this._hass.states[topologyId];
      if (!state) {
        this.shadowRoot.innerHTML = `<ha-card><div class="empty">Waiting for ${escapeHtml(topologyId)}</div></ha-card>`;
        return;
      }

      const attrs = state.attributes || {};
      const voice = attrs.assist_voice || {};
      const router = voice.personality_router || {};
      const currentBackend = router.current_backend || {};
      const upstream = voice.wyoming_bridge?.upstream_stt || {};
      const speakerStt = voice.speaker_id_stt || {};
      const guardedStt = voice.guarded_stt || {};
      const timeout = voice.timeouts || {};
      const stages = attrs.stages || [];
      const findStage = (name) => stages.find((stage) => stage.stage === name) || {};
      const wake = findStage("Wake word");
      const stt = findStage("Speech-to-text");
      const conversation = findStage("Conversation");
      const tts = findStage("Text-to-speech");
      const rotateButton = voice.rotate_button?.entity_id;
      const detailsEntity = topologyId;

      const node = ({
        eyebrow,
        title,
        detail,
        entityId,
        badge,
        classes = "",
      }) => `
        <button class="node ${classes}" type="button" data-entity="${escapeHtml(entityId || detailsEntity)}">
          <span class="eyebrow">${escapeHtml(eyebrow)}</span>
          <strong>${escapeHtml(title || "Not configured")}</strong>
          <span class="detail">${escapeHtml(detail || "")}</span>
          ${badge ? `<span class="badge">${escapeHtml(badge)}</span>` : ""}
          <span class="more">Open details ↗</span>
        </button>`;

      const connector = (label = "") => `
        <div class="connector" aria-hidden="true">
          ${label ? `<span>${escapeHtml(label)}</span>` : ""}<b>→</b>
        </div>`;

      const flow = (items, labels = []) => `
        <div class="flow">
          ${items
            .map(
              (item, index) =>
                `${node(item)}${index < items.length - 1 ? connector(labels[index]) : ""}`,
            )
            .join("")}
        </div>`;

      const entity = (stage) => stage.entity || {};
      const sttActive = Boolean(voice.stt_path_configured);
      const bridge = voice.wyoming_bridge || {};
      const bridgeAddress = `${bridge.host || "?"}:${bridge.port || "?"}`;
      const responseTimeout = timeout.response_after_audio_seconds ?? "?";
      const maxTimeout = timeout.max_request_seconds ?? "?";
      const backends = router.backends || [];
      const backendButtons = backends
        .map((backend) => {
          if (!backend) return "";
          const isCurrent = backend.entity_id === currentBackend.entity_id;
          return `<button class="backend ${isCurrent ? "current" : ""}" type="button" data-entity="${escapeHtml(backend.entity_id)}">${escapeHtml(backend.name)}${isCurrent ? " · current" : ""}</button>`;
        })
        .join("");

      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; }
          ha-card { padding: 20px; color: var(--primary-text-color); }
          .header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 18px; }
          h2 { font-size: 1.15rem; line-height: 1.35; margin: 0; }
          .subtitle, .detail, .note { color: var(--secondary-text-color); }
          .subtitle { font-size: .88rem; margin-top: 4px; }
          h3 { font-size: 1rem; margin: 22px 0 10px; }
          .flow { display: flex; align-items: stretch; gap: 8px; overflow-x: auto; padding: 2px 2px 8px; }
          .node { position: relative; display: flex; flex: 1 0 145px; min-height: 126px; flex-direction: column; align-items: flex-start; text-align: left; gap: 7px; padding: 13px; border: 1px solid var(--divider-color); border-top: 4px solid var(--primary-color); border-radius: 12px; color: var(--primary-text-color); background: var(--card-background-color); cursor: pointer; font: inherit; }
          .node:hover, .backend:hover { background: var(--secondary-background-color); }
          .node.active { border-top-color: var(--success-color, #2e7d32); }
          .node.inactive { opacity: .58; }
          .eyebrow { color: var(--secondary-text-color); font-size: .72rem; letter-spacing: .06em; text-transform: uppercase; }
          .node strong { font-size: .92rem; line-height: 1.3; }
          .detail { font-size: .8rem; line-height: 1.35; overflow-wrap: anywhere; }
          .badge { padding: 4px 7px; border-radius: 999px; color: var(--warning-color, #8a4b00); background: var(--warning-color, #f4c86a); background: color-mix(in srgb, var(--warning-color, #f4c86a) 22%, transparent); font-size: .73rem; font-weight: 600; }
          .more { margin-top: auto; color: var(--primary-color); font-size: .72rem; }
          .connector { display: flex; flex: 0 0 50px; flex-direction: column; justify-content: center; align-items: center; gap: 4px; color: var(--primary-color); }
          .connector span { color: var(--secondary-text-color); font-size: .67rem; text-align: center; }
          .connector b { font-size: 1.45rem; }
          .section { border-top: 1px solid var(--divider-color); margin-top: 18px; padding-top: 2px; }
          .callout { border-left: 4px solid var(--warning-color, #d99b00); border-radius: 4px; padding: 10px 12px; background: var(--secondary-background-color); font-size: .88rem; line-height: 1.5; }
          .note { font-size: .8rem; margin: 8px 0 12px; line-height: 1.45; }
          .backends { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 12px; }
          .backend { border: 1px solid var(--divider-color); border-radius: 999px; padding: 7px 10px; color: var(--primary-text-color); background: transparent; cursor: pointer; font: inherit; font-size: .8rem; }
          .backend.current { border-color: var(--primary-color); background: color-mix(in srgb, var(--primary-color) 15%, transparent); font-weight: 600; }
          .rotate { border: 0; border-radius: 8px; padding: 9px 12px; color: var(--text-primary-color, white); background: var(--primary-color); cursor: pointer; font: inherit; font-size: .82rem; font-weight: 600; }
          .rotate:disabled { opacity: .5; cursor: not-allowed; }
          .empty { padding: 20px; color: var(--secondary-text-color); }
          @media (max-width: 650px) {
            ha-card { padding: 14px; }
            .header { flex-direction: column; }
            .flow { flex-direction: column; overflow: visible; }
            .node { flex: 1 1 auto; min-height: 0; }
            .connector { flex: 0 0 auto; min-height: 28px; }
            .connector b { transform: rotate(90deg); }
          }
        </style>
        <ha-card>
          <div class="header">
            <div>
              <h2>${escapeHtml(attrs.pipeline_name || state.state || "Assist pipeline")}</h2>
              <div class="subtitle">${escapeHtml(attrs.pipeline_language || "")}</div>
            </div>
            <button class="rotate" type="button" ${rotateButton ? "" : "disabled"}>Rotate personality</button>
          </div>

          <h3>Assist pipeline</h3>
          ${flow(
            [
              { eyebrow: "Wake word", title: entity(wake).name || wake.wake_word_id || "Not configured", detail: wake.wake_word_id || "", entityId: entity(wake).entity_id },
              { eyebrow: "Speech-to-text", title: entity(stt).name || "Not configured", detail: stt.language || "", entityId: entity(stt).entity_id, classes: sttActive ? "active" : "" },
              { eyebrow: "Conversation", title: entity(conversation).name || "Not configured", detail: conversation.language || "", entityId: entity(conversation).entity_id },
              { eyebrow: "Text-to-speech", title: entity(tts).name || "Not configured", detail: [tts.language, tts.voice].filter(Boolean).join(" · "), entityId: entity(tts).entity_id },
            ],
            ["audio", "transcript", "response"],
          )}

          <div class="section">
            <h3>Speech-to-text handoff</h3>
            <div class="callout">
              ${sttActive ? "This pipeline uses Assist Voice's timeout-protected STT path." : "This preferred pipeline does not currently use Assist Voice's guarded STT entity."}
              Timeout limits: up to <strong>${escapeHtml(maxTimeout)} seconds</strong> per request, and <strong>${escapeHtml(responseTimeout)} seconds</strong> waiting after audio ends.
            </div>
            <p class="note">Assist Voice delegates to the Speaker ID STT entity. The Speaker ID integration then calls its server over HTTP; that server sends audio to the Wyoming bridge, which proxies the configured Home Assistant STT provider.</p>
            ${flow(
              [
                { eyebrow: "Assist Voice", title: guardedStt.name || "Timeout-protected STT", detail: `Timeout guard · ${maxTimeout}s max / ${responseTimeout}s after audio`, entityId: guardedStt.entity_id, badge: "TIMEOUT", classes: sttActive ? "active" : "inactive" },
                { eyebrow: "HA entity", title: speakerStt.name || "Speaker ID STT", detail: "Delegates to Speaker ID server", entityId: speakerStt.entity_id },
                { eyebrow: "HTTP call", title: "Speaker ID server", detail: "Called by the Speaker ID integration", entityId: speakerStt.entity_id },
                { eyebrow: "Wyoming", title: `Bridge · ${bridgeAddress}`, detail: "Assist Voice STT proxy", entityId: detailsEntity },
                { eyebrow: "Upstream", title: upstream.name || "Configured HA STT", detail: upstream.entity_id || "", entityId: upstream.entity_id },
              ],
              ["delegates", "HTTP", "Wyoming", "transcribes"],
            )}
          </div>

          <div class="section">
            <h3>Conversation and personality</h3>
            <p class="note">The Speaker ID conversation agent's target is configured separately. When it targets this router, new conversations use the selected personality; existing sessions stay with their original backend.</p>
            ${flow(
              [
                { eyebrow: "Pipeline", title: entity(conversation).name || "Conversation agent", detail: entity(conversation).entity_id || "", entityId: entity(conversation).entity_id },
                { eyebrow: "Assist Voice", title: router.entity?.name || "Personality router", detail: router.pipeline_uses_router_directly ? "Used directly by this pipeline" : "Configure as the Speaker ID agent target", entityId: router.entity?.entity_id },
                { eyebrow: "Selected", title: currentBackend.name || "No backend", detail: currentBackend.entity_id || "", entityId: currentBackend.entity_id, classes: "active" },
              ],
              [router.pipeline_uses_router_directly ? "routes" : "target configured separately", "routes new sessions to"],
            )}
            <div class="backends">${backendButtons}</div>
            <p class="note">Personality rotation affects new sessions only; the TTS engine and voice remain those configured on the Assist pipeline.</p>
          </div>
        </ha-card>`;

      this.shadowRoot.querySelectorAll("[data-entity]").forEach((element) => {
        element.addEventListener("click", () => {
          const entityId = element.dataset.entity;
          if (entityId) {
            this.dispatchEvent(
              new CustomEvent("hass-more-info", {
                detail: { entityId },
                bubbles: true,
                composed: true,
              }),
            );
          }
        });
      });

      this.shadowRoot.querySelector(".rotate")?.addEventListener("click", () => {
        if (rotateButton) {
          this._hass.callService("button", "press", { entity_id: rotateButton });
        }
      });
    }
  }

  customElements.define(CARD_TAG, AssistVoicePipelineCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD_TAG,
    name: "Assist Voice Pipeline",
    description: "Clickable diagram of an Assist Voice pipeline and its handoffs.",
  });
})();
