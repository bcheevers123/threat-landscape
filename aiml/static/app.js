/* =========================================================
   ML/AI Landscape — Vanilla JS
   Adapted from Threat Landscape app.js.
   Handles: expand/collapse, search/filter, view toggle,
            source cards, score tooltip, rank heatmap.
   ========================================================= */

(function () {
  "use strict";

  // ── Expand / collapse detail panels ─────────────────────

  document.querySelectorAll(".expand-toggle").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var idx = btn.dataset.idx;
      var panel = document.getElementById("detail-" + idx);
      if (!panel) return;

      var expanded = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", String(!expanded));
      panel.hidden = expanded;
    });
  });

  // ── View state ───────────────────────────────────────────

  var activeView = "ml";   // "ml" | "ai"

  // ── Search / filter ──────────────────────────────────────

  var searchInput         = document.getElementById("threat-search");
  var noResults           = document.getElementById("no-results");
  var clearFiltersBtn     = document.getElementById("clear-filters");
  var threatTypeContainer = document.getElementById("threat-type-filters");
  var sectorContainer     = document.getElementById("sector-filters");
  var companyContainer    = document.getElementById("company-filters");

  var activeThreatType = null;
  var activeSector     = null;
  var activeCompany    = null;

  function getActiveCards() {
    return document.querySelectorAll('.threat-card[data-stream="' + activeView + '"]');
  }

  // ── Build filter chips for the active view ───────────────

  function buildChips() {
    if (threatTypeContainer) threatTypeContainer.innerHTML = "";
    if (sectorContainer)     sectorContainer.innerHTML = "";
    if (companyContainer)    companyContainer.innerHTML = "";

    var viewTypes     = new Set();
    var viewSectors   = new Set();
    var viewCompanies = new Set();

    getActiveCards().forEach(function (card) {
      (card.dataset.threatTypes || "").split(",").forEach(function (t) {
        var trimmed = t.trim();
        if (trimmed && trimmed !== "other" && trimmed !== "ai/ml") viewTypes.add(trimmed);
      });
      (card.dataset.sectors || "").split(",").forEach(function (s) {
        var trimmed = s.trim();
        if (trimmed && trimmed !== "unknown") viewSectors.add(trimmed);
      });
      (card.dataset.companies || "").split(",").forEach(function (c) {
        var trimmed = c.trim();
        if (trimmed) viewCompanies.add(trimmed);
      });
    });

    var filterGroupTypes     = document.getElementById("filter-group-types");
    var filterGroupSectors   = document.getElementById("filter-group-sectors");
    var filterGroupCompanies = document.getElementById("filter-group-companies");

    if (threatTypeContainer && viewTypes.size > 0) {
      if (filterGroupTypes) filterGroupTypes.hidden = false;
      Array.from(viewTypes).sort().forEach(function (typeVal) {
        var chip = makeChip(typeVal, "threat-type", threatTypeContainer, function (val) {
          if (activeThreatType === val) {
            activeThreatType = null;
          } else {
            activeThreatType = val;
            if (sectorContainer)  sectorContainer.querySelectorAll(".filter-chip").forEach(deactivateChip);
            if (companyContainer) companyContainer.querySelectorAll(".filter-chip").forEach(deactivateChip);
            activeSector = null;
            activeCompany = null;
          }
          applyFilter();
        });
        threatTypeContainer.appendChild(chip);
      });
    } else if (filterGroupTypes) {
      filterGroupTypes.hidden = true;
    }

    if (sectorContainer && viewSectors.size > 0) {
      if (filterGroupSectors) filterGroupSectors.hidden = false;
      Array.from(viewSectors).sort().forEach(function (sectorVal) {
        var chip = makeChip(sectorVal, "sector", sectorContainer, function (val) {
          if (activeSector === val) {
            activeSector = null;
          } else {
            activeSector = val;
            if (threatTypeContainer) threatTypeContainer.querySelectorAll(".filter-chip").forEach(deactivateChip);
            if (companyContainer)    companyContainer.querySelectorAll(".filter-chip").forEach(deactivateChip);
            activeThreatType = null;
            activeCompany = null;
          }
          applyFilter();
        });
        sectorContainer.appendChild(chip);
      });
    } else if (filterGroupSectors) {
      filterGroupSectors.hidden = true;
    }

    if (companyContainer && viewCompanies.size > 0) {
      if (filterGroupCompanies) filterGroupCompanies.hidden = false;
      Array.from(viewCompanies).sort().forEach(function (companyVal) {
        var chip = makeChip(companyVal, "company", companyContainer, function (val) {
          if (activeCompany === val) {
            activeCompany = null;
          } else {
            activeCompany = val;
            if (threatTypeContainer) threatTypeContainer.querySelectorAll(".filter-chip").forEach(deactivateChip);
            if (sectorContainer)     sectorContainer.querySelectorAll(".filter-chip").forEach(deactivateChip);
            activeThreatType = null;
            activeSector = null;
          }
          applyFilter();
        });
        companyContainer.appendChild(chip);
      });
    } else if (filterGroupCompanies) {
      filterGroupCompanies.hidden = true;
    }
  }

  // ── Filter logic ─────────────────────────────────────────

  function applyFilter() {
    var query      = searchInput ? searchInput.value.toLowerCase().trim() : "";
    var activeList = document.getElementById("threat-list-" + activeView);
    var visibleCount = 0;

    getActiveCards().forEach(function (card) {
      var title       = (card.dataset.title || "").toLowerCase();
      var sectors     = (card.dataset.sectors || "").toLowerCase();
      var sources     = (card.dataset.sources || "").toLowerCase();
      var threatTypes = (card.dataset.threatTypes || "").toLowerCase();
      var companies   = (card.dataset.companies || "").toLowerCase();

      var matchesSearch = !query ||
        title.includes(query) || sectors.includes(query) ||
        sources.includes(query) || threatTypes.includes(query) ||
        companies.includes(query);

      var matchesThreatType = !activeThreatType ||
        threatTypes.split(",").some(function (t) { return t.trim() === activeThreatType; });

      var matchesSector = !activeSector ||
        sectors.split(",").some(function (s) { return s.trim() === activeSector; });

      var matchesCompany = !activeCompany ||
        companies.split(",").some(function (c) { return c.trim() === activeCompany; });

      if (matchesSearch && matchesThreatType && matchesSector && matchesCompany) {
        card.hidden = false;
        visibleCount++;
      } else {
        card.hidden = true;
      }
    });

    if (noResults) noResults.hidden = visibleCount > 0;
    if (activeList) activeList.hidden = visibleCount === 0;
  }

  if (searchInput) {
    searchInput.addEventListener("input", applyFilter);
  }

  function doClearFilters() {
    if (searchInput) searchInput.value = "";
    activeThreatType = null;
    activeSector     = null;
    activeCompany    = null;
    if (threatTypeContainer) threatTypeContainer.querySelectorAll(".filter-chip").forEach(deactivateChip);
    if (sectorContainer)     sectorContainer.querySelectorAll(".filter-chip").forEach(deactivateChip);
    if (companyContainer)    companyContainer.querySelectorAll(".filter-chip").forEach(deactivateChip);
    applyFilter();
  }

  if (clearFiltersBtn) {
    clearFiltersBtn.addEventListener("click", doClearFilters);
  }

  document.querySelectorAll(".js-clear-filters").forEach(function (btn) {
    btn.addEventListener("click", doClearFilters);
  });

  // ── View toggle ──────────────────────────────────────────

  document.querySelectorAll(".view-toggle-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var newView = btn.dataset.view;
      if (newView === activeView) return;

      activeView = newView;

      // Update button states
      document.querySelectorAll(".view-toggle-btn").forEach(function (b) {
        var on = b.dataset.view === activeView;
        b.classList.toggle("active", on);
        b.setAttribute("aria-pressed", String(on));
      });

      // Show the correct list, hide the other
      var mlList = document.getElementById("threat-list-ml");
      var aiList = document.getElementById("threat-list-ai");
      if (mlList) mlList.hidden = (activeView !== "ml");
      if (aiList) aiList.hidden = (activeView !== "ai");

      // Reset filters, rebuild chips for new view
      activeThreatType = null;
      activeSector     = null;
      if (searchInput) searchInput.value = "";
      buildChips();
      applyFilter();

      // Update the sources section for the new view
      applySourceView();
    });
  });

  // Build chips on load for the default (ML) view
  buildChips();

  // ── Utilities ────────────────────────────────────────────

  function makeChip(value, filterGroup, container, onClick) {
    var chip = document.createElement("button");
    chip.className = "filter-chip";
    chip.textContent = titleCase(value);
    chip.dataset.filterGroup = filterGroup;
    chip.dataset.filterValue = value;
    chip.setAttribute("aria-pressed", "false");
    chip.addEventListener("click", function () {
      var wasActive = chip.classList.contains("active");
      container.querySelectorAll(".filter-chip").forEach(deactivateChip);
      if (!wasActive) {
        chip.classList.add("active");
        chip.setAttribute("aria-pressed", "true");
        onClick(value);
      } else {
        onClick(value);
      }
    });
    return chip;
  }

  function deactivateChip(chip) {
    chip.classList.remove("active");
    chip.setAttribute("aria-pressed", "false");
  }

  function titleCase(str) {
    return str.replace(/-/g, " ").replace(/\b\w/g, function (c) {
      return c.toUpperCase();
    });
  }

  // ── Keyboard: Escape clears search ──────────────────────
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && searchInput && document.activeElement === searchInput) {
      searchInput.value = "";
      applyFilter();
    }
  });

  // ── Sources expand / collapse (view-aware) ───────────────
  // Source cards carry data-stream="ml|ai|both".
  // "both" cards are shown in both views.

  var sourcesToggle    = document.getElementById("sources-toggle");
  var sourcesToggleRow = document.getElementById("sources-toggle-row");
  var sourcesCountEl   = document.getElementById("sources-count");
  var allSourceCards   = Array.from(document.querySelectorAll(".source-card[data-stream]"));
  var sourcesExpanded  = false;

  function getViewSourceCards() {
    return allSourceCards.filter(function (card) {
      var s = card.dataset.stream || "ml";
      return s === activeView || s === "both";
    });
  }

  function applySourceView() {
    sourcesExpanded = false;
    if (sourcesToggle) {
      sourcesToggle.setAttribute("aria-expanded", "false");
    }

    var visible  = getViewSourceCards();
    var overflow = visible.slice(6);

    allSourceCards.forEach(function (card) { card.hidden = true; });
    visible.forEach(function (card, i) {
      card.hidden = (i >= 6 && !sourcesExpanded);
    });

    if (sourcesCountEl) sourcesCountEl.textContent = visible.length;

    if (sourcesToggleRow) {
      sourcesToggleRow.hidden = overflow.length === 0;
    }
    if (sourcesToggle) {
      sourcesToggle.textContent = "Show " + overflow.length + " more sources";
    }
  }

  if (sourcesToggle) {
    sourcesToggle.addEventListener("click", function () {
      sourcesExpanded = !sourcesExpanded;
      var visible = getViewSourceCards();
      visible.forEach(function (card, i) {
        card.hidden = (i >= 6 && !sourcesExpanded);
      });
      sourcesToggle.setAttribute("aria-expanded", String(sourcesExpanded));
      var overflow = visible.slice(6);
      sourcesToggle.textContent = sourcesExpanded
        ? "Show fewer sources"
        : "Show " + overflow.length + " more sources";
    });
  }

  // Run on page load
  applySourceView();

  // ── Rank badge heatmap colouring ────────────────────────
  // Violet (#1) → indigo/blue (#10) — matches the AI/ML theme.
  // Processed independently per list so both get a full sweep.

  ["ml", "ai"].forEach(function (view) {
    var listEl = document.getElementById("threat-list-" + view);
    if (!listEl) return;
    var viewCards = listEl.querySelectorAll(".threat-card");
    var total     = Math.max(viewCards.length - 1, 1);
    viewCards.forEach(function (card, index) {
      var badge  = card.querySelector(".rank-badge");
      var t      = index / total;
      var hue    = Math.round(265 - t * 55);   // 265 (violet) → 210 (blue)
      var sat    = Math.round(78 - t * 14);    // 78% → 64%
      var lit    = Math.round(42 + t * 14);    // 42% → 56%
      var colour = "hsl(" + hue + "," + sat + "%," + lit + "%)";
      if (badge) badge.style.background = colour;
      card.style.borderLeftColor = colour;
    });
  });

  // ── Score tooltip ────────────────────────────────────────

  var DIM_EXPLAIN = {
    recency:
      "How recently the story was published. Items under 12 hours score highest; " +
      "arXiv papers and major announcements lose relevance quickly as follow-up " +
      "coverage arrives. Max weight varies by pool (ML: 0.20, AI: 0.25).",
    source_credibility:
      "Credibility of the primary source, rated 0\u2013100 based on editorial rigour, " +
      "peer-review backing, and track record. arXiv (0.95) and major lab blogs (0.88\u20130.92) " +
      "score highest. Max weight: 0.28 (ML), 0.22 (AI).",
    corroboration:
      "Number of independent sources that covered the same story. A paper reported " +
      "across multiple outlets or a model release picked up by several publications " +
      "scores higher. Max weight: 0.12 (ML), 0.28 (AI).",
    severity:
      "Significance signals: breakthrough or state-of-the-art claims, open-weights " +
      "releases, jailbreak or safety disclosures, major funding rounds, regulation " +
      "events, or frontier-model announcements. " +
      "Max weight: 0.25 (ML), 0.13 (AI).",
    breadth:
      "How widely the story affects different industries or sectors — healthcare, " +
      "finance, education, government, climate science, and others. " +
      "Cross-industry developments score higher. Max weight: 0.10 (ML), 0.08 (AI).",
    actionability:
      "Whether the story contains something directly usable: an open-source release, " +
      "model weights on Hugging Face, a public API or demo, a tutorial, or a " +
      "runnable notebook. Max weight: 0.05 (ML), 0.04 (AI).",
  };

  function escAttr(s) {
    return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;")
            .replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function escHTML(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function buildPopupHTML(dataEl) {
    var rows   = dataEl.querySelectorAll("tr[data-dim]");
    var vals   = [];
    rows.forEach(function (r) { vals.push(parseFloat(r.cells[1].textContent) || 0); });
    var maxVal = Math.max.apply(null, vals) || 1;

    var totalEl = dataEl.querySelector(".stt-total");
    var html    = "<p class=\"stt-total\">" + (totalEl ? escHTML(totalEl.textContent) : "") + "</p>";
    html += "<table class=\"stt-table\">";

    rows.forEach(function (r, i) {
      var dim     = r.dataset.dim || "";
      var label   = r.cells[0].textContent.trim();
      var val     = vals[i];
      var barW    = Math.round((val / maxVal) * 52);
      var explain = DIM_EXPLAIN[dim] || "";

      html += "<tr><td>";
      if (explain) {
        html += "<span class=\"stt-dim-label\" data-explain=\"" + escAttr(explain) + "\">" +
                escHTML(label) + "</span>";
      } else {
        html += escHTML(label);
      }
      html += "</td><td>";
      html += "<span class=\"stt-bar\" style=\"width:" + barW + "px\"></span>";
      html += val.toFixed(3);
      html += "</td></tr>";
    });

    html += "</table>";
    return html;
  }

  var scorePopup  = document.createElement("div");
  scorePopup.className = "score-tooltip-popup";
  scorePopup.hidden    = true;
  document.body.appendChild(scorePopup);

  var hideTimer = null;

  function cancelHide() { clearTimeout(hideTimer); }

  function scheduleHide() {
    hideTimer = setTimeout(function () { scorePopup.hidden = true; }, 120);
  }

  function showPopup(scoreEl, dataEl) {
    cancelHide();
    scorePopup.innerHTML = buildPopupHTML(dataEl);
    scorePopup.hidden    = false;

    var rect = scoreEl.getBoundingClientRect();
    var popW = scorePopup.offsetWidth;
    var popH = scorePopup.offsetHeight;
    var vpH  = window.innerHeight;

    var top  = rect.bottom + 8;
    if (top + popH > vpH - 8) top = rect.top - popH - 8;
    var left = rect.right - popW;
    if (left < 8) left = 8;

    scorePopup.style.top  = top  + "px";
    scorePopup.style.left = left + "px";
  }

  scorePopup.addEventListener("mouseenter", cancelHide);
  scorePopup.addEventListener("mouseleave", scheduleHide);

  document.querySelectorAll(".card-score").forEach(function (scoreEl) {
    var dataEl = scoreEl.querySelector(".score-tooltip-data");
    if (!dataEl) return;
    scoreEl.addEventListener("mouseenter", function () { showPopup(scoreEl, dataEl); });
    scoreEl.addEventListener("mouseleave", scheduleHide);
  });

  // ── Dimension label explainability in detail-panel breakdown ──

  document.querySelectorAll(".score-dim[data-dim] .score-dim-name").forEach(function (nameEl) {
    var dimEl   = nameEl.closest("[data-dim]");
    if (!dimEl) return;
    var explain = DIM_EXPLAIN[dimEl.dataset.dim];
    if (!explain) return;
    nameEl.setAttribute("data-explain", explain);
    nameEl.classList.add("has-explain");
  });

  // ── Countdown to next 07:00 GMT refresh ─────────────────

  (function () {
    var el = document.getElementById("refresh-countdown");
    if (!el) return;
    function pad2(n) { return ("0" + n).slice(-2); }
    function tick() {
      var now    = new Date();
      var next   = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 7, 0, 0));
      if (now >= next) next = new Date(next.getTime() + 86400000);
      var diff   = next - now;
      var h      = Math.floor(diff / 3600000);
      var m      = Math.floor((diff % 3600000) / 60000);
      var s      = Math.floor((diff % 60000) / 1000);
      el.textContent = h + "h " + pad2(m) + "m " + pad2(s) + "s";
    }
    tick();
    setInterval(tick, 1000);
  }());

  // ── Dark mode toggle ─────────────────────────────────────

  (function () {
    var btn    = document.getElementById("dark-mode-toggle");
    var htmlEl = document.documentElement;

    if (localStorage.getItem("darkMode") === "1") {
      htmlEl.setAttribute("data-dark", "true");
    }

    if (btn) {
      btn.addEventListener("click", function () {
        var isDark = htmlEl.getAttribute("data-dark") === "true";
        if (isDark) {
          htmlEl.removeAttribute("data-dark");
          localStorage.removeItem("darkMode");
        } else {
          htmlEl.setAttribute("data-dark", "true");
          localStorage.setItem("darkMode", "1");
        }
      });
    }
  }());

  // ── Copy-code buttons (feed tutorial) ───────────────────
  document.querySelectorAll(".copy-code-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var code = btn.parentElement.querySelector("code");
      if (!code) return;
      navigator.clipboard.writeText(code.textContent).then(function () {
        var orig = btn.textContent;
        btn.textContent = "Copied!";
        setTimeout(function () { btn.textContent = orig; }, 1500);
      });
    });
  });

  // ── Back to top ──────────────────────────────────────────

  var backToTop = document.getElementById("back-to-top");

  if (backToTop) {
    window.addEventListener("scroll", function () {
      backToTop.hidden = window.scrollY < 400;
    }, { passive: true });

    backToTop.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  // ── Tag hover tooltips ───────────────────────────────────
  // Covers both topic-type badges (Research, Model Release …)
  // and ML technique badges (LLM, Diffusion Model …).
  // Lookup is case-insensitive against trimmed badge text.

  var BADGE_TIPS = {
    // ── Topic types ─────────────────────────────────────────
    "research":
      "Academic or lab research output \u2014 a pre-print, published paper, or " +
      "benchmark evaluation presenting new findings to the community.",
    "model release":
      "A new AI model or significant version made publicly available, with or " +
      "without open weights \u2014 from GPT-4o to open-source LLaMA releases.",
    "safety & alignment":
      "Findings or work relating to AI safety, alignment, jailbreaks, harmful " +
      "outputs, red-teaming, or responsible deployment of AI systems.",
    "regulation & policy":
      "Government legislation, policy proposals, enforcement actions, or governance " +
      "frameworks that affect how AI is built, deployed, or procured.",
    "product launch":
      "A new AI-powered product, feature, API, or service released to users by " +
      "a company or research lab.",
    "investment":
      "Funding rounds, acquisitions, mergers, or other significant financial events " +
      "shaping the AI industry landscape.",
    "infrastructure":
      "AI compute hardware, data centre construction, training clusters, or chip " +
      "developments that underpin frontier model work.",
    "ethics & privacy":
      "Ethical concerns, privacy implications, bias, copyright disputes, or " +
      "accountability issues arising from AI systems.",
    "deepfake":
      "AI-generated synthetic media \u2014 fake images, video, audio, or text " +
      "used to mislead, entertain, or impersonate.",
    "ai/ml":
      "A general AI or ML development that does not fit a more specific topic category.",

    // ── ML technique families ───────────────────────────────
    "llm":
      "Large Language Model \u2014 transformer-based neural networks trained on vast " +
      "text corpora for generation, reasoning, and instruction following " +
      "(e.g. GPT-4, LLaMA, Claude, Gemini).",
    "diffusion model":
      "Generative models that learn to reverse a gradual noising process to produce " +
      "high-quality images, audio, or video from random noise " +
      "(e.g. Stable Diffusion, DALL\u00b7E 3, Sora).",
    "reinforcement learning":
      "Training agents through reward signals and environment interaction. Includes " +
      "RLHF \u2014 using human preference feedback to fine-tune language models.",
    "computer vision":
      "ML applied to visual data: image classification, object detection, semantic " +
      "segmentation, depth estimation, and 3D scene understanding.",
    "graph learning":
      "Neural networks that operate on graph-structured data \u2014 knowledge graphs, " +
      "molecular graphs, citation networks, and social networks.",
    "clustering":
      "Unsupervised methods that discover natural groupings in data, including " +
      "k-means, contrastive learning, and self-supervised representation learning.",
    "ensemble methods":
      "Combining multiple models to outperform any individual one. Covers Random " +
      "Forests, Gradient Boosting, XGBoost, LightGBM, and Decision Forests.",
    "multimodal":
      "Models that jointly process and relate multiple data types \u2014 text, images, " +
      "audio, and video \u2014 within a single unified architecture.",
    "robotics":
      "ML applied to physical systems: robot learning, locomotion control, " +
      "manipulation, sim-to-real transfer, and embodied AI.",
    "federated learning":
      "Training ML models across decentralised devices or organisations without " +
      "sharing raw data, preserving user privacy.",
    "gan":
      "Generative Adversarial Network \u2014 a generator and discriminator compete " +
      "to produce realistic synthetic data. Also covers Variational Autoencoders (VAEs).",
    "rag":
      "Retrieval-Augmented Generation \u2014 grounding a language model\u2019s responses " +
      "in retrieved external documents via a vector search step, reducing hallucination.",
    "ai agent":
      "Autonomous AI systems that plan and execute multi-step tasks using tools, " +
      "APIs, web browsing, or code execution with minimal human intervention.",
    "fine-tuning":
      "Adapting a pre-trained model to a specific task with additional training. " +
      "Includes efficient methods like LoRA, PEFT, instruction tuning, and " +
      "knowledge distillation.",
  };

  var tagTooltipEl = document.createElement("div");
  tagTooltipEl.className = "tag-tooltip";
  tagTooltipEl.hidden    = true;
  document.body.appendChild(tagTooltipEl);

  var tagHideTimer = null;

  function showTagTooltip(badge, tipText) {
    clearTimeout(tagHideTimer);
    tagTooltipEl.textContent = tipText;
    tagTooltipEl.hidden = false;

    var rect = badge.getBoundingClientRect();
    var vpW  = window.innerWidth;
    var vpH  = window.innerHeight;

    tagTooltipEl.style.top  = "0";
    tagTooltipEl.style.left = "0";
    var tw = tagTooltipEl.offsetWidth;
    var th = tagTooltipEl.offsetHeight;

    var top  = rect.bottom + 6;
    var left = rect.left;
    if (top + th > vpH - 8)  top  = rect.top - th - 6;
    if (left + tw > vpW - 8) left = vpW - tw - 8;
    if (left < 8)            left = 8;

    tagTooltipEl.style.top  = top  + "px";
    tagTooltipEl.style.left = left + "px";
  }

  function hideTagTooltip() {
    tagHideTimer = setTimeout(function () { tagTooltipEl.hidden = true; }, 80);
  }

  // Wire all threat-type badges (card header pills + detail-panel badge--malware pills)
  document.querySelectorAll(".threat-type-badge, .badge--malware").forEach(function (badge) {
    var key = badge.textContent.trim().toLowerCase();
    var tip = BADGE_TIPS[key];
    if (!tip) return;
    badge.setAttribute("data-tip", "1");
    badge.addEventListener("mouseenter", function () { showTagTooltip(badge, tip); });
    badge.addEventListener("mouseleave", hideTagTooltip);
  });

})();
