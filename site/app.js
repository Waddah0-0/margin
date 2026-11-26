(function () {
  "use strict";

  /* ---- Theme Toggle ------------------------------------------------------------------- */
  const root = document.documentElement;
  const themeBtn = document.getElementById("theme-toggle");

  function setTheme(next) {
    root.setAttribute("data-theme", next);
    try {
      localStorage.setItem("margin-site-theme", next);
    } catch (e) {}
    if (themeBtn) {
      themeBtn.setAttribute(
        "aria-label",
        next === "dark" ? "Switch to light theme" : "Switch to dark theme"
      );
    }
  }

  if (themeBtn) {
    setTheme(root.getAttribute("data-theme") || "light");
    themeBtn.addEventListener("click", function () {
      const current = root.getAttribute("data-theme") === "dark" ? "dark" : "light";
      setTheme(current === "dark" ? "light" : "dark");
    });
  }

  /* ---- Copy Buttons ------------------------------------------------------------------- */
  const announcer = document.getElementById("copy-announcer");

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }

  document.addEventListener("click", async function (event) {
    const btn = event.target.closest("[data-copy]");
    if (!btn) return;
    const text = btn.getAttribute("data-copy");
    if (!text) return;

    try {
      await copyText(text);
      const original = btn.dataset.originalLabel || btn.textContent.trim();
      btn.dataset.originalLabel = original;
      btn.textContent = "Copied";
      btn.setAttribute("data-copied", "true");
      if (announcer) announcer.textContent = "Copied to clipboard";

      clearTimeout(btn._copyTimer);
      btn._copyTimer = setTimeout(function () {
        btn.textContent = original;
        btn.removeAttribute("data-copied");
      }, 1600);
    } catch (e) {
      if (announcer) announcer.textContent = "Copy failed";
    }
  });

  /* ---- Workbench Tabs ----------------------------------------------------------------- */
  const wbCommands = {
    storyteller: "margin run data-storyteller sales.csv --set stop_after=story",
    detector: "margin run ai-code-detector https://github.com/psf/requests",
    "commit-graph": "margin run commit-graph https://github.com/Waddah0-0/margin",
  };

  const wbTabs = document.querySelectorAll("[data-wb-tab]");
  const wbCmdText = document.getElementById("wb-cmd-text");

  wbTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      const target = tab.getAttribute("data-wb-tab");
      wbTabs.forEach(function (t) {
        const active = t === tab;
        t.setAttribute("aria-selected", active ? "true" : "false");
        const panelId = t.getAttribute("aria-controls");
        const panel = panelId ? document.getElementById(panelId) : null;
        if (panel) panel.hidden = !active;
      });
      if (wbCmdText && wbCommands[target]) {
        wbCmdText.textContent = wbCommands[target];
      }
    });
  });

  /* ---- Data Storyteller: Interactive Crosshair Chart ---------------------------------- */
  const chartSvg = document.getElementById("storyteller-chart");
  const chartValueEl = document.getElementById("chart-value");
  const chartMonthEl = document.getElementById("chart-month");

  const series = [
    ["2025-01", 4610],
    ["2025-02", 5280],
    ["2025-03", 4590],
    ["2025-04", 4620],
    ["2025-05", 5210],
    ["2025-06", 5628],
    ["2025-07", 5540],
    ["2025-08", 5710],
    ["2025-09", 5520],
    ["2025-10", 6790],
    ["2025-11", 6320],
    ["2025-12", 6539],
    ["2026-01", 8280],
    ["2026-02", 7720],
    ["2026-03", 7260],
    ["2026-04", 8610],
    ["2026-05", 7233],
    ["2026-06", 9826],
  ];

  function buildChart() {
    if (!chartSvg) return;
    const ns = "http://www.w3.org/2000/svg";
    const padL = 40;
    const padR = 12;
    const padT = 14;
    const padB = 28;
    const w = 640;
    const h = 184;
    const innerW = w - padL - padR;
    const innerH = h - padT - padB;
    const maxY = 10500;

    function xFor(i) {
      return padL + (i / (series.length - 1)) * innerW;
    }
    function yFor(v) {
      return padT + innerH - (v / maxY) * innerH;
    }
    function el(tag, attrs) {
      const node = document.createElementNS(ns, tag);
      for (const k in attrs) node.setAttribute(k, String(attrs[k]));
      return node;
    }

    // Gridlines
    [0, 2500, 5000, 7500, 10000].forEach(function (val) {
      const y = yFor(val);
      chartSvg.appendChild(
        el("line", { x1: padL, x2: w - padR, y1: y, y2: y, class: "chart-grid" })
      );
      const lbl = el("text", {
        x: padL - 10,
        y: y + 4,
        "text-anchor": "end",
        class: "chart-axis",
      });
      lbl.textContent = val === 0 ? "0" : val / 1000 + "K";
      chartSvg.appendChild(lbl);
    });

    const pts = series.map(function (d, i) {
      return [xFor(i), yFor(d[1])];
    });
    const lineD = pts
      .map(function (p, i) {
        return (i === 0 ? "M" : "L") + p[0].toFixed(1) + " " + p[1].toFixed(1);
      })
      .join(" ");
    const areaD =
      lineD +
      " L" +
      pts[pts.length - 1][0].toFixed(1) +
      " " +
      yFor(0).toFixed(1) +
      " L" +
      pts[0][0].toFixed(1) +
      " " +
      yFor(0).toFixed(1) +
      " Z";

    chartSvg.appendChild(el("path", { d: areaD, class: "chart-fill" }));
    chartSvg.appendChild(el("path", { d: lineD, class: "chart-line" }));

    // X-axis ticks
    [0, 5, 11, 17].forEach(function (idx) {
      const lbl = el("text", {
        x: xFor(idx),
        y: h - 6,
        "text-anchor": idx === 0 ? "start" : idx === 17 ? "end" : "middle",
        class: "chart-axis",
      });
      lbl.textContent = series[idx][0];
      chartSvg.appendChild(lbl);
    });

    // Crosshair + active dot
    const lastIdx = series.length - 1;
    const crosshair = el("line", {
      x1: pts[lastIdx][0],
      x2: pts[lastIdx][0],
      y1: padT,
      y2: yFor(0),
      class: "chart-crosshair",
    });
    const dot = el("circle", {
      cx: pts[lastIdx][0],
      cy: pts[lastIdx][1],
      r: 5,
      class: "chart-dot",
    });
    chartSvg.appendChild(crosshair);
    chartSvg.appendChild(dot);

    function setActive(index) {
      const i = Math.max(0, Math.min(series.length - 1, index));
      const p = pts[i];
      crosshair.setAttribute("x1", p[0].toFixed(1));
      crosshair.setAttribute("x2", p[0].toFixed(1));
      dot.setAttribute("cx", p[0].toFixed(1));
      dot.setAttribute("cy", p[1].toFixed(1));
      if (chartValueEl) chartValueEl.textContent = "$" + series[i][1].toLocaleString();
      if (chartMonthEl) chartMonthEl.textContent = series[i][0];
    }

    function indexFromClientX(clientX) {
      const rect = chartSvg.getBoundingClientRect();
      const svgX = ((clientX - rect.left) / rect.width) * w;
      const ratio = (svgX - padL) / innerW;
      return Math.round(ratio * (series.length - 1));
    }

    chartSvg.addEventListener("pointerdown", function (e) {
      setActive(indexFromClientX(e.clientX));
    });
    chartSvg.addEventListener("pointermove", function (e) {
      setActive(indexFromClientX(e.clientX));
    });
    chartSvg.addEventListener("click", function (e) {
      setActive(indexFromClientX(e.clientX));
    });
  }

  buildChart();

  /* ---- Data Storyteller: Interactive Receipts ----------------------------------------- */
  const facts = {
    growth: {
      value: "63.4%",
      status: "Verified · Dual compute",
      tone: "blue",
      desc: "Relative revenue change between 2025-01..2025-06 and 2026-01..2026-06.",
      aLabel: "pandas",
      aVal: "0.634344",
      aCode: "(h2.sum() - h1.sum()) / h1.sum()",
      bLabel: "DuckDB SQL",
      bVal: "0.634344",
      bCode:
        "SELECT\n  (SUM(rev) FILTER (WHERE ym >= '2026-01')\n - SUM(rev) FILTER (WHERE ym <= '2025-06'))\n / SUM(rev) FILTER (WHERE ym <= '2025-06')\nFROM cleaned_sales;",
      source: "period_growth_pct",
      match: "Exact agreement (Δ = 0.0000)",
    },
    first_half: {
      value: "$29,938",
      status: "Verified · Dual compute",
      tone: "blue",
      desc: "Total revenue across the first six months (2025-01 through 2025-06, 198 rows).",
      aLabel: "pandas",
      aVal: "29938.00",
      aCode: "df.loc[df['ym'].between('2025-01', '2025-06'), 'revenue'].sum()",
      bLabel: "DuckDB SQL",
      bVal: "29938.00",
      bCode:
        "SELECT SUM(revenue)\nFROM cleaned_sales\nWHERE ym BETWEEN '2025-01' AND '2025-06';",
      source: "h1_2025_revenue",
      match: "Exact agreement (Δ = 0.00)",
    },
    second_half: {
      value: "$48,929",
      status: "Verified · Dual compute",
      tone: "blue",
      desc: "Total revenue across the comparable 2026 window (2026-01 through 2026-06, 204 rows).",
      aLabel: "pandas",
      aVal: "48929.00",
      aCode: "df.loc[df['ym'].between('2026-01', '2026-06'), 'revenue'].sum()",
      bLabel: "DuckDB SQL",
      bVal: "48929.00",
      bCode:
        "SELECT SUM(revenue)\nFROM cleaned_sales\nWHERE ym BETWEEN '2026-01' AND '2026-06';",
      source: "h1_2026_revenue",
      match: "Exact agreement (Δ = 0.00)",
    },
    total: {
      value: "$115,286",
      status: "Verified · Dual compute",
      tone: "blue",
      desc: "Sum of all cleaned non-null revenue cells across 18 months (599 valid rows, 1 empty).",
      aLabel: "pandas",
      aVal: "115286.00",
      aCode: "df['revenue'].sum(skipna=True)",
      bLabel: "DuckDB SQL",
      bVal: "115286.00",
      bCode: "SELECT SUM(revenue) FROM cleaned_sales;",
      source: "total_revenue",
      match: "Exact agreement (Δ = 0.00)",
    },
    r2: {
      value: "81.7%",
      status: "Verified · Dual compute",
      tone: "blue",
      desc: "Coefficient of determination (R²) for the monthly linear revenue trend over 18 months.",
      aLabel: "scipy / pandas",
      aVal: "0.8174",
      aCode: "linregress(month_idx, monthly_rev).rvalue ** 2",
      bLabel: "DuckDB SQL",
      bVal: "0.8174",
      bCode: "SELECT REGR_R2(monthly_rev, month_idx)\nFROM monthly_totals;",
      source: "trend_r_squared",
      match: "Exact agreement (Δ = 0.0000)",
    },
    date_decision: {
      value: "2026-05-02",
      status: "Assumed · Not confirmed",
      tone: "red",
      desc: 'In "Order date", 05/02/2026 could be May 2 or Feb 5. Parsed month-first under assume_defaults=true.',
      aLabel: "Cleaning change",
      aVal: "row 4",
      aCode: "Order date: '05/02/2026' -> '2026-05-02'",
      bLabel: "Question skipped",
      bVal: "Unconfirmed",
      bCode:
        'In "Order date", is 05/02/2026 day first or month first?\nOmit assume_defaults to answer interactively.',
      source: "date_order_ambiguous",
      match: "Flagged in red in report",
    },
  };

  const factButtons = document.querySelectorAll("[data-fact]");
  const receiptEls = {
    status: document.getElementById("receipt-status"),
    value: document.getElementById("receipt-value"),
    desc: document.getElementById("receipt-desc"),
    aLabel: document.getElementById("receipt-a-label"),
    aVal: document.getElementById("receipt-a-val"),
    aCode: document.getElementById("receipt-a-code"),
    bLabel: document.getElementById("receipt-b-label"),
    bVal: document.getElementById("receipt-b-val"),
    bCode: document.getElementById("receipt-b-code"),
    source: document.getElementById("receipt-source"),
    match: document.getElementById("receipt-match"),
  };

  function showFact(key) {
    const f = facts[key];
    if (!f) return;
    factButtons.forEach(function (btn) {
      btn.setAttribute("aria-pressed", btn.getAttribute("data-fact") === key ? "true" : "false");
    });
    receiptEls.status.textContent = f.status;
    receiptEls.status.setAttribute("data-tone", f.tone);
    receiptEls.value.textContent = f.value;
    receiptEls.desc.textContent = f.desc;
    receiptEls.aLabel.textContent = f.aLabel;
    receiptEls.aVal.textContent = f.aVal;
    receiptEls.aCode.textContent = f.aCode;
    receiptEls.bLabel.textContent = f.bLabel;
    receiptEls.bVal.textContent = f.bVal;
    receiptEls.bCode.textContent = f.bCode;
    receiptEls.source.textContent = f.source;
    receiptEls.match.textContent = f.match;
  }

  factButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      showFact(btn.getAttribute("data-fact"));
    });
  });

  /* ---- AI Code Detector: Animated Precision Ruler & Quotes ---------------------------- */
  function buildRulerTicks() {
    const svg = document.getElementById("detector-ruler");
    if (!svg) return;
    const ns = "http://www.w3.org/2000/svg";
    function el(tag, attrs) {
      const node = document.createElementNS(ns, tag);
      for (const k in attrs) node.setAttribute(k, String(attrs[k]));
      return node;
    }

    const w = 640;
    const baseY = 36;
    svg.appendChild(
      el("line", { x1: 0, x2: w, y1: baseY, y2: baseY, stroke: "var(--hairline-strong)", "stroke-width": 1.2 })
    );

    for (let i = 0; i <= 50; i++) {
      const x = (i / 50) * w;
      const major = i % 5 === 0;
      const end = i === 0 || i === 50;
      const top = end ? 10 : major ? 22 : 29;
      svg.appendChild(
        el("line", {
          x1: x,
          x2: x,
          y1: top,
          y2: baseY,
          stroke: major ? "var(--hairline-strong)" : "var(--hairline)",
          "stroke-width": 1,
        })
      );
    }
  }

  buildRulerTicks();

  const detectorScopes = {
    repo: {
      scoreText: "0.62",
      bandHtml: "plausibly between <code>0.47</code> and <code>0.77</code>",
      needle: 62,
      low: 47,
      high: 77,
      tone: "red",
      tag: "Estimate · Not proof",
      weight: "range 0.47 – 0.77",
      title: "Repository summary",
      desc: "Clean human code can look machine-made, and edited AI code can look human. Use the estimate to start a conversation, never as proof.",
      reason:
        "The model only cites line numbers. margin copies every quoted line verbatim from disk so evidence cannot be invented.",
      rows: [
        { ln: 41, note: "src/router.py", tone: "red", src: 'def resolve_route(path: str, method: str) -> Route:' },
        { ln: 42, note: "boilerplate doc", tone: "red", src: '    """Resolve a route given a path and HTTP method."""' },
        { ln: 112, note: "src/parser.py", tone: "blue", src: "# RFC 2616 fold: older proxies split header values with CRLF + SP" },
        { ln: 114, note: "terse idiom", tone: "blue", src: "    k, v = headers[-1]" },
        { ln: 1, note: "metadata only", tone: "", src: "CLAUDE.md · reported separately, excluded from score" },
      ],
    },
    router: {
      scoreText: "0.81",
      bandHtml: "file signal between <code>0.68</code> and <code>0.91</code>",
      needle: 81,
      low: 68,
      high: 91,
      tone: "red",
      tag: "AI-leaning file",
      weight: "+0.18 weight",
      title: "src/router.py",
      desc: "Consecutive handlers share identical docstring templates and uniform error-wrapping patterns.",
      reason:
        "Restates parameter names verbatim in prose docstrings and wraps single dictionary lookups in identical try/except blocks.",
      rows: [
        { ln: 41, note: "boilerplate doc", tone: "red", src: "def resolve_route(path: str, method: str) -> Route:" },
        { ln: 42, note: "restates sig", tone: "red", src: '    """Resolve a route given a path and HTTP method."""' },
        { ln: 43, note: "", tone: "", src: "    normalized = path.rstrip('/') or '/'" },
        { ln: 44, note: "uniform wrap", tone: "red", src: "    try:" },
        { ln: 45, note: "", tone: "", src: "        return TABLE[(method, normalized)]" },
        { ln: 46, note: "", tone: "", src: "    except KeyError as exc:" },
        { ln: 47, note: "", tone: "", src: '        raise RouteNotFoundError(f"No route for {method} {path}") from exc' },
      ],
    },
    parser: {
      scoreText: "0.24",
      bandHtml: "file signal between <code>0.14</code> and <code>0.36</code>",
      needle: 24,
      low: 14,
      high: 36,
      tone: "blue",
      tag: "Human-leaning file",
      weight: "-0.14 weight",
      title: "src/parser.py",
      desc: "Signals cut both ways. margin shows evidence against AI assistance alongside evidence for it.",
      reason:
        "Terse domain-specific edge case referencing RFC 2616 header folding with compact stateful mutation.",
      rows: [
        { ln: 112, note: "domain quirk", tone: "blue", src: "# RFC 2616 fold: older proxies split header values with CRLF + SP" },
        { ln: 113, note: "", tone: "", src: "if raw.startswith((b' ', b'\\t')) and headers:" },
        { ln: 114, note: "terse idiom", tone: "blue", src: "    k, v = headers[-1]" },
        { ln: 115, note: "", tone: "", src: "    headers[-1] = (k, v + b' ' + raw.strip())" },
        { ln: 116, note: "", tone: "", src: "    continue" },
      ],
    },
    metadata: {
      scoreText: "0.00",
      bandHtml: "metadata is <code>reported, never scored</code>",
      needle: null,
      low: 0,
      high: 0,
      tone: "blue",
      tag: "Reported, not scored",
      weight: "0.00 (excluded)",
      title: "CLAUDE.md",
      desc: "Tool config files and co-author trailers prove a tool was present, not how much code it wrote — so they never inflate the estimate.",
      reason:
        "Detected CLAUDE.md at repository root and 2 commits carrying a Claude co-author trailer.",
      rows: [
        { ln: 1, note: "metadata file", tone: "blue", src: "CLAUDE.md  (configuration / instructions file for Claude Code)" },
        { ln: 2, note: "commit trailer", tone: "blue", src: "bff4096a83  Co-Authored-By: Claude" },
        { ln: 3, note: "policy", tone: "", src: "Status: surfaced in report, score weight fixed at 0.00" },
      ],
    },
  };

  const detTabs = document.querySelectorAll("[data-det-file]");
  const detCodeEl = document.getElementById("detector-code");
  const detEls = {
    score: document.getElementById("det-score"),
    band: document.getElementById("det-band"),
    rulerBand: document.getElementById("ruler-band"),
    rulerNeedle: document.getElementById("ruler-needle"),
    tag: document.getElementById("det-file-tag"),
    weight: document.getElementById("det-file-weight"),
    title: document.getElementById("det-file-title"),
    desc: document.getElementById("det-file-desc"),
    reason: document.getElementById("det-file-reason"),
  };

  function renderDetector(key) {
    const item = detectorScopes[key];
    if (!item || !detCodeEl) return;

    detTabs.forEach(function (t) {
      t.setAttribute("aria-selected", t.getAttribute("data-det-file") === key ? "true" : "false");
    });

    detEls.score.textContent = item.scoreText;
    detEls.band.innerHTML = item.bandHtml;

    if (item.needle === null) {
      detEls.rulerNeedle.style.opacity = "0";
      detEls.rulerBand.style.opacity = "0";
    } else {
      detEls.rulerNeedle.style.opacity = "1";
      detEls.rulerBand.style.opacity = "1";
      detEls.rulerNeedle.style.left = item.needle + "%";
      detEls.rulerBand.style.left = item.low + "%";
      detEls.rulerBand.style.width = item.high - item.low + "%";
      detEls.rulerBand.setAttribute("data-tone", item.tone);
    }

    detCodeEl.innerHTML = "";
    item.rows.forEach(function (r) {
      const row = document.createElement("div");
      row.className = "code-line";
      if (r.tone) row.setAttribute("data-tone", r.tone);

      const note = document.createElement("span");
      note.className = "cl-note";
      note.textContent = r.note;

      const num = document.createElement("span");
      num.className = "cl-num";
      num.textContent = String(r.ln);

      const src = document.createElement("span");
      src.className = "cl-src";
      src.textContent = r.src;

      row.appendChild(note);
      row.appendChild(num);
      row.appendChild(src);
      detCodeEl.appendChild(row);
    });

    detEls.tag.textContent = item.tag;
    detEls.tag.setAttribute("data-tone", item.tone);
    detEls.weight.textContent = item.weight;
    detEls.title.textContent = item.title;
    detEls.desc.textContent = item.desc;
    detEls.reason.textContent = item.reason;
  }

  detTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      renderDetector(tab.getAttribute("data-det-file"));
    });
  });

  renderDetector("repo");

  /* ---- Commit Graph: Filterable Ink-Lane Tree ----------------------------------------- */
  const commits = [
    {
      sha: "7d37898",
      msg: "added power bi project export to data storyteller",
      meta: "23 Nov 2026 · main · 8 files",
      lane: 0,
      flagged: false,
      tag: "Chapter 05",
      chapter: "Exports & publishing",
      stats: "8 files · +2520 / -16",
      summary:
        "Added Power BI project (.pbip) export to Data Storyteller alongside 1,041 lines of schema and layout tests.",
      files:
        "agents/data_storyteller/src/data_storyteller/pbip.py\nagents/data_storyteller/tests/test_pbip.py\nagents/data_storyteller/src/data_storyteller/report.py",
      note: "Lanes stay in ink; red only marks reverts and quick fixes.",
    },
    {
      sha: "9d03e14",
      msg: "added secret leaks agent",
      meta: "21 Nov 2026 · main · 14 files",
      lane: 0,
      flagged: false,
      tag: "Chapter 05",
      chapter: "Exports & publishing",
      stats: "14 files · +1659 / -0",
      summary:
        "Added Secret Leaks scanner covering workspace files and full git history with strictly redacted previews.",
      files:
        "agents/secret_leaks/src/secret_leaks/scanner.py\nagents/secret_leaks/src/secret_leaks/rules.py\nagents/secret_leaks/tests/test_secret_leaks.py",
      note: "Uses READ_ONLY_GIT_CONFIG; never executes repository hooks.",
    },
    {
      sha: "385f080",
      msg: "fixed quiet gap notes on branches",
      meta: "19 Nov 2026 · fix · 2 files",
      lane: 1,
      flagged: true,
      tag: "Flagged · Quick fix",
      chapter: "Commit Graph polish",
      stats: "2 files · +38 / -14",
      summary:
        "Flagged in red as a targeted fix right after initial commit-graph release: corrected gap annotations along side branches.",
      files:
        "agents/commit_graph/src/commit_graph/layout.py\nagents/commit_graph/tests/test_commit_graph.py",
      note: "Red marks quick fixes and reverts — never branch colours.",
    },
    {
      sha: "788ed7e",
      msg: "added the commit graph agent",
      meta: "18 Nov 2026 · main · 16 files",
      lane: 0,
      flagged: false,
      tag: "Chapter 04",
      chapter: "Repository history",
      stats: "16 files · +1940 / -0",
      summary:
        "Introduced Commit Graph: parses git history into narrative chapters and draws a clean ink-lane SVG tree.",
      files:
        "agents/commit_graph/src/commit_graph/agent.py\nagents/commit_graph/src/commit_graph/svg.py\nui/src/results/history/HistoryResult.tsx",
      note: "Pairs with the ruled margin view in the web UI.",
    },
    {
      sha: "570fddf",
      msg: "fixed utf-8 stdout on windows",
      meta: "14 Nov 2026 · fix · 2 files",
      lane: 1,
      flagged: true,
      tag: "Flagged · Quick fix",
      chapter: "Cross-platform CLI",
      stats: "2 files · +98 / -2",
      summary:
        "Ensured UTF-8 report arrows and punctuation print cleanly on Windows terminals without cp1252 encoding errors.",
      files: "packages/cli/src/margin_cli/main.py\npackages/cli/tests/test_cli.py",
      note: "Reports always go to stdout; logs stay on stderr.",
    },
  ];

  const commitListEl = document.getElementById("commit-list");
  const cgFilterTabs = document.querySelectorAll("[data-cg-filter]");
  const cgEls = {
    tag: document.getElementById("cg-tag"),
    sha: document.getElementById("cg-sha"),
    summary: document.getElementById("cg-summary"),
    stats: document.getElementById("cg-stats"),
    files: document.getElementById("cg-files"),
    chapter: document.getElementById("cg-chapter"),
    note: document.getElementById("cg-note"),
  };

  function makeLaneSvg(lane, flagged, isFirst, isLast) {
    const cx = lane === 0 ? 16 : 34;
    const dotColor = flagged ? "var(--red)" : "var(--ink)";
    const branchPath =
      lane === 1
        ? '<path d="M16 0 C16 14 34 10 34 22 C34 34 16 30 16 44" fill="none" stroke="var(--hairline-strong)" stroke-width="1.5"/>'
        : "";
    return (
      '<svg width="48" height="44" viewBox="0 0 48 44" aria-hidden="true">' +
      '<line x1="16" y1="' +
      (isFirst ? 22 : 0) +
      '" x2="16" y2="' +
      (isLast ? 22 : 44) +
      '" stroke="var(--ink-3)" stroke-width="1.5"/>' +
      branchPath +
      '<circle cx="' +
      cx +
      '" cy="22" r="4.5" fill="' +
      dotColor +
      '"/>' +
      "</svg>"
    );
  }

  function selectCommit(c) {
    cgEls.tag.textContent = c.tag;
    cgEls.tag.setAttribute("data-tone", c.flagged ? "red" : "blue");
    cgEls.sha.textContent = c.sha;
    cgEls.summary.textContent = c.summary;
    cgEls.stats.textContent = c.stats;
    cgEls.files.textContent = c.files;
    cgEls.chapter.textContent = c.chapter;
    cgEls.note.textContent = c.note;
  }

  function renderCommits(filter) {
    if (!commitListEl) return;
    const list = filter === "flagged" ? commits.filter(function (c) { return c.flagged; }) : commits;
    commitListEl.innerHTML = "";

    list.forEach(function (c, idx) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cg-row";
      btn.setAttribute("role", "option");
      btn.setAttribute("aria-selected", idx === 0 ? "true" : "false");
      if (c.flagged) btn.setAttribute("data-flagged", "true");

      btn.innerHTML =
        makeLaneSvg(c.lane, c.flagged, idx === 0, idx === list.length - 1) +
        '<span class="cg-sha">' +
        c.sha +
        "</span>" +
        '<span><span class="cg-msg">' +
        c.msg +
        '</span><span class="cg-sub">' +
        c.meta +
        "</span></span>";

      btn.addEventListener("click", function () {
        commitListEl.querySelectorAll(".cg-row").forEach(function (r) {
          r.setAttribute("aria-selected", r === btn ? "true" : "false");
        });
        selectCommit(c);
      });

      commitListEl.appendChild(btn);
    });

    if (list[0]) selectCommit(list[0]);
  }

  cgFilterTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      const filter = tab.getAttribute("data-cg-filter");
      cgFilterTabs.forEach(function (t) {
        t.setAttribute("aria-selected", t === tab ? "true" : "false");
      });
      renderCommits(filter);
    });
  });

  renderCommits("all");

  /* ---- Local Web UI Showcase ---------------------------------------------------------- */
  const uiScreens = {
    storyteller: {
      url: "http://127.0.0.1:8000/runs/3d4a1f27",
      src: "./images/ui-storyteller.webp",
      alt: "Data Storyteller view in the margin web UI showing underlined numbers and a monthly revenue chart.",
      caption:
        "Every underlined number opens its pandas + SQL receipt, alongside clean CSV, JSON, and Markdown exports.",
    },
    detector: {
      url: "http://127.0.0.1:8000/runs/d6c0d75d",
      src: "./images/ui-detector.webp",
      alt: "AI Code Detector view in the margin web UI with a 0.62 estimate, ticked 0 to 1 ruler, and metadata breakdown.",
      caption:
        "Range estimate on a ticked 0-to-1 ruler, confidence readout, and repository metadata kept separate from the score.",
    },
    "commit-graph": {
      url: "http://127.0.0.1:8000/runs/3b775b3b",
      src: "./images/ui-commit-graph.webp",
      alt: "Commit Graph view in the margin web UI showing chapters of repository history and SVG download.",
      caption:
        "Repository history broken into numbered chapters with SVG tree, JSON, and Markdown export.",
    },
    home: {
      url: "http://127.0.0.1:8000/",
      src: "./images/ui-home.webp",
      alt: "margin web UI home screen with a single inline run bar and the ruled list of installed agents.",
      caption:
        "One inline run bar for whichever agents are installed, ruled against the vertical margin line.",
    },
  };

  const uiTabs = document.querySelectorAll("[data-ui-tab]");
  const uiUrl = document.getElementById("ui-url");
  const uiImg = document.getElementById("ui-screenshot");
  const uiCap = document.getElementById("ui-caption");

  uiTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      const key = tab.getAttribute("data-ui-tab");
      const item = uiScreens[key];
      if (!item) return;

      uiTabs.forEach(function (t) {
        t.setAttribute("aria-selected", t === tab ? "true" : "false");
      });

      if (uiUrl) uiUrl.textContent = item.url;
      if (uiImg) {
        uiImg.src = item.src;
        uiImg.alt = item.alt;
      }
      if (uiCap) uiCap.textContent = item.caption;
    });
  });

  /* ---- Ways to Run Rail --------------------------------------------------------------- */
  const runModes = {
    cli: {
      filename: "terminal",
      raw:
        "pip install margin-cli margin-data-storyteller\n" +
        "margin list\n" +
        "margin info data-storyteller\n" +
        "margin run data-storyteller sales.csv --format json --out report.json",
      html:
        '<span class="c-cm"># Install the CLI and any agents you want</span>\n' +
        "pip install margin-cli margin-data-storyteller\n\n" +
        "margin list                         " +
        '<span class="c-cm"># what is installed</span>\n' +
        "margin info data-storyteller        " +
        '<span class="c-cm"># inspect inputs and options</span>\n' +
        "margin run data-storyteller sales.csv --format json --out report.json",
      note: "Reports write to stdout and logs write to stderr, so CLI output is always safe to pipe into jq or scripts.",
    },
    web: {
      filename: "local web server",
      raw: "pip install margin-api\nmargin-api",
      html:
        '<span class="c-cm"># Start the bundled web UI and HTTP API</span>\n' +
        "pip install margin-api\n" +
        "margin-api                          " +
        '<span class="c-cm"># open http://127.0.0.1:8000</span>\n\n' +
        '<span class="c-cm"># OpenAPI documentation is served at /docs</span>',
      note: "Gives you an auto-generated form for every installed agent, live progress, interactive questions, and downloadable results.",
    },
    docker: {
      filename: "docker compose",
      raw: "git clone https://github.com/Waddah0-0/margin.git\ncd margin\ndocker compose up",
      html:
        '<span class="c-cm"># Run the API and web UI in one container using local Ollama</span>\n' +
        "git clone https://github.com/Waddah0-0/margin.git\n" +
        "cd margin\n" +
        "docker compose up                   " +
        '<span class="c-cm"># open http://localhost:8000</span>',
      note: "Listens only on localhost, runs non-root, and mounts your workspace read-only at /workspace.",
    },
    python: {
      filename: "example.py",
      raw:
        'import asyncio\nfrom margin_core import run_agent\n\nasync def main() -> None:\n    result = await run_agent("echo", {"message": "hello", "repeat": 2})\n    print(result.summary)\n\nasyncio.run(main())',
      html:
        '<span class="c-kw">import</span> asyncio\n' +
        '<span class="c-kw">from</span> margin_core <span class="c-kw">import</span> run_agent\n\n' +
        '<span class="c-kw">async def</span> main() -&gt; <span class="c-kw">None</span>:\n' +
        '    result = <span class="c-kw">await</span> run_agent(<span class="c-str">"echo"</span>, {<span class="c-str">"message"</span>: <span class="c-str">"hello"</span>, <span class="c-str">"repeat"</span>: 2})\n' +
        '    print(result.summary)           <span class="c-cm"># Echoed 11 characters (2x).</span>\n\n' +
        "asyncio.run(main())",
      note: "Use the same typed Pydantic inputs, findings, and evidence objects directly inside your own Python code.",
    },
    custom: {
      filename: "todo_counter.py",
      raw:
        'from margin_core import AgentInput, AgentResult, BaseAgent, Evidence, Finding, RunContext\nfrom pydantic import BaseModel\n\nclass TodoInput(AgentInput):\n    text: str\n\nclass TodoOutput(BaseModel):\n    todos: int\n\nclass TodoCounter(BaseAgent):\n    id = "todo-counter"\n    name = "TODO Counter"\n    InputModel = TodoInput\n    OutputModel = TodoOutput\n\n    async def run(self, input: TodoInput, ctx: RunContext) -> AgentResult:\n        hits = [(n, line) for n, line in enumerate(input.text.splitlines(), 1) if "TODO" in line]\n        return self.make_result(\n            summary=f"Found {len(hits)} TODOs.",\n            output=TodoOutput(todos=len(hits)),\n            findings=[Finding(title="TODOs", summary="Lines with remaining work.", evidence=[\n                Evidence(kind="line", location=str(n), detail=line) for n, line in hits\n            ])],\n        )',
      html:
        '<span class="c-kw">class</span> TodoCounter(BaseAgent):\n' +
        '    id = <span class="c-str">"todo-counter"</span>\n' +
        '    name = <span class="c-str">"TODO Counter"</span>\n' +
        "    InputModel = TodoInput\n" +
        "    OutputModel = TodoOutput\n\n" +
        '    <span class="c-kw">async def</span> run(self, input: TodoInput, ctx: RunContext) -&gt; AgentResult:\n' +
        '        hits = [(n, line) <span class="c-kw">for</span> n, line <span class="c-kw">in</span> enumerate(input.text.splitlines(), 1) <span class="c-kw">if</span> <span class="c-str">"TODO"</span> <span class="c-kw">in</span> line]\n' +
        '        <span class="c-kw">return</span> self.make_result(\n' +
        '            summary=f<span class="c-str">"Found {len(hits)} TODOs."</span>,\n' +
        "            output=TodoOutput(todos=len(hits)),\n" +
        '            findings=[Finding(title=<span class="c-str">"TODOs"</span>, evidence=[\n' +
        '                Evidence(kind=<span class="c-str">"line"</span>, location=str(n), detail=line) <span class="c-kw">for</span> n, line <span class="c-kw">in</span> hits\n' +
        "            ])],\n" +
        "        )",
      note: "Once registered via an entry point, the CLI, HTTP API, and web UI pick it up automatically — including the form from InputModel.",
    },
  };

  const runTabs = document.querySelectorAll("[data-run-tab]");
  const runFilename = document.getElementById("run-filename");
  const runCode = document.getElementById("run-code");
  const runNote = document.getElementById("run-note");
  const runCopyBtn = document.getElementById("run-copy-btn");

  function renderRunMode(key) {
    const mode = runModes[key];
    if (!mode) return;
    runTabs.forEach(function (t) {
      t.setAttribute("aria-selected", t.getAttribute("data-run-tab") === key ? "true" : "false");
    });
    if (runFilename) runFilename.textContent = mode.filename;
    if (runCode) runCode.innerHTML = mode.html;
    if (runNote) runNote.textContent = mode.note;
    if (runCopyBtn) runCopyBtn.setAttribute("data-copy", mode.raw);
  }

  runTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      renderRunMode(tab.getAttribute("data-run-tab"));
    });
  });

  renderRunMode("cli");
})();
