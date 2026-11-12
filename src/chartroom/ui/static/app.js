"use strict";
// Токен живёт только в памяти страницы: после обновления нужно войти снова.
let token = null;
const $ = (id) => document.getElementById(id);

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;  // только textContent: ответы модели не парсятся как HTML
  if (className) node.className = className;
  return node;
}

async function api(path, options = {}) {
  const headers = token ? { Authorization: "Bearer " + token } : {};
  const response = await fetch(path, { ...options, headers: { ...headers, ...options.headers } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "Запрос не выполнен";
    throw new Error(response.status === 503 ? "Сервис временно недоступен, повторите позже" : detail);
  }
  return body;
}

function show(box, ...nodes) { box.replaceChildren(...nodes); }
function showError(box, error) { show(box, el("p", error.message, "bad")); }

function renderAnswer(box, data) {
  const nodes = [el("p", data.answer, data.refusal ? "answer refusal" : "answer")];
  if (data.citation_warning) nodes.push(el("p", "Часть ссылок модели не прошла проверку и удалена.", "warn"));
  for (const c of data.citations) {
    const page = c.page ? ", стр. " + c.page : "";
    const quote = el("blockquote");
    quote.append(el("strong", c.title + " — " + c.section_path + page), el("div", "«" + c.quote + "»"));
    nodes.push(quote);
  }
  if (data.tool_calls && data.tool_calls.length) {
    const list = el("ul");
    for (const t of data.tool_calls) list.append(el("li", t.name + " " + JSON.stringify(t.args) + (t.ok ? "" : " — " + t.error)));
    nodes.push(el("small", "Вызовы инструментов:"), list);
  }
  show(box, ...nodes);
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("login-error").textContent = "";
  try {
    const form = new URLSearchParams({ username: $("email").value, password: $("password").value });
    token = (await api("/auth/login", { method: "POST", body: form })).access_token;
    $("password").value = "";
    $("login").hidden = true; $("app").hidden = false;
    loadTemplates();
  } catch (error) { $("login-error").textContent = error.message; }
});

$("logout").addEventListener("click", () => { token = null; location.reload(); });

for (const button of document.querySelectorAll("nav [data-tab]")) {
  button.addEventListener("click", () => {
    for (const b of document.querySelectorAll("nav [data-tab]")) {
      b.setAttribute("aria-current", String(b === button));
      $("tab-" + b.dataset.tab).hidden = b !== button;
    }
  });
}

$("ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  show($("ask-result"), el("p", "Ищу ответ…", "muted"));
  try {
    const data = await api($("mode").value, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: $("question").value }),
    });
    renderAnswer($("ask-result"), data);
  } catch (error) { showError($("ask-result"), error); }
});

async function loadTemplates() {
  try {
    const templates = await api("/report-templates");
    $("template").replaceChildren(...templates.map((t) => Object.assign(el("option", t.title), { value: t.name })));
  } catch (error) { showError($("report-result"), error); }
}

$("report-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  show($("report-result"), el("p", "Разбираю…", "muted"));
  try {
    const report = await api("/reports/extract", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template: $("template").value, text: $("report-text").value }),
    });
    const issues = el("ul");
    for (const i of report.issues) issues.append(el("li", i.field + ": " + i.message, "bad"));
    show($("report-result"),
      el("p", "Отчёт №" + report.id + ", статус: " + report.status, report.issues.length ? "warn" : "ok"),
      el("pre", JSON.stringify(report.data, null, 2)),
      report.issues.length ? issues : el("p", "Замечаний нет.", "ok"));
  } catch (error) { showError($("report-result"), error); }
});

$("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData();
  form.append("title", $("u-title").value); form.append("version", $("u-version").value);
  form.append("language", $("u-language").value); form.append("issued_on", $("u-date").value);
  form.append("file", $("u-file").files[0]);
  try {
    const data = await api("/documents", { method: "POST", body: form });
    show($("upload-result"), el("p", "Принято, индексация: " + data.version.status + " (документ №" + data.document_id + ")", "ok"));
  } catch (error) { showError($("upload-result"), error); }
});
