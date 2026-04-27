/* =========================================================
   Cybersecurity Conferences — App JS
   Handles: view switching, tag/search filtering,
            calendar rendering, Leaflet map, dark mode,
            copy-code buttons, back-to-top.
   ========================================================= */

(function () {
  "use strict";

  var events = window.CONFERENCES || [];

  // ── Helpers ──────────────────────────────────────────────

  function $(id) { return document.getElementById(id); }

  function formatDateRange(start, end) {
    var s = new Date(start + "T00:00:00");
    var e = new Date(end   + "T00:00:00");
    var opts = { day: "numeric", month: "short", year: "numeric" };
    if (start === end) return s.toLocaleDateString("en-GB", opts);
    if (s.getMonth() === e.getMonth() && s.getFullYear() === e.getFullYear()) {
      return s.getDate() + "–" + e.toLocaleDateString("en-GB", opts);
    }
    return s.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) +
           " – " + e.toLocaleDateString("en-GB", opts);
  }

  function monthName(year, month) {
    return new Date(year, month, 1).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
  }

  // ── State ─────────────────────────────────────────────────
  var state = {
    activeTag:    "",
    searchQuery:  "",
    calYear:      new Date().getFullYear(),
    calMonth:     new Date().getMonth(),
    currentView:  "list",
    mapInitialised: false,
  };

  // ── View switching ────────────────────────────────────────
  var viewBtns    = document.querySelectorAll(".view-toggle-btn");
  var viewPanels  = { list: $("view-list"), calendar: $("view-calendar"), map: $("view-map") };

  function showView(name) {
    state.currentView = name;
    viewBtns.forEach(function (btn) {
      var active = btn.dataset.view === name;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-pressed", String(active));
    });
    Object.keys(viewPanels).forEach(function (key) {
      var panel = viewPanels[key];
      if (!panel) return;
      panel.classList.toggle("view-content--active", key === name);
    });
    if (name === "calendar") renderCalendar(state.calYear, state.calMonth);
    if (name === "map" && !state.mapInitialised) initMap();
  }

  viewBtns.forEach(function (btn) {
    btn.addEventListener("click", function () { showView(btn.dataset.view); });
  });

  // ── Tag filter chips ──────────────────────────────────────
  var tagChips     = document.querySelectorAll(".tag-filter-bar .filter-chip");
  var clearFilters = document.querySelectorAll(".btn-clear-filters");
  var clearBtn     = $("clear-filters");

  function setTag(tag) {
    state.activeTag = tag;
    tagChips.forEach(function (chip) {
      var active = chip.dataset.tag === tag;
      chip.classList.toggle("active", active);
      chip.setAttribute("aria-pressed", String(active));
    });
    if (clearBtn) clearBtn.hidden = tag === "" && state.searchQuery === "";
    applyFilters();
  }

  tagChips.forEach(function (chip) {
    chip.addEventListener("click", function () { setTag(chip.dataset.tag); });
  });

  // Chips inside event cards
  document.querySelectorAll(".event-tags .tag-chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      showView("list");
      setTag(chip.dataset.tag);
    });
  });

  clearFilters.forEach(function (btn) {
    btn.addEventListener("click", function () {
      state.searchQuery = "";
      var searchEl = $("event-search");
      if (searchEl) searchEl.value = "";
      setTag("");
    });
  });

  // ── Search ────────────────────────────────────────────────
  var searchInput = $("event-search");
  if (searchInput) {
    searchInput.addEventListener("input", function () {
      state.searchQuery = searchInput.value.toLowerCase().trim();
      if (clearBtn) clearBtn.hidden = state.activeTag === "" && state.searchQuery === "";
      applyFilters();
    });
  }

  // ── Filter logic ──────────────────────────────────────────
  var eventCards   = document.querySelectorAll(".event-card");
  var noResults    = $("no-filter-results");
  var monthHeadings = document.querySelectorAll(".month-heading");

  function applyFilters() {
    var visible = 0;
    var visibleMonths = {};

    eventCards.forEach(function (card) {
      var tags  = (card.dataset.tags  || "").split(",");
      var name  = card.dataset.name   || "";
      var city  = card.dataset.city   || "";
      var ctry  = card.dataset.country || "";

      var tagMatch    = state.activeTag === "" || tags.indexOf(state.activeTag) !== -1;
      var searchMatch = state.searchQuery === "" ||
                        name.indexOf(state.searchQuery) !== -1 ||
                        city.indexOf(state.searchQuery) !== -1 ||
                        ctry.indexOf(state.searchQuery) !== -1;

      var show = tagMatch && searchMatch;
      card.hidden = !show;
      if (show) {
        visible++;
        // Determine which month heading this card falls under
        var prev = card.previousElementSibling;
        while (prev) {
          if (prev.classList.contains("month-heading")) {
            visibleMonths[prev.id || prev.textContent] = true;
            break;
          }
          prev = prev.previousElementSibling;
        }
      }
    });

    // Show/hide month headings
    monthHeadings.forEach(function (h) {
      h.hidden = !visibleMonths[h.id || h.textContent];
    });

    if (noResults) noResults.hidden = visible > 0;
  }

  // ── Calendar ──────────────────────────────────────────────
  var calPrev  = $("cal-prev");
  var calNext  = $("cal-next");
  var calLabel = $("cal-month-label");
  var calGrid  = $("calendar-grid");
  var calList  = $("cal-event-list");

  if (calPrev) {
    calPrev.addEventListener("click", function () {
      state.calMonth--;
      if (state.calMonth < 0) { state.calMonth = 11; state.calYear--; }
      renderCalendar(state.calYear, state.calMonth);
    });
  }
  if (calNext) {
    calNext.addEventListener("click", function () {
      state.calMonth++;
      if (state.calMonth > 11) { state.calMonth = 0; state.calYear++; }
      renderCalendar(state.calYear, state.calMonth);
    });
  }

  function eventsInMonth(year, month) {
    return events.filter(function (ev) {
      var s = new Date(ev.start_date + "T00:00:00");
      var e = new Date(ev.end_date   + "T00:00:00");
      var mStart = new Date(year, month, 1);
      var mEnd   = new Date(year, month + 1, 0);
      return s <= mEnd && e >= mStart;
    });
  }

  function eventsOnDay(year, month, day) {
    var d = new Date(year, month, day);
    return events.filter(function (ev) {
      var s = new Date(ev.start_date + "T00:00:00");
      var e = new Date(ev.end_date   + "T00:00:00");
      return s <= d && e >= d;
    });
  }

  function renderCalendar(year, month) {
    if (!calLabel || !calGrid) return;
    calLabel.textContent = monthName(year, month);

    var today     = new Date();
    var firstDay  = new Date(year, month, 1).getDay(); // 0=Sun
    var daysInMonth = new Date(year, month + 1, 0).getDate();

    var html = "";
    var dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    dayNames.forEach(function (d) {
      html += '<div class="cal-day-header">' + d + "</div>";
    });

    // Empty cells before first day
    for (var i = 0; i < firstDay; i++) {
      html += '<div class="cal-day cal-day--empty"></div>';
    }

    for (var d = 1; d <= daysInMonth; d++) {
      var isToday = today.getFullYear() === year && today.getMonth() === month && today.getDate() === d;
      var dayEvs  = eventsOnDay(year, month, d);
      var cls     = "cal-day" + (isToday ? " cal-day--today" : "");
      html += '<div class="' + cls + '" data-day="' + d + '">';
      html += '<div class="cal-day__num">' + d + "</div>";
      dayEvs.slice(0, 3).forEach(function (ev) {
        var ongoing = ev.start_date < (new Date(year, month, d).toISOString().slice(0, 10));
        var dotCls  = "cal-event-dot" + (ongoing ? " cal-event-dot--ongoing" : "");
        html += '<span class="' + dotCls + '" data-id="' + ev.id + '" title="' + ev.name + '">' + ev.name + "</span>";
      });
      if (dayEvs.length > 3) {
        html += '<span class="cal-event-dot" style="background:#64748b">+' + (dayEvs.length - 3) + ' more</span>';
      }
      html += "</div>";
    }
    calGrid.innerHTML = html;

    // Show this month's events in the list below
    var monthEvs = eventsInMonth(year, month);
    if (calList) {
      if (monthEvs.length === 0) {
        calList.innerHTML = "<p>No events in this month.</p>";
      } else {
        var listHtml = "<ul class='cal-event-list-items'>";
        monthEvs.forEach(function (ev) {
          listHtml += "<li><a href='" + ev.url + "' target='_blank' rel='noopener noreferrer'>" +
            "<strong>" + ev.name + "</strong></a> — " + ev.city + ", " + ev.country +
            " &middot; " + formatDateRange(ev.start_date, ev.end_date) + "</li>";
        });
        listHtml += "</ul>";
        calList.innerHTML = listHtml;
      }
    }

    // Click on dot → jump to list view card
    calGrid.querySelectorAll(".cal-event-dot[data-id]").forEach(function (dot) {
      dot.addEventListener("click", function () {
        showView("list");
        var card = document.getElementById("event-" + dot.dataset.id);
        if (card) {
          card.scrollIntoView({ behavior: "smooth", block: "center" });
          card.style.transition = "box-shadow 0.3s";
          card.style.boxShadow  = "0 0 0 3px #0d9488";
          setTimeout(function () { card.style.boxShadow = ""; }, 1500);
        }
      });
    });
  }

  // ── Map ───────────────────────────────────────────────────
  function initMap() {
    if (typeof L === "undefined") return;
    state.mapInitialised = true;

    var map = L.map("conferences-map").setView([20, 10], 2);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
      maxZoom: 18,
    }).addTo(map);

    var markerGroup = L.markerClusterGroup ? L.markerClusterGroup() : L.layerGroup();

    var tealIcon = L.divIcon({
      className: "conf-marker",
      html: "<div style='width:12px;height:12px;border-radius:50%;background:#0d9488;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,0.4)'></div>",
      iconSize:   [12, 12],
      iconAnchor: [6,  6],
    });
    var ongoingIcon = L.divIcon({
      className: "conf-marker",
      html: "<div style='width:14px;height:14px;border-radius:50%;background:#059669;border:2px solid #fff;box-shadow:0 0 0 3px rgba(5,150,105,0.3)'></div>",
      iconSize:   [14, 14],
      iconAnchor: [7,  7],
    });

    events.forEach(function (ev) {
      if (ev.lat == null || ev.lon == null) return;
      var icon = ev.status === "ongoing" ? ongoingIcon : tealIcon;
      var marker = L.marker([ev.lat, ev.lon], { icon: icon, title: ev.name });
      marker.bindPopup(
        "<strong>" + ev.name + "</strong><br>" +
        formatDateRange(ev.start_date, ev.end_date) + "<br>" +
        '<span style="color:#6b7280">' + ev.city + ", " + ev.country + "</span><br>" +
        '<a href="' + ev.url + '" target="_blank" rel="noopener noreferrer" style="color:#0d9488">Details &#8599;</a>'
      );
      markerGroup.addLayer(marker);
    });

    map.addLayer(markerGroup);
  }

  // ── Dynamic Europe/London date display ───────────────────

  (function () {
    if (!window.Intl || !Intl.DateTimeFormat) return;

    document.querySelectorAll(".js-london-time").forEach(function (el) {
      if (!el.dataset.utc) return;
      var dt = new Date(el.dataset.utc);
      if (isNaN(dt)) return;

      el.textContent = new Intl.DateTimeFormat("en-GB", {
        day: "numeric", month: "long", year: "numeric",
        timeZone: "Europe/London",
      }).format(dt);
    });
  }());

  // ── Dark mode toggle ──────────────────────────────────────
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

  // ── Copy-code buttons ─────────────────────────────────────
  document.querySelectorAll(".copy-code-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var pre = btn.parentElement.querySelector("code");
      if (!pre) return;
      navigator.clipboard.writeText(pre.textContent).then(function () {
        var orig = btn.textContent;
        btn.textContent = "Copied!";
        setTimeout(function () { btn.textContent = orig; }, 1500);
      });
    });
  });

  // ── Back to top ───────────────────────────────────────────
  var backToTop = $("back-to-top");
  if (backToTop) {
    window.addEventListener("scroll", function () {
      backToTop.hidden = window.scrollY < 400;
    }, { passive: true });
    backToTop.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  // ── Initialise ────────────────────────────────────────────
  renderCalendar(state.calYear, state.calMonth);

}());
