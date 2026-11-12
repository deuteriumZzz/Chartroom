"use strict";
// Токен живёт только в памяти страницы: после обновления нужно войти снова.
let token = null;
let templates = [];
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
    if (response.status === 429) throw new Error("Слишком много запросов, попробуйте через минуту");
    if (response.status === 503) throw new Error("Сервис временно недоступен, повторите позже");
    throw new Error(typeof body.detail === "string" ? body.detail : "Запрос не выполнен");
  }
  return body;
}

const json = (data) => ({ headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
function show(box, ...nodes) { box.replaceChildren(...nodes); }
function showError(box, error) { show(box, el("p", error.message, "bad")); }

// ---------- Вход ----------

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

// ---------- Чат ----------

function citationNodes(citations) {
  return citations.map((c) => {
    const page = c.page ? ", стр. " + c.page : "";
    const quote = el("blockquote");
    quote.append(el("strong", c.title + " — " + c.section_path + page), el("div", "«" + c.quote + "»"));
    return quote;
  });
}

function feedbackNode(queryId) {
  const box = el("div", undefined, "feedback");
  box.append(el("small", "Ответ полезен?"));
  for (const [label, useful] of [["Да", true], ["Нет", false]]) {
    const button = el("button", label);
    button.type = "button";
    button.addEventListener("click", async () => {
      try {
        await api("/ask/" + queryId + "/feedback", { method: "POST", ...json({ useful }) });
        box.replaceChildren(el("small", "Спасибо, отзыв учтён.", "ok"));
      } catch (error) { box.replaceChildren(el("small", error.message, "bad")); }
    });
    box.append(button);
  }
  return box;
}

function botMessage(data) {
  const msg = el("div", undefined, "msg bot");
  msg.append(el("p", data.answer, data.refusal ? "answer refusal" : "answer"));
  if (data.citation_warning) msg.append(el("p", "Часть ссылок модели не прошла проверку и удалена.", "warn"));
  msg.append(...citationNodes(data.citations));
  if (data.tool_calls && data.tool_calls.length) {
    const list = el("ul");
    for (const t of data.tool_calls) list.append(el("li", t.name + " " + JSON.stringify(t.args) + (t.ok ? "" : " — " + t.error)));
    msg.append(el("small", "Вызовы инструментов:"), list);
  }
  if (data.query_id) msg.append(feedbackNode(data.query_id));  // отзывы есть только у обычных вопросов
  return msg;
}

$("ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = $("question").value.trim();
  const pending = el("div", "Ищу ответ…", "msg bot muted");
  $("chat").append(el("div", question, "msg user"), pending);
  $("question").value = "";
  pending.scrollIntoView({ block: "nearest" });
  try {
    pending.replaceWith(botMessage(await api($("mode").value, { method: "POST", ...json({ question }) })));
  } catch (error) { pending.replaceWith(el("div", error.message, "msg bot bad")); }
});

// ---------- Отчёты ----------

async function loadTemplates() {
  try {
    templates = await api("/report-templates");
    $("template").replaceChildren(...templates.map((t) => Object.assign(el("option", t.title), { value: t.name })));
  } catch (error) { showError($("report-result"), error); }
}

function fieldInput(name, spec, value) {
  let input;
  if (spec.enum || spec.type === "boolean") {
    input = el("select");
    input.append(Object.assign(el("option", "—"), { value: "" }));
    for (const option of spec.enum || [true, false]) input.append(Object.assign(el("option", String(option)), { value: String(option) }));
  } else {
    input = el("input");
    input.type = spec.format === "date" ? "date" : spec.format === "time" ? "time" : ["number", "integer"].includes(spec.type) ? "number" : "text";
  }
  input.id = "f-" + name;
  input.value = value === null || value === undefined ? "" : String(value);
  return input;
}

function typedValue(raw, spec) {
  if (raw === "") return undefined;  // пустое поле не отправляем: PATCH меняет только заполненные
  if (spec.type === "boolean") return raw === "true";
  if (["number", "integer"].includes(spec.type)) return Number(raw);
  return raw;
}

function renderReport(report) {
  const schema = templates.find((t) => t.id === report.template_id).schema;
  const fields = el("div", undefined, "fields");
  for (const [name, spec] of Object.entries(schema.properties)) {
    const label = el("label", name + (schema.required?.includes(name) ? " *" : ""));
    label.htmlFor = "f-" + name;
    fields.append(label, fieldInput(name, spec, report.data[name]));
  }
  const status = el("p", undefined, report.issues.length ? "warn" : "ok");
  status.append("Отчёт №" + report.id + " ", el("span", report.status, "badge"));
  const issues = el("ul");
  for (const i of report.issues) issues.append(el("li", i.field + ": " + i.message, "bad"));

  const save = async (accept) => {
    const data = {};
    for (const [name, spec] of Object.entries(schema.properties)) {
      const value = typedValue($("f-" + name).value, spec);
      if (value !== undefined) data[name] = value;
    }
    try {
      renderReport(await api("/reports/" + report.id, { method: "PATCH", ...json({ data, accept }) }));
    } catch (error) { $("report-error").textContent = error.message; }
  };
  const actions = el("div", undefined, "actions");
  const saveButton = el("button", "Сохранить правки");
  saveButton.type = "button"; saveButton.addEventListener("click", () => save(false));
  actions.append(saveButton);
  if (report.status !== "accepted") {
    const accept = el("button", "Принять (captain / admin)");
    accept.type = "button"; accept.addEventListener("click", () => save(true));
    actions.append(accept);
  }
  const error = el("p", "", "bad"); error.id = "report-error";
  show($("report-result"), status, report.issues.length ? issues : el("p", "Замечаний нет.", "ok"), fields, actions, error);
}

$("report-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  show($("report-result"), el("p", "Разбираю…", "muted"));
  try {
    renderReport(await api("/reports/extract", { method: "POST", ...json({ template: $("template").value, text: $("report-text").value }) }));
  } catch (error) { showError($("report-result"), error); }
});

// ---------- Документы ----------

function renderStatus(documentId, version) {
  const line = el("p", undefined, version.status === "failed" ? "bad" : "ok");
  line.append("Документ №" + documentId + ", версия " + version.label + ": ", el("span", version.status, "badge"));
  if (version.error) line.append(" — " + version.error);
  const refresh = el("button", "Обновить статус");
  refresh.type = "button";
  refresh.addEventListener("click", async () => {
    try {
      const doc = await api("/documents/" + documentId + "/status");
      renderStatus(documentId, doc.versions.find((v) => v.id === version.id));
    } catch (error) { showError($("upload-result"), error); }
  });
  show($("upload-result"), line, refresh);
}

$("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData();
  form.append("title", $("u-title").value); form.append("version", $("u-version").value);
  form.append("language", $("u-language").value); form.append("issued_on", $("u-date").value);
  form.append("file", $("u-file").files[0]);
  try {
    const data = await api("/documents", { method: "POST", body: form });
    renderStatus(data.document_id, data.version);
  } catch (error) { showError($("upload-result"), error); }
});
