(() => {
  "use strict";

  const SESSION_KEY_NAME = "aleph_api_key";
  const LOCAL_KEY_NAME = "aleph_api_key_saved";

  const state = {
    apiKey: "",
    ready: null,
    allocationsPayload: null,
    stands: [],
    metricsPayload: null,
    issuesPayload: null,
    opsStats: null,
    activeTab: "overview",
    ganttType: "ALL",
    ganttSize: "ALL",
    ganttQuery: "",
    showBuffer: true,
    flightStatus: "ALL",
    flightSize: "ALL",
    flightQuery: "",
    standType: "ALL",
    issueAction: "ALL",
  };

  // DOM helpers
  const $ = (id) => document.getElementById(id);

  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatUtcTime(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toISOString().slice(11, 16);
  }

  function formatDuration(arrIso, depIso) {
    const mins = Math.round((new Date(depIso) - new Date(arrIso)) / 60000);
    if (mins < 60) return `${mins}m`;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return m === 0 ? `${h}h` : `${h}h ${m}m`;
  }

  function formatUptime(sec) {
    if (sec < 60) return `${Math.round(sec)}s`;
    if (sec < 3600) return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`;
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    return `${h}h ${m}m`;
  }

  function loadStoredKey() {
    return (
      sessionStorage.getItem(SESSION_KEY_NAME) ||
      localStorage.getItem(LOCAL_KEY_NAME) ||
      ""
    );
  }

  function saveStoredKey(key, remember) {
    sessionStorage.setItem(SESSION_KEY_NAME, key);
    if (remember) {
      localStorage.setItem(LOCAL_KEY_NAME, key);
    } else {
      localStorage.removeItem(LOCAL_KEY_NAME);
    }
  }

  function clearStoredKey() {
    sessionStorage.removeItem(SESSION_KEY_NAME);
    localStorage.removeItem(LOCAL_KEY_NAME);
  }

  async function apiFetch(path) {
    const headers = {};
    if (state.apiKey) {
      headers["X-API-Key"] = state.apiKey;
    }
    const res = await fetch(path, { headers });
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try {
        const errBody = await res.json();
        if (errBody && errBody.error && errBody.error.message) {
          msg = errBody.error.message;
        }
      } catch (_) {
        // ignore JSON parse failure
      }
      const err = new Error(msg);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  // ==================== READINESS & AUTH ====================
  async function checkReadiness() {
    const chip = $("readyChip");
    const readyText = $("readyText");
    const authBadgeText = $("authReadySummary");

    try {
      const res = await fetch("/ready");
      const data = await res.json();
      state.ready = data;
      if (res.ok && data.status === "ready") {
        chip.className = "status-chip ready";
        readyText.textContent = `Ready • ${data.run_id}`;
        authBadgeText.textContent =
          `${data.stands} stands • ${data.valid_flights} flights • ${data.primary_method.toUpperCase()} (${data.solver_status})`;
      } else {
        chip.className = "status-chip error";
        readyText.textContent = "Not Ready";
        authBadgeText.textContent = "Server not ready";
      }
    } catch (_) {
      chip.className = "status-chip error";
      readyText.textContent = "Offline";
      authBadgeText.textContent = "Unable to reach server";
    }
  }

  function showAuth(errorMessage) {
    $("authSection").hidden = false;
    $("appContent").hidden = true;
    $("navTabs").hidden = true;
    $("refreshBtn").hidden = true;
    $("keyBtn").hidden = true;

    if (errorMessage) {
      $("authErrorText").textContent = errorMessage;
      $("authError").hidden = false;
    } else {
      $("authError").hidden = true;
    }
  }

  function showApp() {
    $("authSection").hidden = true;
    $("appContent").hidden = false;
    $("navTabs").hidden = false;
    $("refreshBtn").hidden = false;
    $("keyBtn").hidden = false;
  }

  async function loadAllData() {
    try {
      const [allocations, stands, metrics, issues, ops] = await Promise.all([
        apiFetch("/allocations?limit=500"),
        apiFetch("/stands"),
        apiFetch("/metrics"),
        apiFetch("/data-issues?limit=500"),
        apiFetch("/ops/stats"),
      ]);
      state.allocationsPayload = allocations;
      state.stands = stands;
      state.metricsPayload = metrics;
      state.issuesPayload = issues;
      state.opsStats = ops;

      $("tabCountFlights").textContent = String(allocations.total);
      $("tabCountStands").textContent = String(stands.length);
      $("tabCountIssues").textContent = String(issues.count);

      showApp();
      renderAll();
    } catch (err) {
      if (err.status === 401) {
        clearStoredKey();
        state.apiKey = "";
        showAuth("Invalid or missing API key. Please enter a valid X-API-Key.");
      } else if (err.status === 429) {
        showAuth(err.message || "Rate limited. Please wait a few seconds and retry.");
      } else {
        showAuth(err.message || "Failed to load dashboard data.");
      }
    }
  }

  // ==================== RENDERING ====================
  function renderAll() {
    renderOverview();
    renderGantt();
    renderMetricsTable();
    renderFlightsTable();
    renderStandsGrid();
    renderAuditAndOps();
  }

  function getMetric(id) {
    return state.metricsPayload.metrics.find((m) => m.id === id);
  }

  function renderOverview() {
    const alloc = state.allocationsPayload;
    const winStart = formatUtcTime(alloc.planning_window.start);
    const winEnd = formatUtcTime(alloc.planning_window.end);
    $("windowSubtitle").textContent =
      `Planning window: ${alloc.planning_window.start.slice(0, 10)} • ${winStart}–${winEnd} UTC`;

    const solveText =
      state.ready && typeof state.ready.solve_seconds === "number"
        ? ` (${state.ready.solve_seconds.toFixed(2)}s)`
        : "";
    $("solverPills").innerHTML = `
      <span class="meta-pill">Run: ${escapeHtml(alloc.run_id)}</span>
      <span class="meta-pill">Method: ${escapeHtml(alloc.primary_method.toUpperCase())}</span>
      <span class="meta-pill">Solver: ${escapeHtml(alloc.solver_status)}${escapeHtml(solveText)}</span>
      <span class="meta-pill">Buffer: ${escapeHtml(alloc.buffer_minutes ?? 15)}m</span>
    `;

    const m1 = getMetric("M1");
    const m2 = getMetric("M2");
    const m3 = getMetric("M3");
    const m4 = getMetric("M4");
    const m5 = getMetric("M5");
    const m6 = getMetric("M6");
    const m7 = getMetric("M7");
    const m8 = getMetric("M8");

    const assignedCount = m1 ? Math.round(m1.value) : 0;
    const totalFlights = alloc.total || 0;
    const assignedPct = totalFlights > 0 ? ((assignedCount / totalFlights) * 100).toFixed(1) : "0.0";
    const plbCount = alloc.allocations.filter(
      (a) => a.status === "ASSIGNED" && a.stand_type === "PLB"
    ).length;

    const kpis = [
      {
        label: "Assigned Flights",
        value: `${assignedCount} / ${totalFlights}`,
        sub: `<span class="kpi-highlight">${assignedPct}% placed</span> • +${Math.round(m8?.value || 0)} vs greedy`,
      },
      {
        label: "PLB Contact Gates",
        value: `${plbCount}`,
        sub: `<span class="kpi-highlight">+${Math.round(m7?.value || 0)} PLB gained</span> over baseline`,
      },
      {
        label: "Peak Demand & Utilisation",
        value: `${Math.round(m3?.value || 0)} stands`,
        sub: `${m4?.value ?? 0}% stand utilisation across window`,
      },
      {
        label: "Unassigned & Tight Turns",
        value: `${Math.round(m2?.value || 0)} unplaced`,
        sub: `${Math.round(m5?.value || 0)} tight turns (&lt;30m) • ${Math.round(m6?.value || 0)} oversized`,
      },
    ];

    $("kpiGrid").innerHTML = kpis
      .map(
        (k) => `
      <div class="kpi-card">
        <div class="kpi-label">${k.label}</div>
        <div class="kpi-value">${escapeHtml(k.value)}</div>
        <div class="kpi-sub">${k.sub}</div>
      </div>`
      )
      .join("");
  }

  function renderGantt() {
    const board = $("ganttBoard");
    const alloc = state.allocationsPayload;
    const winStartMs = new Date(alloc.planning_window.start).getTime();
    const winEndMs = new Date(alloc.planning_window.end).getTime();
    const spanMs = winEndMs - winStartMs;
    const bufferMins = alloc.buffer_minutes ?? 15;
    const bufferMs = bufferMins * 60 * 1000;
    const legendEl = $("bufferLegendText");
    if (legendEl) legendEl.textContent = `${bufferMins}m Buffer`;

    // Extract peak time if present in M3 window string (e.g. "first reached at 09:15 UTC")
    const m3 = getMetric("M3");
    let peakPct = null;
    if (m3 && m3.window) {
      const match = m3.window.match(/(\d{2}):(\d{2})\s*UTC/);
      if (match) {
        const datePrefix = alloc.planning_window.start.slice(0, 11);
        const peakMs = new Date(`${datePrefix}${match[1]}:${match[2]}:00Z`).getTime();
        peakPct = ((peakMs - winStartMs) / spanMs) * 100;
      }
    }

    const stands = state.stands.filter(
      (s) => state.ganttType === "ALL" || s.stand_type === state.ganttType
    );

    const byStand = new Map();
    for (const s of stands) byStand.set(s.stand_id, []);
    for (const a of alloc.allocations) {
      if (a.status === "ASSIGNED" && a.stand_id && byStand.has(a.stand_id)) {
        byStand.get(a.stand_id).push(a);
      }
    }

    const ticks = [];
    for (let h = 0; h <= 6; h += 1) {
      const t = new Date(winStartMs + h * 3600000);
      const pct = (h / 6) * 100;
      ticks.push(`<span class="gantt-tick" style="left:${pct}%">${t.toISOString().slice(11, 16)}</span>`);
    }

    const query = state.ganttQuery.trim().toLowerCase();

    const rowsHtml = stands
      .map((s) => {
        const flights = byStand.get(s.stand_id) || [];
        const barsHtml = flights
          .map((f) => {
            const arrMs = new Date(f.arrival_time).getTime();
            const depMs = new Date(f.departure_time).getTime();
            const leftPct = Math.max(0, ((arrMs - winStartMs) / spanMs) * 100);
            const rightPct = Math.min(100, ((depMs - winStartMs) / spanMs) * 100);
            const widthPct = Math.max(1.2, rightPct - leftPct);

            const bufEndPct = Math.min(100, ((depMs + bufferMs - winStartMs) / spanMs) * 100);
            const bufWidthPct = Math.max(0, bufEndPct - rightPct);

            const matchesSize = state.ganttSize === "ALL" || f.aircraft_size === state.ganttSize;
            const matchesQuery = !query || f.flight_id.toLowerCase().includes(query);
            const dimmed = !(matchesSize && matchesQuery);
            const barClass = s.stand_type === "PLB" ? "plb" : "remote";

            const bufferEl =
              state.showBuffer && bufWidthPct > 0.2
                ? `<div class="gantt-buffer" style="left:${rightPct.toFixed(2)}%;width:${bufWidthPct.toFixed(2)}%"></div>`
                : "";

            return `
              ${bufferEl}
              <div
                class="gantt-bar ${barClass} ${dimmed ? "dimmed" : ""}"
                style="left:${leftPct.toFixed(2)}%;width:${widthPct.toFixed(2)}%"
                data-flight-id="${escapeHtml(f.flight_id)}"
                data-stand-id="${escapeHtml(s.stand_id)}"
              >
                <span>${escapeHtml(f.flight_id)}</span>
                <span>${escapeHtml(f.aircraft_size)}</span>
              </div>
            `;
          })
          .join("");

        const peakLine =
          peakPct !== null && peakPct >= 0 && peakPct <= 100
            ? `<div class="gantt-peak-line" style="left:${peakPct.toFixed(2)}%"></div>`
            : "";

        const typeBadge =
          s.stand_type === "PLB"
            ? `<span class="badge badge-blue">PLB</span>`
            : `<span class="badge badge-teal">REM</span>`;

        return `
          <div class="gantt-row">
            <div class="gantt-stand-label" data-stand-id="${escapeHtml(s.stand_id)}">
              <span class="stand-code">${escapeHtml(s.stand_id)}</span>
              ${typeBadge}
              <span class="badge badge-gray">${escapeHtml(s.max_size)}</span>
            </div>
            <div class="gantt-track">
              ${peakLine}
              ${barsHtml}
            </div>
          </div>
        `;
      })
      .join("");

    board.innerHTML = `
      <div class="gantt-header">
        <div class="mono" style="font-size:11.5px;color:var(--text-muted)">STAND</div>
        <div class="gantt-axis">${ticks.join("")}</div>
      </div>
      ${rowsHtml}
    `;

    // Bind bar tooltips & click-to-open-drawer
    const tooltip = $("ganttTooltip");
    board.querySelectorAll(".gantt-bar").forEach((bar) => {
      const flightId = bar.dataset.flightId;
      const flight = alloc.allocations.find((a) => a.flight_id === flightId);
      if (!flight) return;

      bar.addEventListener("mouseenter", (e) => {
        tooltip.innerHTML = `
          <div><b>${escapeHtml(flight.flight_id)}</b> • Size ${escapeHtml(flight.aircraft_size)}</div>
          <div>Stand: <b>${escapeHtml(flight.stand_id)}</b> (${escapeHtml(flight.stand_type)})</div>
          <div>${formatUtcTime(flight.arrival_time)}–${formatUtcTime(flight.departure_time)} UTC (${formatDuration(flight.arrival_time, flight.departure_time)})</div>
        `;
        tooltip.hidden = false;
        positionTooltip(e);
      });
      bar.addEventListener("mousemove", positionTooltip);
      bar.addEventListener("mouseleave", () => {
        tooltip.hidden = true;
      });
      bar.addEventListener("click", () => openFlightDrawer(flight));
    });

    board.querySelectorAll(".gantt-stand-label").forEach((el) => {
      el.addEventListener("click", () => openStandDrawer(el.dataset.standId));
    });
  }

  function positionTooltip(e) {
    const tooltip = $("ganttTooltip");
    const pad = 14;
    const x = Math.min(window.innerWidth - 290, e.clientX + pad);
    const y = Math.min(window.innerHeight - 90, e.clientY + pad);
    tooltip.style.left = `${x}px`;
    tooltip.style.top = `${y}px`;
  }

  function renderMetricsTable() {
    const tbody = $("metricsTableBody");
    tbody.innerHTML = state.metricsPayload.metrics
      .map((m) => {
        const val = m.value == null ? "—" : `${m.value} ${m.unit}`;
        return `
          <tr>
            <td><span class="badge badge-gray mono">${escapeHtml(m.id)}</span></td>
            <td>
              <div style="font-weight:500">${escapeHtml(m.name)}</div>
              <div style="font-size:12px;color:var(--text-secondary)">${escapeHtml(m.why_it_matters)}</div>
            </td>
            <td class="mono" style="font-weight:500;white-space:nowrap">${escapeHtml(val)}</td>
            <td style="white-space:nowrap;color:var(--text-secondary)">${m.flights_covered} flights</td>
            <td style="color:var(--text-secondary);font-size:13px">${escapeHtml(m.definition)}</td>
          </tr>
        `;
      })
      .join("");
  }

  function renderFlightsTable() {
    const query = state.flightQuery.trim().toLowerCase();
    const filtered = state.allocationsPayload.allocations.filter((a) => {
      if (state.flightStatus !== "ALL" && a.status !== state.flightStatus) return false;
      if (state.flightSize !== "ALL" && a.aircraft_size !== state.flightSize) return false;
      if (!query) return true;
      return (
        a.flight_id.toLowerCase().includes(query) ||
        (a.stand_id && a.stand_id.toLowerCase().includes(query)) ||
        (a.reason && a.reason.toLowerCase().includes(query))
      );
    });

    $("flightResultCount").textContent =
      `Showing ${filtered.length} of ${state.allocationsPayload.total} flights`;

    const tbody = $("flightsTableBody");
    if (filtered.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-secondary);padding:28px">No matching flights found.</td></tr>`;
      return;
    }

    tbody.innerHTML = filtered
      .map((a) => {
        const statusBadge =
          a.status === "ASSIGNED"
            ? `<span class="badge badge-green">ASSIGNED</span>`
            : `<span class="badge badge-red">UNASSIGNED</span>`;

        const standCell = a.stand_id
          ? `<span class="mono" style="font-weight:500">${escapeHtml(a.stand_id)}</span> <span class="badge ${a.stand_type === "PLB" ? "badge-blue" : "badge-teal"}">${escapeHtml(a.stand_type)}</span>`
          : `<span style="color:var(--text-muted)">—</span>`;

        const noteOrReason =
          a.status === "UNASSIGNED"
            ? `<div class="code-label">${escapeHtml(a.reason_code || "")}</div><div class="reason-cell">${escapeHtml(a.reason || "")}</div>`
            : a.note
              ? `<span style="font-size:12.5px;color:var(--text-secondary)">${escapeHtml(a.note)}</span>`
              : `<span style="color:var(--text-muted)">—</span>`;

        return `
          <tr data-flight-id="${escapeHtml(a.flight_id)}" style="cursor:pointer">
            <td class="mono" style="font-weight:500">${escapeHtml(a.flight_id)}</td>
            <td><span class="badge badge-gray">${escapeHtml(a.aircraft_size)}</span></td>
            <td class="mono">${formatUtcTime(a.arrival_time)}</td>
            <td class="mono">${formatUtcTime(a.departure_time)}</td>
            <td class="mono" style="color:var(--text-secondary)">${formatDuration(a.arrival_time, a.departure_time)}</td>
            <td>${statusBadge}</td>
            <td style="white-space:nowrap">${standCell}</td>
            <td>${noteOrReason}</td>
          </tr>
        `;
      })
      .join("");

    tbody.querySelectorAll("tr[data-flight-id]").forEach((tr) => {
      tr.addEventListener("click", () => {
        const flight = state.allocationsPayload.allocations.find(
          (a) => a.flight_id === tr.dataset.flightId
        );
        if (flight) openFlightDrawer(flight);
      });
    });
  }

  function renderStandsGrid() {
    const winStartMs = new Date(state.allocationsPayload.planning_window.start).getTime();
    const winEndMs = new Date(state.allocationsPayload.planning_window.end).getTime();
    const spanMs = winEndMs - winStartMs;

    const stands = state.stands.filter(
      (s) => state.standType === "ALL" || s.stand_type === state.standType
    );

    $("standGrid").innerHTML = stands
      .map((s) => {
        const flights = state.allocationsPayload.allocations.filter(
          (a) => a.stand_id === s.stand_id
        );
        let occupiedMs = 0;
        const bars = flights
          .map((f) => {
            const arr = new Date(f.arrival_time).getTime();
            const dep = new Date(f.departure_time).getTime();
            occupiedMs += Math.max(0, Math.min(dep, winEndMs) - Math.max(arr, winStartMs));
            const left = Math.max(0, ((arr - winStartMs) / spanMs) * 100);
            const width = Math.max(2, Math.min(100 - left, ((dep - arr) / spanMs) * 100));
            const cls = s.stand_type === "PLB" ? "plb" : "remote";
            return `<span class="mini-bar ${cls}" style="left:${left.toFixed(1)}%;width:${width.toFixed(1)}%"></span>`;
          })
          .join("");

        const utilPct = ((occupiedMs / spanMs) * 100).toFixed(0);
        const typeBadge =
          s.stand_type === "PLB"
            ? `<span class="badge badge-blue">PLB Contact</span>`
            : `<span class="badge badge-teal">Remote Apron</span>`;

        return `
          <div class="stand-card" data-stand-id="${escapeHtml(s.stand_id)}">
            <div class="stand-card-top">
              <span class="stand-card-id">${escapeHtml(s.stand_id)}</span>
              <div style="display:flex;gap:6px">
                ${typeBadge}
                <span class="badge badge-gray">Max ${escapeHtml(s.max_size)}</span>
              </div>
            </div>
            <div class="stand-card-meta">
              <span><b>${flights.length}</b> ${flights.length === 1 ? "flight" : "flights"}</span>
              <span>${utilPct}% occupied</span>
            </div>
            <div class="mini-track">${bars}</div>
          </div>
        `;
      })
      .join("");

    $("standGrid")
      .querySelectorAll(".stand-card")
      .forEach((card) => {
        card.addEventListener("click", () => openStandDrawer(card.dataset.standId));
      });
  }

  function renderAuditAndOps() {
    const ops = state.opsStats;
    const reqTotal = Object.values(ops.requests_total || {}).reduce((a, b) => a + b, 0);

    $("opsGrid").innerHTML = `
      <div class="kpi-card">
        <div class="kpi-label">API Uptime</div>
        <div class="kpi-value">${formatUptime(ops.uptime_seconds)}</div>
        <div class="kpi-sub">Run ${escapeHtml(ops.run_id || "—")}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">P95 Latency</div>
        <div class="kpi-value">${ops.latency_p95_ms.toFixed(1)} ms</div>
        <div class="kpi-sub">Nearest-rank over last 1,000 requests</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Requests Served</div>
        <div class="kpi-value">${reqTotal}</div>
        <div class="kpi-sub">2xx: ${ops.requests_total["2xx"] || 0} • 4xx: ${ops.requests_total["4xx"] || 0} • 5xx: ${ops.requests_total["5xx"] || 0}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Security Guards</div>
        <div class="kpi-value">${ops.auth_failed_total} / ${ops.rate_limited_total}</div>
        <div class="kpi-sub">Auth failures / Rate-limited requests</div>
      </div>
    `;

    const issuesData = state.issuesPayload;
    $("issuesSummary").textContent =
      `${issuesData.count} rows flagged during CSV validation — ${issuesData.fixed} auto-fixed, ${issuesData.dropped} dropped`;

    const filtered = issuesData.issues.filter(
      (i) => state.issueAction === "ALL" || i.action === state.issueAction
    );

    $("issuesTableBody").innerHTML = filtered
      .map((i) => {
        const badge =
          i.action === "FIXED"
            ? `<span class="badge badge-amber">FIXED</span>`
            : `<span class="badge badge-red">DROPPED</span>`;
        const transition =
          i.new_value !== null && i.new_value !== undefined
            ? `<span class="mono" style="color:var(--text-secondary)">${escapeHtml(i.original_value)}</span> → <span class="mono" style="font-weight:500">${escapeHtml(i.new_value)}</span>`
            : `<span class="mono" style="color:var(--text-secondary)">${escapeHtml(i.original_value || "(empty)")}</span>`;

        return `
          <tr>
            <td class="mono">#${i.row_number}</td>
            <td class="mono" style="font-weight:500">${escapeHtml(i.flight_id || "—")}</td>
            <td class="mono">${escapeHtml(i.field)}</td>
            <td><span class="code-label">${escapeHtml(i.issue_code)}</span></td>
            <td>${badge}</td>
            <td>${transition}</td>
            <td style="font-size:13px;color:var(--text-secondary)">${escapeHtml(i.explanation)}</td>
          </tr>
        `;
      })
      .join("");
  }

  // ==================== SLIDE-OVER DRAWER ====================
  function showDrawer(title, subtitle, bodyHtml) {
    $("drawerTitle").textContent = title;
    $("drawerSubtitle").textContent = subtitle;
    $("drawerBody").innerHTML = bodyHtml;
    $("drawerBackdrop").hidden = false;
    $("detailDrawer").setAttribute("aria-hidden", "false");
    $("detailDrawer").classList.add("open");
  }

  function closeDrawer() {
    $("detailDrawer").classList.remove("open");
    $("detailDrawer").setAttribute("aria-hidden", "true");
    $("drawerBackdrop").hidden = true;
  }

  function openFlightDrawer(flight) {
    const statusBadge =
      flight.status === "ASSIGNED"
        ? `<span class="badge badge-green">ASSIGNED</span>`
        : `<span class="badge badge-red">UNASSIGNED</span>`;

    const body = `
      <div class="kv-list">
        <div class="kv-key">Flight ID</div>
        <div class="mono" style="font-weight:500">${escapeHtml(flight.flight_id)}</div>

        <div class="kv-key">Aircraft Size</div>
        <div><span class="badge badge-gray">${escapeHtml(flight.aircraft_size)}</span></div>

        <div class="kv-key">Arrival (UTC)</div>
        <div class="mono">${escapeHtml(flight.arrival_time)}</div>

        <div class="kv-key">Departure (UTC)</div>
        <div class="mono">${escapeHtml(flight.departure_time)}</div>

        <div class="kv-key">Ground Time</div>
        <div>${formatDuration(flight.arrival_time, flight.departure_time)}</div>

        <div class="kv-key">Status</div>
        <div>${statusBadge}</div>

        <div class="kv-key">Assigned Stand</div>
        <div>${
          flight.stand_id
            ? `<button class="btn-outline mono" type="button" id="drawerOpenStandBtn">${escapeHtml(flight.stand_id)} (${escapeHtml(flight.stand_type)})</button>`
            : "None"
        }</div>

        ${
          flight.note
            ? `<div class="kv-key">Note</div><div style="color:var(--text-secondary)">${escapeHtml(flight.note)}</div>`
            : ""
        }
        ${
          flight.reason_code
            ? `<div class="kv-key">Reason Code</div><div class="code-label">${escapeHtml(flight.reason_code)}</div>`
            : ""
        }
        ${
          flight.reason
            ? `<div class="kv-key">Explanation</div><div style="color:var(--text-secondary)">${escapeHtml(flight.reason)}</div>`
            : ""
        }
      </div>
    `;

    showDrawer(
      `Flight ${flight.flight_id}`,
      `${formatUtcTime(flight.arrival_time)}–${formatUtcTime(flight.departure_time)} UTC`,
      body
    );

    const standBtn = $("drawerOpenStandBtn");
    if (standBtn && flight.stand_id) {
      standBtn.addEventListener("click", () => openStandDrawer(flight.stand_id));
    }
  }

  async function openStandDrawer(standId) {
    showDrawer(`Stand ${standId}`, "Loading stand schedule…", `<p style="color:var(--text-secondary)">Fetching details…</p>`);
    try {
      const detail = await apiFetch(`/stands/${encodeURIComponent(standId)}`);
      const timelineHtml =
        detail.flights.length === 0
          ? `<p style="color:var(--text-secondary)">No flights assigned to this stand.</p>`
          : detail.flights
              .map((f, idx) => {
                let gapHtml = "";
                if (idx > 0) {
                  const prevDep = new Date(detail.flights[idx - 1].departure_time).getTime();
                  const curArr = new Date(f.arrival_time).getTime();
                  const gapMins = Math.round((curArr - prevDep) / 60000);
                  const tight = gapMins < 30;
                  gapHtml = `
                    <div class="gap-pill ${tight ? "tight" : ""}">
                      ${tight ? "Tight turn:" : "Turnaround gap:"} ${gapMins} min
                    </div>
                  `;
                }
                return `
                  ${gapHtml}
                  <div class="timeline-item">
                    <div class="timeline-item-top">
                      <span class="mono" style="font-weight:500">${escapeHtml(f.flight_id)}</span>
                      <span class="badge badge-gray">Size ${escapeHtml(f.aircraft_size)}</span>
                    </div>
                    <div class="mono" style="font-size:12.5px;color:var(--text-secondary)">
                      ${formatUtcTime(f.arrival_time)} – ${formatUtcTime(f.departure_time)} UTC (${formatDuration(f.arrival_time, f.departure_time)})
                    </div>
                  </div>
                `;
              })
              .join("");

      showDrawer(
        `Stand ${detail.stand_id}`,
        `${detail.stand_type} • Max size ${detail.max_size} • ${detail.flight_count} flights`,
        timelineHtml
      );
    } catch (err) {
      showDrawer(`Stand ${standId}`, "Error", `<p style="color:var(--google-red)">${escapeHtml(err.message)}</p>`);
    }
  }

  // ==================== EVENT WIRING ====================
  function bindSegmented(containerId, onSelect) {
    const el = $(containerId);
    el.querySelectorAll(".seg-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        el.querySelectorAll(".seg-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        onSelect(btn.dataset.val);
      });
    });
  }

  function initEvents() {
    $("toggleKeyVis").addEventListener("click", () => {
      const input = $("apiKeyInput");
      const isPwd = input.type === "password";
      input.type = isPwd ? "text" : "password";
      $("visIcon").textContent = isPwd ? "visibility_off" : "visibility";
    });

    $("authForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const key = $("apiKeyInput").value.trim();
      const remember = $("rememberKey").checked;
      if (!key) return;
      state.apiKey = key;
      saveStoredKey(key, remember);
      $("connectBtn").disabled = true;
      $("connectBtn").textContent = "Connecting…";
      await loadAllData();
      $("connectBtn").disabled = false;
      $("connectBtn").textContent = "Connect";
    });

    $("keyBtn").addEventListener("click", () => {
      clearStoredKey();
      state.apiKey = "";
      $("apiKeyInput").value = "";
      showAuth();
    });

    $("refreshBtn").addEventListener("click", () => {
      checkReadiness();
      loadAllData();
    });

    document.querySelectorAll(".nav-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        const target = tab.dataset.tab;
        state.activeTab = target;
        document.querySelectorAll(".nav-tab").forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
        $(`panel-${target}`).classList.add("active");
      });
    });

    // Gantt controls
    $("ganttSearch").addEventListener("input", (e) => {
      state.ganttQuery = e.target.value;
      renderGantt();
    });
    $("showBufferToggle").addEventListener("change", (e) => {
      state.showBuffer = e.target.checked;
      renderGantt();
    });
    bindSegmented("ganttTypeFilter", (val) => {
      state.ganttType = val;
      renderGantt();
    });
    bindSegmented("ganttSizeFilter", (val) => {
      state.ganttSize = val;
      renderGantt();
    });

    // Flights controls
    $("flightSearch").addEventListener("input", (e) => {
      state.flightQuery = e.target.value;
      renderFlightsTable();
    });
    bindSegmented("flightStatusFilter", (val) => {
      state.flightStatus = val;
      renderFlightsTable();
    });
    bindSegmented("flightSizeFilter", (val) => {
      state.flightSize = val;
      renderFlightsTable();
    });

    // Stands controls
    bindSegmented("standTypeFilter", (val) => {
      state.standType = val;
      renderStandsGrid();
    });

    // Audit controls
    bindSegmented("issueActionFilter", (val) => {
      state.issueAction = val;
      renderAuditAndOps();
    });

    // Drawer controls
    $("closeDrawerBtn").addEventListener("click", closeDrawer);
    $("drawerBackdrop").addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeDrawer();
    });
  }

  // ==================== BOOT ====================
  async function boot() {
    initEvents();
    await checkReadiness();

    const stored = loadStoredKey();
    if (stored) {
      state.apiKey = stored;
      await loadAllData();
    } else {
      showAuth();
    }
  }

  boot();
})();
