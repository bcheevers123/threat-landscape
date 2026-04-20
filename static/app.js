/* =========================================================
   Threat Landscape — Vanilla JS
   Handles: expand/collapse, STIX copy, search/filter, toast
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

  // ── Copy STIX JSON to clipboard ──────────────────────────

  var toast = document.getElementById("copy-toast");
  var toastTimer = null;

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toast.hidden = true;
    }, 2500);
  }

  document.querySelectorAll(".btn-stix--copy").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var idx = btn.dataset.stix;
      // Read from the visible <pre> — no duplicate hidden element needed
      var dataEl = document.getElementById("stix-pre-" + idx);
      if (!dataEl) return;

      var text = dataEl.textContent || "";
      if (!text.trim()) {
        showToast("No STIX data available.");
        return;
      }

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          showToast("STIX JSON copied to clipboard.");
        }, function () {
          fallbackCopy(text);
        });
      } else {
        fallbackCopy(text);
      }
    });
  });

  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try {
      document.execCommand("copy");
      showToast("STIX JSON copied to clipboard.");
    } catch (e) {
      showToast("Copy failed — try selecting and copying manually.");
    }
    document.body.removeChild(ta);
  }

  // ── View state ───────────────────────────────────────────

  var activeView = "technical";   // "technical" | "mainstream"

  // ── Search / filter ──────────────────────────────────────

  var searchInput         = document.getElementById("threat-search");
  var noResults           = document.getElementById("no-results");
  var clearFiltersBtn     = document.getElementById("clear-filters");
  var threatTypeContainer = document.getElementById("threat-type-filters");
  var sectorContainer     = document.getElementById("sector-filters");

  var activeThreatType = null;
  var activeSector     = null;

  function getActiveCards() {
    return document.querySelectorAll('.threat-card[data-stream="' + activeView + '"]');
  }

  // ── Build filter chips for the active view ───────────────

  function buildChips() {
    if (threatTypeContainer) threatTypeContainer.innerHTML = "";
    if (sectorContainer)     sectorContainer.innerHTML = "";

    var viewTypes   = new Set();
    var viewSectors = new Set();

    getActiveCards().forEach(function (card) {
      (card.dataset.threatTypes || "").split(",").forEach(function (t) {
        var trimmed = t.trim();
        if (trimmed && trimmed !== "other") viewTypes.add(trimmed);
      });
      (card.dataset.sectors || "").split(",").forEach(function (s) {
        var trimmed = s.trim();
        if (trimmed && trimmed !== "unknown") viewSectors.add(trimmed);
      });
    });

    var filterGroupTypes   = document.getElementById("filter-group-types");
    var filterGroupSectors = document.getElementById("filter-group-sectors");

    if (threatTypeContainer && viewTypes.size > 0) {
      if (filterGroupTypes) filterGroupTypes.hidden = false;
      Array.from(viewTypes).sort().forEach(function (typeVal) {
        var chip = makeChip(typeVal, "threat-type", threatTypeContainer, function (val) {
          if (activeThreatType === val) {
            activeThreatType = null;
          } else {
            activeThreatType = val;
            if (sectorContainer) sectorContainer.querySelectorAll(".filter-chip").forEach(deactivateChip);
            activeSector = null;
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
            activeThreatType = null;
          }
          applyFilter();
        });
        sectorContainer.appendChild(chip);
      });
    } else if (filterGroupSectors) {
      filterGroupSectors.hidden = true;
    }
  }

  // ── Filter logic ─────────────────────────────────────────

  function applyFilter() {
    var query       = searchInput ? searchInput.value.toLowerCase().trim() : "";
    var activeList  = document.getElementById("threat-list-" + activeView);
    var visibleCount = 0;

    getActiveCards().forEach(function (card) {
      var title       = (card.dataset.title || "").toLowerCase();
      var sectors     = (card.dataset.sectors || "").toLowerCase();
      var sources     = (card.dataset.sources || "").toLowerCase();
      var threatTypes = (card.dataset.threatTypes || "").toLowerCase();

      var matchesSearch = !query ||
        title.includes(query) || sectors.includes(query) ||
        sources.includes(query) || threatTypes.includes(query);

      var matchesThreatType = !activeThreatType ||
        threatTypes.split(",").some(function (t) { return t.trim() === activeThreatType; });

      var matchesSector = !activeSector ||
        sectors.split(",").some(function (s) { return s.trim() === activeSector; });

      if (matchesSearch && matchesThreatType && matchesSector) {
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
    if (threatTypeContainer) threatTypeContainer.querySelectorAll(".filter-chip").forEach(deactivateChip);
    if (sectorContainer)     sectorContainer.querySelectorAll(".filter-chip").forEach(deactivateChip);
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
      var techList = document.getElementById("threat-list-technical");
      var mainList = document.getElementById("threat-list-mainstream");
      if (techList) techList.hidden = (activeView !== "technical");
      if (mainList) mainList.hidden = (activeView !== "mainstream");

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

  // Build chips on load for the default view
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
      // Toggle this chip
      var wasActive = chip.classList.contains("active");
      // Deactivate all chips in this container
      container.querySelectorAll(".filter-chip").forEach(deactivateChip);
      if (!wasActive) {
        chip.classList.add("active");
        chip.setAttribute("aria-pressed", "true");
        onClick(value);
      } else {
        onClick(value);  // toggles the active state off
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
  // Source cards carry data-stream="technical|mainstream|both".
  // When the view toggles, only cards relevant to that view are shown.
  // Within the visible set, the first 6 are shown by default; the rest
  // are hidden behind the "Show more" button.

  var sourcesToggle    = document.getElementById("sources-toggle");
  var sourcesToggleRow = document.getElementById("sources-toggle-row");
  var sourcesCountEl   = document.getElementById("sources-count");
  var allSourceCards   = Array.from(document.querySelectorAll(".source-card[data-stream]"));
  var sourcesExpanded  = false;

  function getViewSourceCards() {
    return allSourceCards.filter(function (card) {
      var s = card.dataset.stream || "technical";
      return s === activeView || s === "both";
    });
  }

  function applySourceView() {
    sourcesExpanded = false;
    if (sourcesToggle) {
      sourcesToggle.setAttribute("aria-expanded", "false");
    }

    var visible = getViewSourceCards();
    var overflow = visible.slice(6);

    // Hide all first, then reveal the right ones
    allSourceCards.forEach(function (card) { card.hidden = true; });
    visible.forEach(function (card, i) {
      card.hidden = (i >= 6 && !sourcesExpanded);
    });

    // Update count text
    if (sourcesCountEl) sourcesCountEl.textContent = visible.length;

    // Show/hide the "Show more" row
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
  // Processed independently per list so both get a full crimson→amber sweep.

  ["technical", "mainstream"].forEach(function (view) {
    var listEl = document.getElementById("threat-list-" + view);
    if (!listEl) return;
    var viewCards = listEl.querySelectorAll(".threat-card");
    var total     = Math.max(viewCards.length - 1, 1);
    viewCards.forEach(function (card, index) {
      var badge  = card.querySelector(".rank-badge");
      var t      = index / total;                     // 0 at #1, 1 at last
      var hue    = Math.round(t * 35);                // 0 (red) → 35 (amber)
      var sat    = Math.round(78 - t * 12);           // 78% → 66%
      var lit    = Math.round(34 + t * 14);           // 34% → 48%
      var colour = "hsl(" + hue + "," + sat + "%," + lit + "%)";
      if (badge) badge.style.background = colour;
      card.style.borderLeftColor = colour;
    });
  });

  // ── Score tooltip ────────────────────────────────────────
  // Appended to <body> so it escapes the card's overflow:hidden.
  // Stays visible when the cursor moves into it (delay-based hide),
  // allowing the user to hover dimension labels for sub-explanations.

  var DIM_EXPLAIN = {
    recency:
      "How recently the story was published. Items under 6 hours score highest; " +
      "anything older than 48 hours loses most recency credit. Max weight: 0.25.",
    source_credibility:
      "Credibility of the primary source, rated 0\u2013100 based on outlet quality, " +
      "editorial standards, and track record. Higher-rated outlets carry more weight. Max weight: 0.20.",
    corroboration:
      "Number of independent sources that reported the same story. Multiple " +
      "outlets covering the same event increases analytical confidence. Max weight: 0.15.",
    severity:
      "Signals of operational impact: presence of CVEs, active exploitation " +
      "evidence, ransomware or malware activity, and high-severity advisory keywords. Max weight: 0.20.",
    breadth:
      "How widely the threat affects different sectors, countries, or organisations. " +
      "Threats with broad cross-sector or cross-country impact score higher. Max weight: 0.10.",
    actionability:
      "Whether the story contains concrete defensive actions \u2014 patches, " +
      "mitigations, IOCs, or official advisories that allow an immediate response. Max weight: 0.10.",
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

  // Keep popup alive while the cursor is inside it
  scorePopup.addEventListener("mouseenter", cancelHide);
  scorePopup.addEventListener("mouseleave", scheduleHide);

  document.querySelectorAll(".card-score").forEach(function (scoreEl) {
    var dataEl = scoreEl.querySelector(".score-tooltip-data");
    if (!dataEl) return;
    scoreEl.addEventListener("mouseenter", function () { showPopup(scoreEl, dataEl); });
    scoreEl.addEventListener("mouseleave", scheduleHide);
  });

  // ── Dimension label explainability in detail-panel breakdown ──
  // Adds dotted underline + CSS sub-tooltip to each .score-dim-name.

  document.querySelectorAll(".score-dim[data-dim] .score-dim-name").forEach(function (nameEl) {
    var dimEl   = nameEl.closest("[data-dim]");
    if (!dimEl) return;
    var explain = DIM_EXPLAIN[dimEl.dataset.dim];
    if (!explain) return;
    nameEl.setAttribute("data-explain", explain);
    nameEl.classList.add("has-explain");
  });

  // ── Countdown to next 09:00 UTC refresh ─────────────────

  (function () {
    var el = document.getElementById("refresh-countdown");
    if (!el) return;
    function pad2(n) { return ("0" + n).slice(-2); }
    function tick() {
      var now    = new Date();
      var next   = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 9, 0, 0));
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
  // Definitions for every threat-type badge label.  Lookup is
  // case-insensitive against the badge's trimmed text content.

  var THREAT_TYPE_TIPS = {
    "ransomware":
      "Malicious software that encrypts a victim\u2019s data and demands payment " +
      "for the decryption key. Modern variants use double extortion \u2014 " +
      "exfiltrating data before encrypting it.",
    "wiper":
      "Destructive malware designed to permanently erase data or disable systems, " +
      "with no recovery mechanism. Frequently deployed in nation-state attacks against critical infrastructure.",
    "bec":
      "Business Email Compromise \u2014 fraud that impersonates executives or suppliers " +
      "to authorise fraudulent payments or redirect sensitive data transfers.",
    "supply chain":
      "Attacks that compromise software vendors, open-source packages, or build pipelines " +
      "to reach many downstream victims through a single trusted entry point.",
    "phishing":
      "Social-engineering attacks that trick users into revealing credentials or " +
      "installing malware, delivered via deceptive emails (phishing), SMS (smishing), " +
      "or voice calls (vishing).",
    "ddos":
      "Distributed Denial of Service \u2014 overwhelming a target with traffic from " +
      "many sources to make it unavailable to legitimate users.",
    "zero-day":
      "A vulnerability that is unknown to the vendor and has no available patch. " +
      "Attackers can exploit it freely until a fix is released.",
    "apt":
      "Advanced Persistent Threat \u2014 a sophisticated, long-running intrusion " +
      "typically by a nation-state or well-resourced group, aimed at espionage or sabotage.",
    "credential theft":
      "Techniques for stealing usernames and passwords \u2014 brute force, credential " +
      "stuffing, phishing, or memory-dump tools such as Mimikatz.",
    "cryptojacking":
      "Unauthorised use of a victim\u2019s compute resources to mine cryptocurrency, " +
      "often deployed via malicious scripts or vulnerable cloud workloads.",
    "data breach":
      "Unauthorised access and exfiltration of sensitive data \u2014 customer records, " +
      "credentials, or intellectual property \u2014 typically for financial gain or extortion.",
    "web shell":
      "A script uploaded to a compromised web server that gives an attacker persistent " +
      "remote access and command execution over HTTP.",
    "malware":
      "General-purpose malicious software \u2014 trojans, backdoors, " +
      "loaders, and rootkits that do not fit a more specific category.",
    "vulnerability":
      "A security flaw in software or hardware that can be exploited to gain " +
      "unauthorised access, escalate privileges, or execute arbitrary code.",
    "social engineering":
      "Manipulation techniques that exploit human trust rather than technical flaws \u2014 " +
      "pretexting, whaling, QR-code phishing (quishing), and impersonation attacks.",
    "exploitation":
      "Active, in-the-wild abuse of a known vulnerability, often via exploit kits or " +
      "chained techniques, before many defenders have applied the available patch.",
    "insider threat":
      "Damage caused by a malicious or negligent employee, contractor, or privileged user " +
      "who misuses legitimate access to systems or data.",
    "mfa bypass":
      "Techniques that circumvent multi-factor authentication \u2014 including MFA fatigue " +
      "(push bombing), SIM swapping, SS7 attacks, and adversary-in-the-middle proxies.",
    "cloud attack":
      "Attacks targeting cloud infrastructure \u2014 misconfigured storage buckets, " +
      "cloud account takeover, container escapes, and compromise of AWS, Azure, or GCP workloads.",
    "ot/ics":
      "Attacks against Operational Technology or Industrial Control Systems \u2014 " +
      "SCADA networks, PLCs, and the cyber-physical systems that run factories, " +
      "utilities, and critical infrastructure.",
    "infostealer":
      "Malware designed specifically to harvest credentials, browser cookies, crypto wallets, " +
      "and sensitive files \u2014 examples include Lumma, Raccoon Stealer, and RedLine.",
    "botnet":
      "A network of compromised devices controlled by a threat actor via command-and-control " +
      "infrastructure, used for spam, DDoS, credential stuffing, or distributing further malware.",
    "watering hole":
      "An attack where a threat actor compromises a website frequented by a target audience, " +
      "then uses it to deliver drive-by malware to visitors.",
    "typosquatting":
      "Registering lookalike domain names or publishing malicious packages to repositories " +
      "(npm, PyPI) to catch users who mistype a trusted name.",
    "malvertising":
      "Delivery of malware via online advertising networks or SEO poisoning, causing " +
      "malicious code to execute when a user clicks a seemingly legitimate advert or search result.",
    "disinformation":
      "Coordinated information operations \u2014 influence campaigns, propaganda, and " +
      "cognitive warfare aimed at shaping public opinion or undermining trust in institutions.",
    "other":
      "A security incident or threat that does not fit a standard category based " +
      "on the available source information.",
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

  document.querySelectorAll(".threat-type-badge").forEach(function (badge) {
    var key = badge.textContent.trim().toLowerCase();
    var tip = THREAT_TYPE_TIPS[key];
    if (!tip) return;
    badge.setAttribute("data-tip", "1");
    badge.addEventListener("mouseenter", function () { showTagTooltip(badge, tip); });
    badge.addEventListener("mouseleave", hideTagTooltip);
  });

})();
