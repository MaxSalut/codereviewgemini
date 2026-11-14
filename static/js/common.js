/* Спільні функції: запити до API, повідомлення про помилки, стан сервісу, рендер звіту. */
(function () {
  "use strict";

  const TYPE = {
    error: { label: "Помилка", plural: "Помилки" },
    bad_practice: { label: "Погана практика", plural: "Погані практики" },
    style: { label: "Стиль", plural: "Стиль" },
  };
  const SEVERITY = { high: "критично", medium: "важливо", low: "дрібниця" };

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /** Мінімальний markdown для порад Gemini: `код` і ```блоки```. */
  function richText(s) {
    const parts = String(s ?? "").split(/```(?:[\w+#-]*)\n?/);
    return parts.map((p, i) => {
      if (i % 2 === 1) return `<pre>${esc(p.replace(/\n$/, ""))}</pre>`;
      return esc(p).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\n/g, "<br>");
    }).join("");
  }

  function toast(msg, ms = 2600) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("is-on");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove("is-on"), ms);
  }

  class ApiError extends Error {
    constructor(code, message, status) { super(message); this.code = code; this.status = status; }
  }

  const ERROR_TITLES = {
    offline: "Немає інтернету",
    server_down: "Сервер недоступний",
    client_timeout: "Задовге очікування",
    timeout: "Задовге очікування",
    rate_limit: "Перевищено ліміт Gemini API",
    daily_quota: "Вичерпано денний ліміт моделі",
    local_rate: "Забагато запитів",
    bad_file: "Неправильний файл",
    file_too_big: "Файл завеликий",
    too_long: "Код задовгий",
    too_short: "Код закороткий",
    empty: "Немає коду",
    not_configured: "Сервіс не налаштовано",
    bad_key: "Проблема з ключем API",
    unavailable: "Gemini тимчасово недоступний",
    network: "Сервер без зв'язку з Gemini",
    blocked: "Відповідь заблоковано",
    db: "Проблема з базою даних",
  };
  const errorTitle = (code) => ERROR_TITLES[code] || "Щось пішло не так";

  /** fetch з таймаутом і зрозумілими помилками українською. */
  async function api(url, { method = "GET", body, timeoutMs = 30000, signal } = {}) {
    if (!navigator.onLine) throw new ApiError("offline", "Комп'ютер не підключено до інтернету. Перевірте Wi-Fi і спробуйте ще раз.", 0);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort("timeout"), timeoutMs);
    if (signal) signal.addEventListener("abort", () => ctrl.abort("cancel"), { once: true });
    let res;
    try {
      res = await fetch(url, {
        method,
        headers: body && !(body instanceof FormData) ? { "Content-Type": "application/json" } : undefined,
        body: body && !(body instanceof FormData) ? JSON.stringify(body) : body,
        signal: ctrl.signal,
      });
    } catch (e) {
      clearTimeout(timer);
      if (ctrl.signal.aborted && ctrl.signal.reason === "cancel") throw new ApiError("cancelled", "Перевірку скасовано.", 0);
      if (ctrl.signal.aborted) throw new ApiError("client_timeout", `Сервер не відповів за ${Math.round(timeoutMs / 1000)} с. Спробуйте ще раз або скоротіть код.`, 0);
      if (!navigator.onLine) throw new ApiError("offline", "Зник інтернет. Перевірте з'єднання і спробуйте ще раз.", 0);
      throw new ApiError("server_down", "Не вдалося зв'язатися з сервером. Можливо, він перезапускається — спробуйте за хвилину.", 0);
    }
    clearTimeout(timer);
    let data = null;
    try { data = await res.json(); } catch (_) { /* не JSON */ }
    if (!res.ok || !data || data.ok === false) {
      const err = data && data.error;
      if (err) throw new ApiError(err.code, err.message, res.status);
      if (res.status === 502 || res.status === 503) throw new ApiError("server_down", "Сервер запускається або перевантажений. Зачекайте 30–60 секунд і спробуйте знову.", res.status);
      throw new ApiError("server", `Сервер повернув помилку ${res.status}.`, res.status);
    }
    return data;
  }

  /** Індикатор стану в шапці: Gemini, база даних, «прокидання» сервера на Render. */
  async function checkHealth() {
    const el = document.getElementById("status");
    if (!el) return null;
    const text = el.querySelector(".status__text");
    const set = (cls, t) => { el.className = "status " + cls; text.textContent = t; };
    set("is-wait", "З'єднання з сервером…");
    const slow = setTimeout(() => set("is-wait", "Сервер прокидається, до хвилини…"), 3500);
    try {
      const h = await api("/api/health", { timeoutMs: 75000 });
      clearTimeout(slow);
      if (!h.gemini_configured) set("is-bad", "Немає ключа Gemini");
      else set("is-ok", `Gemini готовий · ${h.storage}`);
      return h;
    } catch (e) {
      clearTimeout(slow);
      set("is-bad", e.code === "offline" ? "Немає інтернету" : "Сервер недоступний");
      return null;
    }
  }
  window.addEventListener("offline", () => { const el = document.getElementById("status"); if (el) { el.className = "status is-bad"; el.querySelector(".status__text").textContent = "Немає інтернету"; } });
  window.addEventListener("online", () => checkHealth());

  const scoreClass = (s) => (s >= 80 ? "good" : s >= 55 ? "mid" : "bad");

  function fmtMs(ms) { return ms == null ? "—" : ms < 1000 ? `${ms} мс` : `${(ms / 1000).toFixed(1).replace(".", ",")} с`; }
  function fmtUsd(v) {
    if (v == null) return "—";
    if (v === 0) return "$0";
    if (v < 0.01) return "$" + v.toFixed(5).replace(/0+$/, "");
    return "$" + v.toFixed(3);
  }
  const fmtInt = (n) => (n == null ? "—" : Number(n).toLocaleString("uk-UA"));
  function fmtDate(iso) {
    try { return new Date(iso).toLocaleString("uk-UA", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); } catch (_) { return iso; }
  }

  // ---------- Diff (LCS по рядках) ----------
  function lineDiff(a, b) {
    const A = a.split("\n"), B = b.split("\n");
    if (A.length * B.length > 640000) return null;
    const n = A.length, m = B.length;
    const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
      dp[i][j] = A[i].trimEnd() === B[j].trimEnd() ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    const out = []; let i = 0, j = 0;
    while (i < n && j < m) {
      if (A[i].trimEnd() === B[j].trimEnd()) { out.push({ t: "same", a: i + 1, b: j + 1, s: B[j] }); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ t: "del", a: i + 1, s: A[i] }); i++; }
      else { out.push({ t: "add", b: j + 1, s: B[j] }); j++; }
    }
    while (i < n) { out.push({ t: "del", a: i + 1, s: A[i] }); i++; }
    while (j < m) { out.push({ t: "add", b: j + 1, s: B[j] }); j++; }
    return out;
  }

  // ---------- Рендер звіту ----------
  function noteHtml(issue, showLine) {
    const lineBtn = showLine && issue.line > 0 ? `<button class="note__line" data-goto="${issue.line}">рядок ${issue.line}</button>` : "";
    return `<article class="note note--${esc(issue.type)}" data-type="${esc(issue.type)}">
      <div class="note__top">
        <span class="tag tag--${esc(issue.type)}">${esc(TYPE[issue.type]?.label || issue.type)}</span>
        <span class="tag tag--sev">${esc(SEVERITY[issue.severity] || issue.severity)}</span>
        ${lineBtn}
      </div>
      <h4 class="note__title">${esc(issue.title)}</h4>
      <p class="note__desc">${richText(issue.description)}</p>
      <div class="note__fix"><strong>Як виправити:</strong> ${richText(issue.fix)}</div>
    </article>`;
  }

  function listingHtml(code, issues) {
    const lines = code.split("\n");
    const byLine = new Map();
    issues.forEach((it) => { if (it.line > 0 && it.line <= lines.length) { if (!byLine.has(it.line)) byLine.set(it.line, []); byLine.get(it.line).push(it); } });
    const rank = { error: 0, bad_practice: 1, style: 2 };
    let html = "";
    lines.forEach((ln, idx) => {
      const no = idx + 1;
      const its = byLine.get(no) || [];
      const top = its.slice().sort((x, y) => rank[x.type] - rank[y.type])[0];
      html += `<div class="ln ${top ? "ln--" + top.type : ""}" id="ln-${no}" data-types="${its.map((i) => i.type).join(" ")}"><span class="ln__no">${no}</span><span class="ln__code">${esc(ln) || " "}</span></div>`;
      if (its.length) html += `<div class="notes" data-types="${its.map((i) => i.type).join(" ")}">${its.map((i) => noteHtml(i, false)).join("")}</div>`;
    });
    return `<div class="listing"><div class="listing__scroll">${html}</div></div>`;
  }

  function renderReport(root, payload, opts = {}) {
    const { result: r, meta } = payload;
    const code = opts.code || "";
    const issues = r.issues || [];
    const counts = { error: 0, bad_practice: 0, style: 0 };
    issues.forEach((i) => { if (counts[i.type] != null) counts[i.type]++; });
    const sc = scoreClass(r.score);
    const uid = Math.random().toString(36).slice(2, 8);
    const lineCount = code ? code.split("\n").length : 0;
    const orphan = code ? issues.filter((i) => !(i.line > 0 && i.line <= lineCount)) : issues;

    const notesTab = code
      ? `${orphan.length ? `<div class="general">${orphan.map((i) => noteHtml(i, false)).join("")}</div>` : ""}${listingHtml(code, issues)}`
      : `<div class="general">${issues.map((i) => noteHtml(i, true)).join("")}</div>`;

    const diff = code && r.corrected_code ? lineDiff(code.replace(/\s+$/, ""), r.corrected_code.replace(/\s+$/, "")) : null;
    const fixedBody = diff
      ? `<div class="diff"><div class="diff__scroll">${diff.map((d) => `<div class="dl dl--${d.t}"><span class="dl__n">${d.a || ""}</span><span class="dl__n">${d.b || ""}</span><span class="dl__s">${d.t === "add" ? "+" : d.t === "del" ? "−" : ""}</span><span class="dl__c">${esc(d.s) || " "}</span></div>`).join("")}</div></div>`
      : `<div class="listing"><div class="listing__scroll">${(r.corrected_code || "").split("\n").map((l, i) => `<div class="ln"><span class="ln__no">${i + 1}</span><span class="ln__code">${esc(l) || " "}</span></div>`).join("")}</div></div>`;

    const m = meta || {};
    const outTok = (m.output_tokens || 0) + (m.thinking_tokens || 0);
    root.innerHTML = `
      <div class="report">
        <div class="report__head">
          <div class="grade grade--${sc} ${opts.animate ? "is-new" : ""}" role="img" aria-label="Оцінка ${r.score} зі 100">
            <svg viewBox="0 0 116 96" aria-hidden="true"><ellipse cx="58" cy="48" rx="52" ry="40" transform="rotate(-7 58 48)"/></svg>
            <span class="grade__num">${r.score}</span><span class="grade__of">/100</span>
          </div>
          <div>
            <p class="report__lang">${esc(r.detected_language)}${m.model_label ? " · " + esc(m.model_label) : ""}${m.duration_ms ? " · " + fmtMs(m.duration_ms) : ""}</p>
            <p class="report__summary">${richText(r.summary)}</p>
            ${(r.strengths || []).length ? `<ul class="strengths">${r.strengths.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
          </div>
          <div class="filters" role="group" aria-label="Фільтр зауважень">
            <button class="filter" data-filter="all" aria-pressed="true">Усі <b>${issues.length}</b></button>
            ${Object.keys(counts).map((t) => `<button class="filter filter--${t}" data-filter="${t}" aria-pressed="false" ${counts[t] ? "" : "disabled"}><span class="dot"></span>${TYPE[t].plural} <b>${counts[t]}</b></button>`).join("")}
          </div>
        </div>
        ${opts.warning ? `<p class="warn-line">${esc(opts.warning)}</p>` : ""}
        <div class="tabs" role="tablist">
          <button class="tab" role="tab" id="t-n-${uid}" aria-controls="p-n-${uid}" aria-selected="true">Зауваження</button>
          <button class="tab" role="tab" id="t-f-${uid}" aria-controls="p-f-${uid}" aria-selected="false">Виправлений код</button>
          <button class="tab" role="tab" id="t-m-${uid}" aria-controls="p-m-${uid}" aria-selected="false">Час і вартість</button>
        </div>
        <div class="tab-panel" role="tabpanel" id="p-n-${uid}" aria-labelledby="t-n-${uid}">
          ${issues.length ? notesTab : `<div class="clean">Gemini не знайшов проблем у цьому коді.</div>`}
        </div>
        <div class="tab-panel" role="tabpanel" id="p-f-${uid}" aria-labelledby="t-f-${uid}" hidden>
          <div class="fixed__bar">
            ${diff ? `<div class="legend"><span><i style="background:#e6f6ec;border:1px solid #9ad3ad"></i>додано</span><span><i style="background:#fdecea;border:1px solid #f0aaa6"></i>видалено</span></div>` : `<span class="muted">Повна виправлена версія</span>`}
            <button class="btn btn--ghost btn--sm" data-copy>Копіювати код</button>
          </div>
          ${fixedBody}
        </div>
        <div class="tab-panel" role="tabpanel" id="p-m-${uid}" aria-labelledby="t-m-${uid}" hidden>
          <div class="metrics">
            <div class="metric"><span class="metric__v">${fmtMs(m.duration_ms)}</span><span class="metric__l">час відповіді Gemini</span></div>
            <div class="metric"><span class="metric__v">${fmtInt(m.input_tokens)}</span><span class="metric__l">вхідних токенів</span></div>
            <div class="metric"><span class="metric__v">${fmtInt(outTok)}</span><span class="metric__l">вихідних токенів${m.thinking_tokens ? ` (з них ${fmtInt(m.thinking_tokens)} на «роздуми»)` : ""}</span></div>
            <div class="metric"><span class="metric__v">${fmtUsd(m.cost_usd)}</span><span class="metric__l">ціна запиту на платному рівні</span></div>
            <div class="metric"><span class="metric__v">${m.cost_usd != null ? fmtUsd(m.cost_usd * 1000) : "—"}</span><span class="metric__l">за 1000 таких перевірок</span></div>
            <div class="metric"><span class="metric__v">$0</span><span class="metric__l">фактично сплачено (безкоштовний рівень)</span></div>
          </div>
          <div class="explain">
            <p>Ціна = вхідні токени × ціна входу + (вихідні + «роздуми») × ціна виходу, за тарифами Google для моделі ${esc(m.model_label || m.model || "")}.${m.price_note ? " Примітка: " + esc(m.price_note) + "." : ""}</p>
            ${m.attempts > 1 ? `<p>Відповідь отримано з ${m.attempts}-ї спроби: сервер автоматично повторив запит після збою.</p>` : ""}
          </div>
        </div>
      </div>`;

    // Вкладки
    const tabs = root.querySelectorAll(".tab");
    tabs.forEach((tab) => tab.addEventListener("click", () => {
      tabs.forEach((t) => { const on = t === tab; t.setAttribute("aria-selected", on); document.getElementById(t.getAttribute("aria-controls")).hidden = !on; });
    }));
    // Фільтри
    root.querySelectorAll(".filter").forEach((btn) => btn.addEventListener("click", () => {
      const f = btn.dataset.filter;
      root.querySelectorAll(".filter").forEach((b) => b.setAttribute("aria-pressed", b === btn));
      root.querySelectorAll(".note").forEach((n) => n.classList.toggle("is-hidden-type", f !== "all" && n.dataset.type !== f));
      root.querySelectorAll(".notes").forEach((n) => n.classList.toggle("is-hidden-type", f !== "all" && !n.dataset.types.split(" ").includes(f)));
      root.querySelectorAll(".ln[data-types]").forEach((n) => {
        const types = n.dataset.types ? n.dataset.types.split(" ") : [];
        n.style.opacity = f === "all" || !types.length || types.includes(f) ? "" : ".55";
      });
    }));
    // Копіювання
    const copyBtn = root.querySelector("[data-copy]");
    if (copyBtn) copyBtn.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(r.corrected_code || ""); toast("Виправлений код скопійовано"); }
      catch (_) { toast("Не вдалося скопіювати — виділіть код вручну"); }
    });
  }

  window.Rev = { api, ApiError, esc, toast, checkHealth, renderReport, errorTitle, fmtMs, fmtUsd, fmtInt, fmtDate, scoreClass, TYPE };
})();
