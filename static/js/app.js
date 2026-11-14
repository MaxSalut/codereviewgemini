/* Сторінка перевірки: редактор, файли, приклади, запит до сервера, показ результату. */
(function () {
  "use strict";
  const { api, esc, toast, checkHealth, renderReport, errorTitle, fmtMs, fmtUsd } = window.Rev;

  const $ = (id) => document.getElementById(id);
  const codeEl = $("code"), gutter = $("gutter"), editor = $("editor"), countEl = $("count");
  const langEl = $("language"), modelsEl = $("models"), compareEl = $("compare"), submitBtn = $("submit");
  const empty = $("empty"), output = $("output"), fileInput = $("file");

  let cfg = null;
  let currentName = null;
  let busy = null; // AbortController поточного запиту
  const CLIENT_TIMEOUT_MS = 140000;

  // ---------- Редактор ----------
  function updateGutter() {
    const n = codeEl.value ? codeEl.value.split("\n").length : 1;
    if (gutter.childElementCount !== n) {
      let html = "";
      for (let i = 1; i <= n; i++) html += `<span>${i}</span>`;
      gutter.innerHTML = html;
    }
    const chars = codeEl.value.length;
    const lim = cfg ? cfg.limits : { chars: 40000, lines: 800 };
    countEl.textContent = `${n} ${plural(n, "рядок", "рядки", "рядків")} · ${chars.toLocaleString("uk-UA")} символів`;
    countEl.classList.toggle("is-over", chars > lim.chars || n > lim.lines);
    gutter.scrollTop = codeEl.scrollTop;
  }
  function plural(n, one, few, many) {
    const m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }
  codeEl.addEventListener("input", () => { updateGutter(); });
  codeEl.addEventListener("scroll", () => { gutter.scrollTop = codeEl.scrollTop; });
  codeEl.addEventListener("keydown", (e) => {
    if (e.key === "Tab" && !e.shiftKey) {
      e.preventDefault();
      const s = codeEl.selectionStart, en = codeEl.selectionEnd;
      codeEl.setRangeText("    ", s, en, "end");
      updateGutter();
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && document.activeElement !== codeEl) submit(); });

  $("clear").addEventListener("click", () => { codeEl.value = ""; currentName = null; updateGutter(); codeEl.focus(); });

  // ---------- Файли ----------
  function extOf(name) { const i = name.lastIndexOf("."); return i >= 0 ? name.slice(i).toLowerCase() : ""; }
  function langByExt(ext) {
    const map = { ".py": "python", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".h": "c", ".c": "c", ".java": "java", ".cs": "csharp", ".js": "javascript", ".mjs": "javascript", ".ts": "typescript", ".go": "go", ".kt": "kotlin", ".php": "php", ".rs": "rust", ".pas": "pascal", ".dpr": "pascal", ".hs": "haskell", ".sql": "sql" };
    return map[ext];
  }
  function showInputError(code, message) {
    showError({ code, message });
  }
  async function openFile(file) {
    if (!file) return;
    const ext = extOf(file.name);
    const allowed = cfg ? cfg.extensions : [];
    if (allowed.length && !allowed.includes(ext)) {
      return showInputError("bad_file", `Файл «${file.name}» не схожий на код. Підтримуються: ${allowed.join(", ")}.`);
    }
    const max = cfg ? cfg.limits.upload_bytes : 200 * 1024;
    if (file.size > max) return showInputError("file_too_big", `Файл «${file.name}» завеликий (${Math.round(file.size / 1024)} КБ). Максимум — ${Math.round(max / 1024)} КБ.`);
    const buf = await file.arrayBuffer();
    const bytes = new Uint8Array(buf);
    if (bytes.slice(0, 4096).includes(0)) return showInputError("bad_file", `Файл «${file.name}» не текстовий. Завантажте файл з кодом програми.`);
    let text;
    try { text = new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
    catch (_) { text = new TextDecoder("windows-1251").decode(bytes); }
    codeEl.value = text.replace(/^﻿/, "").replace(/\r\n?/g, "\n");
    currentName = file.name;
    const lang = langByExt(ext);
    if (lang) langEl.value = lang;
    updateGutter();
    toast(`Відкрито ${file.name}`);
  }
  fileInput.addEventListener("change", () => { openFile(fileInput.files[0]); fileInput.value = ""; });
  let dragDepth = 0;
  editor.addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; editor.classList.add("is-dragging"); });
  editor.addEventListener("dragover", (e) => e.preventDefault());
  editor.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; editor.classList.remove("is-dragging"); } });
  editor.addEventListener("drop", (e) => {
    e.preventDefault(); dragDepth = 0; editor.classList.remove("is-dragging");
    if (e.dataTransfer.files.length) openFile(e.dataTransfer.files[0]);
  });

  // ---------- Конфігурація ----------
  async function loadConfig() {
    try {
      cfg = await api("/api/config", { timeoutMs: 75000 });
    } catch (e) {
      showError(e);
      return;
    }
    langEl.innerHTML = cfg.languages.map((l) => `<option value="${l.id}">${esc(l.label)}</option>`).join("");
    modelsEl.innerHTML = cfg.models.map((m) => `
      <label title="${esc(m.description)}">
        <input type="radio" name="model" value="${esc(m.id)}" ${m.id === cfg.default_model ? "checked" : ""}>
        <span>${esc(m.short)}</span>
      </label>`).join("");
    $("examples").innerHTML = cfg.examples.map((ex, i) => `<button class="chip-btn" data-ex="${i}" title="${esc(ex.hint)}">${esc(ex.title)}</button>`).join("");
    $("examples").addEventListener("click", (e) => {
      const b = e.target.closest("[data-ex]");
      if (!b) return;
      const ex = cfg.examples[+b.dataset.ex];
      codeEl.value = ex.code.replace(/\n$/, "");
      langEl.value = ex.language;
      currentName = ex.filename;
      updateGutter();
      toast(`Приклад: ${ex.title}`);
    });
    if (cfg.models.length < 2) compareEl.closest(".switch").hidden = true;
    updateGutter();
  }

  compareEl.addEventListener("change", () => {
    modelsEl.querySelectorAll("input").forEach((i) => (i.disabled = compareEl.checked));
    submitBtn.querySelector(".btn__label").textContent = compareEl.checked ? "Порівняти моделі" : "Перевірити код";
  });

  // ---------- Стан результату ----------
  function show(html) {
    empty.hidden = true;
    output.hidden = false;
    output.innerHTML = html;
  }

  function showLoading(compare) {
    const started = Date.now();
    show(`
      <div class="loading">
        <div class="loading__top">
          <h3 class="loading__title">${compare ? "Дві моделі аналізують код" : "Gemini аналізує код"}</h3>
          <span class="loading__time" id="elapsed">0,0 с</span>
        </div>
        <ol class="steps" id="steps">
          <li class="is-active">Надсилаю код на сервер</li>
          <li>Gemini шукає помилки і погані практики</li>
          <li>Формую звіт і зберігаю в історію</li>
        </ol>
        <div class="skeleton" aria-hidden="true"><span style="width:92%"></span><span style="width:78%"></span><span style="width:85%"></span><span style="width:60%"></span><span style="width:70%"></span></div>
        <p class="loading__hint" id="hint">Зазвичай це займає 5–20 секунд.</p>
        <button class="btn btn--ghost btn--sm" id="cancel" style="margin-top:12px">Скасувати</button>
      </div>`);
    $("cancel").addEventListener("click", () => busy && busy.abort());
    const steps = $("steps").children;
    const tick = setInterval(() => {
      const s = (Date.now() - started) / 1000;
      const el = $("elapsed");
      if (!el) return clearInterval(tick);
      el.textContent = s.toFixed(1).replace(".", ",") + " с";
      if (s > 0.8) { steps[0].className = "is-done"; steps[1].className = "is-active"; }
      if (s > 25) $("hint").textContent = "Довше, ніж зазвичай: великий код або сервер щойно прокинувся. Зачекайте ще трохи.";
      if (s > 60) $("hint").textContent = "Gemini відповідає повільно. Якщо буде збій, сервер сам повторить запит.";
    }, 100);
    return () => clearInterval(tick);
  }

  function showError(e) {
    const isWarn = ["empty", "too_short", "too_long", "bad_file", "file_too_big", "local_rate", "cancelled"].includes(e.code);
    show(`
      <div class="alert ${isWarn ? "alert--warn" : ""}" role="alert">
        <h3 class="alert__title">${esc(e.code === "cancelled" ? "Перевірку скасовано" : errorTitle(e.code))}</h3>
        <p class="alert__text">${esc(e.message)}</p>
        ${isWarn ? "" : `<button class="btn btn--primary btn--sm" id="retry">Спробувати ще раз</button>`}
      </div>`);
    const retry = $("retry");
    if (retry) retry.addEventListener("click", submit);
  }

  function bindGoto(root) {
    root.addEventListener("click", (e) => {
      const b = e.target.closest("[data-goto]");
      if (!b) return;
      const ln = root.querySelector(`#ln-${b.dataset.goto}`);
      if (ln) { ln.scrollIntoView({ behavior: "smooth", block: "center" }); ln.classList.remove("is-flash"); void ln.offsetWidth; ln.classList.add("is-flash"); }
    });
  }

  function renderCompare(results, code) {
    const ok = results.filter((r) => r.ok);
    const fastest = ok.length > 1 ? ok.reduce((a, b) => (a.meta.duration_ms <= b.meta.duration_ms ? a : b)) : null;
    const cheapest = ok.length > 1 ? ok.reduce((a, b) => (a.meta.cost_usd <= b.meta.cost_usd ? a : b)) : null;
    const best = ok.length > 1 ? ok.reduce((a, b) => (a.result.issues.length >= b.result.issues.length ? a : b)) : null;
    show(`<div class="compare" role="group" aria-label="Порівняння моделей">
      ${results.map((r, i) => r.ok ? `
        <button class="cmp" data-i="${i}" aria-pressed="${i === results.indexOf(ok[0])}">
          <span class="cmp__name">${esc(r.meta.model_label)}</span>
          <span class="cmp__row">Оцінка коду <b>${r.result.score}/100</b></span>
          <span class="cmp__row">Зауважень <b>${r.result.issues.length}</b></span>
          <span class="cmp__row">Час <b>${fmtMs(r.meta.duration_ms)}</b></span>
          <span class="cmp__row">Ціна запиту <b>${fmtUsd(r.meta.cost_usd)}</b></span>
          <span class="cmp__best">${[r === fastest ? "найшвидша" : "", r === cheapest ? "найдешевша" : "", r === best ? "найдетальніша" : ""].filter(Boolean).join(", ")}</span>
        </button>` : `
        <div class="cmp" aria-disabled="true"><span class="cmp__name">${esc(r.meta.model_label)}</span><span class="cmp__err">${esc(r.error.message)}</span></div>`).join("")}
    </div><div id="cmp-report"></div>`);
    const box = $("cmp-report");
    const pick = (i) => {
      output.querySelectorAll(".cmp[data-i]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.i == i));
      renderReport(box, results[i], { code, animate: true, warning: results[i].history_saved === false ? "Звіт не збережено в історію: база даних недоступна." : "" });
    };
    output.querySelectorAll(".cmp[data-i]").forEach((b) => b.addEventListener("click", () => pick(+b.dataset.i)));
    pick(results.indexOf(ok[0]));
  }

  // ---------- Надсилання ----------
  async function submit() {
    if (busy) return;
    const code = codeEl.value;
    if (!code.trim()) { showError({ code: "empty", message: "Вставте код, відкрийте файл або оберіть один із прикладів нижче." }); codeEl.focus(); return; }
    if (!cfg) await loadConfig();
    if (!cfg) return;
    const lines = code.split("\n").length;
    if (code.length > cfg.limits.chars || lines > cfg.limits.lines) {
      showError({ code: "too_long", message: `Код задовгий: ${lines} рядків, ${code.length.toLocaleString("uk-UA")} символів. Максимум — ${cfg.limits.lines} рядків і ${cfg.limits.chars.toLocaleString("uk-UA")} символів. Перевірте файл частинами.` });
      return;
    }
    const compare = compareEl.checked;
    const model = (modelsEl.querySelector("input:checked") || {}).value;
    busy = new AbortController();
    submitBtn.disabled = true;
    const stop = showLoading(compare);
    if (window.matchMedia("(max-width: 1100px)").matches) $("result").scrollIntoView({ behavior: "smooth", block: "start" });
    try {
      const body = { code, language: langEl.value, filename: currentName, model };
      if (compare) {
        body.models = cfg.models.slice(0, 2).map((m) => m.id);
        const data = await api("/api/compare", { method: "POST", body, timeoutMs: CLIENT_TIMEOUT_MS, signal: busy.signal });
        stop();
        renderCompare(data.results, code.replace(/\r\n?/g, "\n").replace(/\t/g, "    ").replace(/^\n+|\n+$/g, ""));
      } else {
        const data = await api("/api/review", { method: "POST", body, timeoutMs: CLIENT_TIMEOUT_MS, signal: busy.signal });
        stop();
        show(`<div id="single"></div>`);
        renderReport($("single"), data, {
          code: code.replace(/\r\n?/g, "\n").replace(/\t/g, "    ").replace(/^\n+|\n+$/g, ""),
          animate: true,
          warning: [
            data.meta && data.meta.fallback_from
              ? (data.meta.fallback_reason === "daily_quota"
                  ? `Денний ліміт безкоштовного рівня для ${data.meta.fallback_from_label} вичерпано, тому звіт зробила резервна модель ${data.meta.model_label}.`
                  : `${data.meta.fallback_from_label} зараз перевантажена на боці Google, тому звіт зробила резервна модель ${data.meta.model_label}.`)
              : "",
            data.history_saved === false ? "Звіт не збережено в історію: база даних недоступна." : "",
          ].filter(Boolean).join(" "),
        });
      }
      bindGoto(output);
    } catch (e) {
      stop();
      showError(e);
    } finally {
      busy = null;
      submitBtn.disabled = false;
    }
  }
  submitBtn.addEventListener("click", submit);

  updateGutter();
  checkHealth();
  loadConfig();
})();
