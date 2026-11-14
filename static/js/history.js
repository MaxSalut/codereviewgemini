/* Сторінка «Історія»: дані з Supabase, підсумки, графіки, перегляд старих звітів. */
(function () {
  "use strict";
  const { api, esc, checkHealth, renderReport, errorTitle, fmtMs, fmtUsd, fmtInt, fmtDate, scoreClass, TYPE } = window.Rev;
  const $ = (id) => document.getElementById(id);

  function bars(el, items, { label, value, cls, fmt = (v) => v }) {
    if (!items.length) { el.innerHTML = `<p class="muted">Поки немає даних.</p>`; return; }
    const max = Math.max(1, ...items.map(value));
    el.innerHTML = items.map((it) => `
      <div class="bar">
        <span>${esc(label(it))}</span>
        <span class="bar__track"><span class="bar__fill ${cls ? cls(it) : ""}" style="width:${(value(it) / max) * 100}%"></span></span>
        <span class="bar__val">${fmt(value(it), it)}</span>
      </div>`).join("");
  }

  function lineChart(el, points) {
    if (points.length < 2) { el.innerHTML = `<p class="muted">Графік з'явиться після двох і більше перевірок.</p>`; return; }
    const W = 520, H = 170, L = 30, R = 8, T = 10, B = 22;
    const x = (i) => L + (i * (W - L - R)) / (points.length - 1);
    const y = (v) => T + (1 - v / 100) * (H - T - B);
    const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.score).toFixed(1)}`).join(" ");
    const area = `${d} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`;
    const grid = [0, 50, 100].map((v) => `<line class="axis" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="ax-label" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join("");
    const pts = points.map((p, i) => `<circle class="pt" cx="${x(i)}" cy="${y(p.score)}" r="3.2"><title>${fmtDate(p.created_at)}: ${p.score}</title></circle>`).join("");
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Оцінки останніх ${points.length} перевірок від ${points[0].score} до ${points[points.length - 1].score}">
      ${grid}<path class="area" d="${area}" opacity=".6"/><path class="path" d="${d}"/>${pts}
      <text class="ax-label" x="${L}" y="${H - 4}">${fmtDate(points[0].created_at)}</text>
      <text class="ax-label" x="${W - R}" y="${H - 4}" text-anchor="end">${fmtDate(points[points.length - 1].created_at)}</text>
    </svg>`;
  }

  function modelsTable(el, rows) {
    if (!rows.length) { el.innerHTML = `<p class="muted">Поки немає даних.</p>`; return; }
    el.innerHTML = `<table class="mini-table"><thead><tr><th>Модель</th><th class="num">Перевірок</th><th class="num">Сер. час</th><th class="num">Ціна</th><th class="num">Оцінка</th></tr></thead><tbody>
      ${rows.map((m) => `<tr><td>${esc(m.model)}</td><td class="num">${m.count}</td><td class="num">${fmtMs(m.avg_ms)}</td><td class="num">${fmtUsd(m.avg_cost_usd)}</td><td class="num">${m.avg_score}</td></tr>`).join("")}
    </tbody></table>`;
  }

  function table(el, items) {
    if (!items.length) {
      el.innerHTML = `<div class="empty-history">Ще немає жодної перевірки. <a href="/">Перевірте перший код</a> — і він з'явиться тут.</div>`;
      return;
    }
    el.innerHTML = `<table class="rev-table"><thead><tr><th>Дата</th><th>Мова</th><th>Файл</th><th>Модель</th><th>Зауваження</th><th class="num">Час</th><th class="num">Оцінка</th></tr></thead><tbody>
      ${items.map((r) => `<tr tabindex="0" data-id="${r.id}">
        <td data-label="Дата">${fmtDate(r.created_at)}</td>
        <td data-label="Мова">${esc(r.language || "—")}</td>
        <td data-label="Файл" class="muted">${esc(r.filename || "вставлений код")}</td>
        <td data-label="Модель">${esc(r.model || "—")}</td>
        <td data-label="Зауваження"><span class="counts">
          <span title="${TYPE.error.plural}"><i class="dot" style="background:var(--red)"></i>${r.errors_count ?? 0}</span>
          <span title="${TYPE.bad_practice.plural}"><i class="dot" style="background:var(--amber)"></i>${r.bad_practice_count ?? 0}</span>
          <span title="${TYPE.style.plural}"><i class="dot" style="background:var(--teal)"></i>${r.style_count ?? 0}</span>
        </span></td>
        <td data-label="Час" class="num">${fmtMs(r.duration_ms)}</td>
        <td data-label="Оцінка" class="num"><span class="score-pill score-pill--${scoreClass(r.score)}">${r.score ?? "—"}</span></td>
      </tr>`).join("")}
    </tbody></table>`;
    el.querySelectorAll("tr[data-id]").forEach((tr) => {
      tr.addEventListener("click", () => openItem(tr.dataset.id));
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") openItem(tr.dataset.id); });
    });
  }

  const modal = $("modal");
  $("modal-close").addEventListener("click", () => modal.close());
  modal.addEventListener("click", (e) => { if (e.target === modal) modal.close(); });

  async function openItem(id) {
    const body = $("modal-body");
    body.innerHTML = `<div class="loading"><p class="muted">Завантажую звіт…</p></div>`;
    $("modal-title").textContent = "Звіт перевірки";
    modal.showModal();
    try {
      const { item } = await api(`/api/history/${id}`);
      $("modal-title").textContent = `${item.language || ""} · ${fmtDate(item.created_at)}`;
      if (!item.result) { body.innerHTML = `<div class="alert alert--warn"><p class="alert__text">Для цього запису повний звіт не збережено.</p></div>`; return; }
      renderReport(body, {
        result: item.result,
        meta: { model: item.model, model_label: item.model, duration_ms: item.duration_ms, input_tokens: item.input_tokens, output_tokens: item.output_tokens, cost_usd: Number(item.cost_usd) },
      });
    } catch (e) {
      body.innerHTML = `<div class="alert"><h3 class="alert__title">${esc(errorTitle(e.code))}</h3><p class="alert__text">${esc(e.message)}</p></div>`;
    }
  }

  async function load() {
    const errBox = $("history-error");
    errBox.hidden = true;
    $("storage-note").textContent = "Завантажую дані з бази…";
    try {
      const data = await api("/api/history?limit=300", { timeoutMs: 75000 });
      const s = data.stats;
      $("storage-note").textContent = `Дані зберігаються в ${data.storage}. Натисніть на рядок, щоб відкрити повний звіт.`;
      const set = (k, v) => { document.querySelector(`[data-k="${k}"]`).textContent = v; };
      set("total", fmtInt(s.total));
      set("avg_score", s.avg_score ?? "—");
      set("total_issues", fmtInt(s.total_issues ?? 0));
      set("avg_duration", fmtMs(s.avg_duration_ms));
      set("avg_cost", s.total ? fmtUsd(s.avg_cost_usd) : "—");
      bars($("chart-types"), s.by_type || [], { label: (it) => it.label, value: (it) => it.count, cls: (it) => "bar__fill--" + it.type });
      lineChart($("chart-scores"), s.timeline || []);
      bars($("chart-langs"), s.by_language || [], { label: (it) => it.language, value: (it) => it.count, fmt: (v) => v });
      modelsTable($("chart-models"), s.by_model || []);
      table($("table"), data.items);
    } catch (e) {
      $("storage-note").textContent = "";
      errBox.hidden = false;
      errBox.innerHTML = `<div class="alert" role="alert" style="margin:0"><h3 class="alert__title">${esc(errorTitle(e.code))}</h3><p class="alert__text">${esc(e.message)}</p><button class="btn btn--primary btn--sm" id="retry-h">Спробувати ще раз</button></div>`;
      $("retry-h").addEventListener("click", load);
    }
  }

  $("reload").addEventListener("click", load);
  checkHealth();
  load();
})();
