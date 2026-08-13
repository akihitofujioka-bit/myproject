"use strict";
/* 議会だより 原稿編集ツール — 画面側。
   通信先はこのパソコンの中（127.0.0.1）だけ。 */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const state = {
  project: null,
  slots: [],
  images: [],
  currentArticle: null,
  issues: [],
};

// ------------------------------------------------------------------ 通信

async function api(path, body, opts = {}) {
  const res = await fetch("/api/" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const ct = res.headers.get("Content-Type") || "";
  if (!ct.includes("application/json")) {
    if (!res.ok) throw new Error("通信に失敗しました");
    return res.blob();
  }
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "エラーが発生しました");
  return data;
}

let toastTimer;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), isErr ? 6000 : 3000);
}

async function guard(fn) {
  try { await fn(); } catch (e) { toast(e.message, true); }
}

function fileToBase64(file) {
  return new Promise((ok, ng) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(",")[1]);
    r.onerror = () => ng(new Error(file.name + " を読み込めませんでした"));
    r.readAsDataURL(file);
  });
}

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------------ 画面遷移

$$("#steps button").forEach((b) =>
  b.addEventListener("click", () => showStep(b.dataset.step)));

function showStep(name) {
  $$("#steps button").forEach((b) => b.classList.toggle("on", b.dataset.step === name));
  $$(".pane").forEach((p) => p.classList.toggle("on", p.id === "pane-" + name));
  if (name === "layout") loadSlots();
  if (name === "photo") renderPhotos();
  if (name === "edit") renderArticleList();
}

function modal(title, html) {
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = html;
  $("#modal").hidden = false;
}
$("#modalClose").addEventListener("click", () => ($("#modal").hidden = true));
$("#modal").addEventListener("click", (e) => {
  if (e.target.id === "modal") $("#modal").hidden = true;
});

// ------------------------------------------------------------------ ① 号

async function loadWorkspace() {
  const d = await api("workspace");
  $("#wsPath").textContent = "保存先: " + d.workspace;
  const el = $("#projectList");
  if (!d.projects.length) {
    el.innerHTML = "<p class='empty'>保存済みの号はまだありません。</p>";
    return;
  }
  el.innerHTML = d.projects.map((p) => `
    <div class="item">
      <div class="main">
        <div class="name">${esc(p.title)}</div>
        <div class="meta">記事 ${p.articles} 件 ／ 最終更新 ${esc(p.updated || "—")}</div>
      </div>
      <button data-open="${esc(p.name)}">開く</button>
    </div>`).join("");
  $$("[data-open]", el).forEach((b) =>
    b.addEventListener("click", () => guard(async () => {
      const r = await api("project/open", { name: b.dataset.open });
      setProject(r.project);
      toast("「" + r.project.title + "」を開きました");
      showStep("import");
    })));
}

$("#btnCreate").addEventListener("click", () => guard(async () => {
  const r = await api("project/create", {
    title: $("#newTitle").value.trim(),
    issue_no: $("#newNo").value.trim(),
    issue_date: $("#newDate").value.trim(),
  });
  setProject(r.project);
  toast("作成しました: " + r.project.root);
  await loadWorkspace();
  showStep("import");
}));

function setProject(p) {
  state.project = p;
  $("#projLabel").textContent = p ? p.title + "（" + p.articles.length + "件）" : "プロジェクト未選択";
  $("#templateState").textContent = p && p.has_template ? "読み込み済み" : "未読み込み";
  renderImportList();
  renderArticleList();
  renderPhotos();
}

async function refresh() {
  const r = await api("project");
  setProject(r.project);
}

// ------------------------------------------------------------------ ② 取り込み

function wireDrop(dropEl, onFiles) {
  ["dragenter", "dragover"].forEach((ev) =>
    dropEl.addEventListener(ev, (e) => {
      e.preventDefault(); dropEl.classList.add("hot");
    }));
  ["dragleave", "drop"].forEach((ev) =>
    dropEl.addEventListener(ev, (e) => {
      e.preventDefault(); dropEl.classList.remove("hot");
    }));
  dropEl.addEventListener("drop", (e) => onFiles([...e.dataTransfer.files]));
}

wireDrop($("#dropManu"), importManuscripts);
$("#btnPickManu").addEventListener("click", () => $("#fileManu").click());
$("#fileManu").addEventListener("change", (e) => importManuscripts([...e.target.files]));

function importManuscripts(files) {
  guard(async () => {
    if (!state.project) throw new Error("先に号を作成または選択してください");
    let ok = 0;
    for (const f of files) {
      const data = await fileToBase64(f);
      await api("article/import", { name: f.name, data });
      ok++;
    }
    await refresh();
    toast(ok + " 件の原稿を取り込みました");
  });
}

$("#btnPaste").addEventListener("click", () => guard(async () => {
  if (!state.project) throw new Error("先に号を作成または選択してください");
  await api("article/paste", {
    text: $("#pasteText").value,
    title: $("#pasteTitle").value.trim(),
    author: $("#pasteAuthor").value.trim(),
    normalize: $("#optNormalize").checked,
  });
  $("#pasteText").value = ""; $("#pasteTitle").value = ""; $("#pasteAuthor").value = "";
  await refresh();
  toast("記事を追加しました");
}));

function renderImportList() {
  const el = $("#importList");
  const arts = state.project ? state.project.articles : [];
  $("#artCount").textContent = arts.length;
  if (!arts.length) {
    el.innerHTML = "<p class='empty'>まだ原稿がありません。</p>";
    return;
  }
  el.innerHTML = arts.map((a) => `
    <div class="item">
      <div class="main">
        <div class="name">${esc(a.title || a.source_file || "（見出し未設定）")}</div>
        <div class="meta">${esc(a.author || "執筆者不明")} ／ ${countOf(a.body)} 字 ／ ${esc(a.status)}</div>
      </div>
      <button data-edit="${a.id}">編集</button>
      <button class="danger" data-del="${a.id}">削除</button>
    </div>`).join("");
  $$("[data-edit]", el).forEach((b) =>
    b.addEventListener("click", () => { showStep("edit"); openArticle(b.dataset.edit); }));
  $$("[data-del]", el).forEach((b) =>
    b.addEventListener("click", () => guard(async () => {
      if (!confirm("この記事を削除します。よろしいですか？\n（元の原稿ファイルは残ります）")) return;
      await api("article/delete", { id: b.dataset.del });
      await refresh();
      toast("削除しました");
    })));
}

function countOf(s) {
  let n = 0;
  for (const ch of String(s || "")) {
    if (ch === "\n" || ch === "\r") continue;
    n += /[　-鿿＀-￯]/.test(ch) ? 1 : 0.5;
  }
  return Math.ceil(n);
}

// ------------------------------------------------------------------ ③ 校正

function renderArticleList() {
  const el = $("#editArticleList");
  const arts = state.project ? state.project.articles : [];
  if (!arts.length) {
    el.innerHTML = "<p class='empty'>原稿がありません。</p>";
    return;
  }
  el.innerHTML = arts.map((a) => `
    <div class="item ${state.currentArticle === a.id ? "on" : ""}" data-open="${a.id}">
      <div class="main">
        <div class="name">${esc(a.title || "（見出し未設定）")}</div>
        <div class="meta">${esc(a.author || "—")} ／ ${countOf(a.body)} 字</div>
      </div>
    </div>`).join("");
  $$("[data-open]", el).forEach((b) =>
    b.addEventListener("click", () => openArticle(b.dataset.open)));
}

function article(id) {
  return (state.project?.articles || []).find((a) => a.id === id);
}

function openArticle(id) {
  state.currentArticle = id;
  renderArticleList();
  const a = article(id);
  if (!a) return;
  $("#editorArea").innerHTML = `
    <div class="card">
      <div class="row">
        <label>見出し<input id="fTitle" value="${esc(a.title)}"></label>
        <label>執筆者<input id="fAuthor" value="${esc(a.author)}"></label>
        <button class="ghost" id="btnTitles">見出し候補</button>
      </div>
      <div class="row">
        <label>リード文<input id="fLead" value="${esc(a.lead)}"></label>
      </div>
      <div class="row">
        <label>字数上限<input id="fLimit" type="number" min="0" value="${a.limit_chars || 0}"></label>
        <label>1行の字数<input id="fCpl" type="number" min="0" value="${a.chars_per_line || 0}"></label>
        <label>行数<input id="fLines" type="number" min="0" value="${a.lines || 0}"></label>
        <label>状態<select id="fStatus">
          ${["下書き", "校正済み", "割付済み", "確定"].map((s) =>
            `<option ${s === a.status ? "selected" : ""}>${s}</option>`).join("")}
        </select></label>
      </div>
    </div>

    <div class="card">
      <div class="row" style="margin-bottom:6px">
        <h2 style="margin:0;flex:1">本文</h2>
        <span class="counter" id="counter"></span>
      </div>
      <textarea id="fBody" rows="16">${esc(a.body)}</textarea>
      <div class="row" style="margin-top:10px">
        <button class="primary" id="btnSave">保存</button>
        <button id="btnCheck">校正する</button>
        <button id="btnShorten">冗長表現を縮める</button>
        <button id="btnFit">枠に合わせて要約</button>
        <button class="ghost" id="btnRevert">取り込んだ原稿に戻す</button>
      </div>
    </div>

    <div class="card">
      <div class="tabs">
        <button class="on" data-tab="issues">校正結果</button>
        <button data-tab="photos">この記事の写真</button>
      </div>
      <div id="tab-issues"><p class="empty">「校正する」を押すと結果が出ます。</p></div>
      <div id="tab-photos" hidden></div>
    </div>`;

  $("#fBody").addEventListener("input", updateCounter);
  updateCounter();

  $$(".tabs button").forEach((b) => b.addEventListener("click", () => {
    $$(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    $("#tab-issues").hidden = b.dataset.tab !== "issues";
    $("#tab-photos").hidden = b.dataset.tab !== "photos";
    if (b.dataset.tab === "photos") renderArticlePhotos(id);
  }));

  $("#btnSave").addEventListener("click", () => guard(saveArticle));
  $("#btnCheck").addEventListener("click", () => guard(async () => {
    await saveArticle(true);
    await runProofread();
  }));
  $("#btnShorten").addEventListener("click", () => guard(async () => {
    await saveArticle(true);
    const r = await api("article/shorten", { id, drop_fillers: false });
    showDiff("冗長表現を縮める", $("#fBody").value, r.text,
      `${r.before} 字 → ${r.chars} 字`);
  }));
  $("#btnFit").addEventListener("click", () => guard(async () => {
    await saveArticle(true);
    const r = await api("article/fit", { id });
    showDiff("枠に合わせて要約", $("#fBody").value, r.text,
      `${r.before} 字 → ${r.chars} 字（${r.method}）\n${r.note || ""}`);
  }));
  $("#btnTitles").addEventListener("click", () => guard(async () => {
    await saveArticle(true);
    const r = await api("article/titles", { id });
    const list = r.titles.length
      ? r.titles.map((t) => `<div class="item"><div class="main">${esc(t)}</div>
          <button data-pick="${esc(t)}">これにする</button></div>`).join("")
      : "<p class='empty'>候補を作れませんでした。本文を確認してください。</p>";
    modal("見出し候補", `<div class="pad">
      <p class="hint">本文から機械的に作った候補です。そのまま使わず、必ず手直ししてください。</p>
      <div class="list">${list}</div>
      ${r.lead ? `<h2 style="margin-top:16px">リード文の候補</h2>
        <div class="item"><div class="main">${esc(r.lead)}</div>
        <button data-lead="${esc(r.lead)}">これにする</button></div>` : ""}
    </div>`);
    $$("[data-pick]").forEach((b) => b.addEventListener("click", () => {
      $("#fTitle").value = b.dataset.pick; $("#modal").hidden = true;
    }));
    $$("[data-lead]").forEach((b) => b.addEventListener("click", () => {
      $("#fLead").value = b.dataset.lead; $("#modal").hidden = true;
    }));
  }));
  $("#btnRevert").addEventListener("click", () => guard(async () => {
    if (!confirm("編集内容を破棄して、取り込んだままの原稿に戻します。よろしいですか？")) return;
    $("#fBody").value = a.raw;
    updateCounter();
    toast("取り込んだ原稿に戻しました（保存すると確定します）");
  }));
}

function updateCounter() {
  const a = article(state.currentArticle);
  if (!a) return;
  const text = $("#fBody").value;
  const n = countOf(text);
  const limit = Number($("#fLimit").value) || 0;
  const cpl = Number($("#fCpl").value) || 0;
  const maxLines = Number($("#fLines").value) || 0;
  let label = n + " 字";
  let cls = "counter";
  if (limit) {
    label += " / " + limit + " 字";
    cls += n > limit ? " over" : " ok";
  }
  if (cpl) {
    let lines = 0;
    for (const para of text.split("\n")) {
      lines += para.trim() ? Math.ceil(countOf(para) / cpl) : 1;
    }
    label += " ／ " + lines + (maxLines ? " / " + maxLines : "") + " 行";
    if (maxLines && lines > maxLines) cls = "counter over";
  }
  const el = $("#counter");
  if (el) { el.textContent = label; el.className = cls; }
}

async function saveArticle(quiet = false) {
  const id = state.currentArticle;
  if (!id) return;
  const r = await api("article/save", {
    article: {
      id,
      title: $("#fTitle").value,
      author: $("#fAuthor").value,
      lead: $("#fLead").value,
      body: $("#fBody").value,
      limit_chars: Number($("#fLimit").value) || 0,
      chars_per_line: Number($("#fCpl").value) || 0,
      lines: Number($("#fLines").value) || 0,
      status: $("#fStatus").value,
    },
  });
  const i = state.project.articles.findIndex((a) => a.id === id);
  if (i >= 0) state.project.articles[i] = r.article;
  renderArticleList();
  if (!quiet) toast("保存しました");
}

async function runProofread() {
  const id = state.currentArticle;
  const r = await api("article/proofread", { id });
  state.issues = r.issues;
  const el = $("#tab-issues");
  const s = r.summary.by_severity;
  const head = `<p class="hint">
    <span class="sev error">要修正 ${s.error || 0}</span>
    <span class="sev warn">確認 ${s.warn || 0}</span>
    <span class="sev info">参考 ${s.info || 0}</span>
    　本文 ${r.chars} 字</p>`;

  if (!r.issues.length) {
    el.innerHTML = head + "<p class='empty'>指摘はありません。</p>";
    return;
  }
  const fixable = r.issues.filter((i) => i.auto_fixable);
  el.innerHTML = head + `
    ${fixable.length ? `<div class="row"><button class="primary" id="btnFixAll">
      自動で直せる ${fixable.length} 件をまとめて修正</button></div>` : ""}
    <div class="issues">${r.issues.map(issueRow).join("")}</div>`;

  $("#btnFixAll")?.addEventListener("click", () => guard(async () => {
    const r2 = await api("article/autofix", { id });
    $("#fBody").value = r2.article.body;
    updateCounter();
    await refresh();
    await runProofread();
    toast(r2.changed ? "まとめて修正しました" : "修正対象はありませんでした");
  }));

  $$("[data-fix]", el).forEach((b) => b.addEventListener("click", () => guard(async () => {
    const r2 = await api("article/autofix", { id, rule_ids: [b.dataset.fix] });
    $("#fBody").value = r2.article.body;
    updateCounter();
    await refresh();
    await runProofread();
  })));

  $$("[data-jump]", el).forEach((b) => b.addEventListener("click", () => {
    const ta = $("#fBody");
    const [s0, e0] = b.dataset.jump.split(",").map(Number);
    ta.focus();
    ta.setSelectionRange(s0, e0);
    // 選択位置がだいたい真ん中に来るようにスクロール
    const ratio = s0 / Math.max(1, ta.value.length);
    ta.scrollTop = ratio * ta.scrollHeight - ta.clientHeight / 2;
  }));
}

function issueRow(i) {
  const sev = { error: "要修正", warn: "確認", info: "参考" }[i.severity] || i.severity;
  return `<div class="issue">
    <span class="sev ${i.severity}">${sev}</span>
    <div class="body">
      <div><span class="frag">${esc(i.text)}</span>　${esc(i.message)}</div>
      <div class="meta" style="font-size:11.5px;color:var(--sub)">${esc(i.category)}</div>
    </div>
    <div class="acts">
      <button data-jump="${i.start},${i.end}">位置</button>
      ${i.auto_fixable ? `<button data-fix="${esc(i.rule_id)}">直す</button>` : ""}
    </div>
  </div>`;
}

function showDiff(title, before, after, note) {
  modal(title, `<div class="pad">
    <p class="hint">${esc(note || "")}</p>
    <p class="hint"><strong>要約は機械的な処理です。</strong>
      内容が変わっていないか、必ず目で確かめてから反映してください。</p>
    <div class="diff">
      <div><h3>いまの本文</h3><textarea readonly>${esc(before)}</textarea></div>
      <div><h3>処理後</h3><textarea id="diffAfter">${esc(after)}</textarea></div>
    </div>
    <div class="row" style="margin-top:12px">
      <button class="primary" id="btnApplyDiff">これを本文に反映する</button>
      <button class="ghost" id="btnCancelDiff">やめる</button>
    </div>
  </div>`);
  $("#btnApplyDiff").addEventListener("click", () => {
    $("#fBody").value = $("#diffAfter").value;
    updateCounter();
    $("#modal").hidden = true;
    toast("反映しました（「保存」を押すと確定します）");
  });
  $("#btnCancelDiff").addEventListener("click", () => ($("#modal").hidden = true));
}

function renderArticlePhotos(id) {
  const a = article(id);
  const all = state.project.photos;
  const el = $("#tab-photos");
  const mine = all.filter((p) => a.photos.includes(p.id));
  el.innerHTML = `
    <div class="photogrid">${mine.map(photoCard).join("") ||
      "<p class='empty'>この記事に紐づいた写真はありません。「④ 写真」で追加できます。</p>"}</div>`;
  wirePhotoCards(el);
}

// ------------------------------------------------------------------ ④ 写真

wireDrop($("#dropPhoto"), uploadPhotos);
$("#btnPickPhoto").addEventListener("click", () => $("#filePhoto").click());
$("#filePhoto").addEventListener("change", (e) => uploadPhotos([...e.target.files]));

function uploadPhotos(files) {
  guard(async () => {
    if (!state.project) throw new Error("先に号を作成または選択してください");
    for (const f of files) {
      const data = await fileToBase64(f);
      await api("photo/upload", { name: f.name, data, article_id: state.currentArticle || "" });
    }
    await refresh();
    toast(files.length + " 枚を取り込みました");
  });
}

function photoCard(p) {
  const info = p.info || {};
  const note = info.warning
    ? `<div class="warn">⚠ ${esc(info.warning)}</div>`
    : `<div class="ok">${info.width}×${info.height}px ／ ${esc(info.orientation || "")}
        ／ 印刷可 最大 ${(info.max_print_cm || [])[0] || "?"}cm</div>`;
  const opts = ['<option value="">（差し込み先なし）</option>']
    .concat(state.images.map((im) =>
      `<option value="${esc(im.name)}" ${im.name === p.slot ? "selected" : ""}>${esc(im.name)}</option>`))
    .join("");
  return `<div class="photocard" data-photo="${p.id}">
    <img src="/api/photo/thumb?id=${encodeURIComponent(p.id)}" alt="" loading="lazy">
    <div class="pc-body">
      ${note}
      <input data-f="caption" value="${esc(p.caption)}" placeholder="写真の説明文">
      <input data-f="credit" value="${esc(p.credit)}" placeholder="撮影者（任意）">
      <select data-f="slot">${opts}</select>
      <div class="row" style="margin:0">
        <button data-pv="${p.id}">切り出し確認</button>
        <button class="danger" data-rm="${p.id}">削除</button>
      </div>
    </div>
  </div>`;
}

function renderPhotos() {
  const el = $("#photoGrid");
  if (!el) return;
  const ps = state.project ? state.project.photos : [];
  el.innerHTML = ps.length
    ? ps.map(photoCard).join("")
    : "<p class='empty'>写真がありません。</p>";
  wirePhotoCards(el);
}

function wirePhotoCards(root) {
  $$(".photocard", root).forEach((card) => {
    const id = card.dataset.photo;
    $$("[data-f]", card).forEach((inp) =>
      inp.addEventListener("change", () => guard(async () => {
        await api("photo/save", { photo: { id, [inp.dataset.f]: inp.value } });
        await refresh();
        toast("保存しました");
      })));
  });
  $$("[data-rm]", root).forEach((b) => b.addEventListener("click", () => guard(async () => {
    if (!confirm("この写真を削除します。よろしいですか？")) return;
    await api("photo/delete", { id: b.dataset.rm });
    await refresh();
    toast("削除しました");
  })));
  $$("[data-pv]", root).forEach((b) => b.addEventListener("click", () => {
    const p = state.project.photos.find((x) => x.id === b.dataset.pv);
    const q = "/api/photo/preview?id=" + encodeURIComponent(p.id) +
      (p.slot ? "&slot=" + encodeURIComponent(p.slot) : "");
    modal("枠に合わせた切り出し", `<div class="pad">
      <p class="hint">${p.slot
        ? "差し込み先「" + esc(p.slot) + "」の縦横比に合わせて切り出した結果です。"
        : "差し込み先が未設定のため、元の写真のまま表示しています。"}</p>
      <img src="${q}" style="max-width:100%;border:1px solid var(--line)">
    </div>`);
  }));
}

// ------------------------------------------------------------------ ⑤ 割付

$("#btnPickTemplate").addEventListener("click", () => $("#fileTemplate").click());
$("#fileTemplate").addEventListener("change", (e) => guard(async () => {
  const f = e.target.files[0];
  if (!f) return;
  if (!state.project) throw new Error("先に号を作成または選択してください");
  toast("様式を読み込んでいます…");
  const data = await fileToBase64(f);
  const r = await api("template/upload", { name: f.name, data });
  state.slots = r.slots; state.images = r.images;
  $("#templateState").textContent =
    `読み込み済み（枠 ${r.slots.length} か所、画像 ${r.images.length} 点）`;
  renderSlots(); renderImageSlots();
  await refresh();
  toast("様式を読み込みました");
}));

async function loadSlots() {
  if (!state.project || !state.project.has_template) return;
  if (state.slots.length) { renderSlots(); renderImageSlots(); return; }
  const r = await api("template/slots");
  state.slots = r.slots; state.images = r.images;
  $("#templateState").textContent =
    `読み込み済み（枠 ${r.slots.length} か所、画像 ${r.images.length} 点）`;
  renderSlots(); renderImageSlots();
}

$("#slotSearch").addEventListener("input", renderSlots);
$("#slotFilterText").addEventListener("change", renderSlots);

function renderSlots() {
  const tb = $("#slotTable tbody");
  const q = $("#slotSearch").value.trim();
  const onlyText = $("#slotFilterText").checked;
  const arts = state.project ? state.project.articles : [];

  const rows = state.slots.filter((s) => {
    if (onlyText && s.kind !== "marker" && !s.chars) return false;
    if (q && !(s.sample.includes(q) || s.name.includes(q))) return false;
    return true;
  });

  if (!rows.length) {
    tb.innerHTML = "<tr><td colspan='6' class='empty'>該当する枠がありません。</td></tr>";
    return;
  }

  tb.innerHTML = rows.map((s) => {
    const assigned = arts.find((a) => a.slot === s.id);
    const titleAt = arts.find((a) => a.title_slot === s.id);
    const opts = ['<option value="">—</option>'].concat(
      arts.flatMap((a) => {
        const label = esc(a.title || a.author || "無題");
        return [
          `<option value="${a.id}|body" ${assigned?.id === a.id ? "selected" : ""}>本文: ${label}</option>`,
          `<option value="${a.id}|title" ${titleAt?.id === a.id ? "selected" : ""}>見出し: ${label}</option>`,
        ];
      })).join("");
    return `<tr>
      <td>${s.page_hint || "—"}</td>
      <td>${esc(s.name)}</td>
      <td>${esc(s.guess || s.kind)}${s.vertical ? " <small>縦</small>" : ""}</td>
      <td class="sample">${esc(s.sample.slice(0, 70))}</td>
      <td>${s.chars || "—"}</td>
      <td><select data-slot="${esc(s.id)}">${opts}</select></td>
    </tr>`;
  }).join("");

  $$("[data-slot]", tb).forEach((sel) =>
    sel.addEventListener("change", () => guard(async () => {
      const slotId = sel.dataset.slot;
      const [aid, kind] = sel.value.split("|");

      // 同じ枠に割り当てられていた記事の設定を外す
      for (const a of arts) {
        const patch = {};
        if (a.slot === slotId) patch.slot = "";
        if (a.title_slot === slotId) patch.title_slot = "";
        if (Object.keys(patch).length)
          await api("article/save", { article: { id: a.id, ...patch } });
      }
      if (aid) {
        const patch = kind === "title"
          ? { title_slot: slotId }
          : { slot: slotId, page: state.slots.find((x) => x.id === slotId)?.page_hint || 0 };
        // 枠の字数を上限の目安として引き継ぐ
        const s = state.slots.find((x) => x.id === slotId);
        if (kind !== "title" && s && s.chars) patch.limit_chars = s.chars;
        await api("article/save", { article: { id: aid, ...patch } });
      }
      await refresh();
      renderSlots();
      toast("割り当てを変更しました");
    })));
}

function renderImageSlots() {
  const el = $("#imageSlots");
  if (!state.images.length) {
    el.innerHTML = "<p class='empty'>様式に画像が見つかりません。</p>";
    return;
  }
  const ps = state.project ? state.project.photos : [];
  el.innerHTML = state.images.map((im) => {
    const used = ps.find((p) => p.slot === im.name);
    return `<div class="item">
      <img src="/api/template/image?name=${encodeURIComponent(im.name)}"
           style="width:74px;height:56px;object-fit:cover;border:1px solid var(--line);border-radius:4px">
      <div class="main">
        <div class="name">${esc(im.name)}</div>
        <div class="meta">${Math.round(im.size / 1024)} KB ／
          ${used ? "差し替え予定: " + esc(used.caption || used.id) : "そのまま"}</div>
      </div>
    </div>`;
  }).join("");
}

// ------------------------------------------------------------------ ⑥ 書き出し

$("#btnExport").addEventListener("click", () => guard(async () => {
  if (!state.project) throw new Error("先に号を作成または選択してください");
  toast("書き出しています…");
  const r = await api("export", {
    filename: $("#expName").value.trim(),
    pdf: $("#expPdf").checked,
  });
  const warn = r.unassigned.length
    ? `<p class="warn" style="color:var(--warn)">⚠ 差し込み先が未設定の記事: ${
        r.unassigned.map(esc).join("、")}</p>` : "";
  const bad = r.photos.filter((p) => !p.ok);
  $("#exportResult").innerHTML = `
    <div class="card" style="margin-top:12px">
      <h2>書き出しました</h2>
      <p>${esc(r.docx)}</p>
      <p class="hint">枠 ${r.filled} か所に差し込みました。</p>
      ${warn}
      ${bad.length ? `<p style="color:var(--warn)">⚠ 写真: ${
        bad.map((b) => esc(b.message)).join("、")}</p>` : ""}
      ${r.pdf ? `<p>PDF: ${esc(r.pdf)}</p>` :
        (r.pdf_error ? `<p class="hint">${esc(r.pdf_error)}</p>` : "")}
      <div class="row">
        <button id="btnDl">Word をダウンロード</button>
        ${r.pdf ? '<button id="btnDlPdf">PDF をダウンロード</button>' : ""}
      </div>
    </div>`;
  const base = r.docx.split(/[\\/]/).pop();
  $("#btnDl").addEventListener("click", () => {
    window.location = "/api/download?file=" + encodeURIComponent(base);
  });
  $("#btnDlPdf")?.addEventListener("click", () => {
    window.location = "/api/download?file=" +
      encodeURIComponent(r.pdf.split(/[\\/]/).pop());
  });
  toast("書き出しが終わりました");
}));

$("#btnPreview").addEventListener("click", () => guard(async () => {
  const r = await api("export/preview", {});
  const blob = new Blob([r.html], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  modal("紙面プレビュー（下見用）", `<iframe src="${url}"></iframe>`);
}));

// ------------------------------------------------------------------ 設定

$("#btnSettings").addEventListener("click", () => guard(async () => {
  if (!state.project) throw new Error("先に号を作成または選択してください");
  const st = state.project.settings || {};
  const checks = {
    style: "表記ルール（等→など など）", typo: "明らかな誤字",
    confusion: "同音異義語の確認", grammar: "文法（ら抜き・助詞）",
    punct: "記号・句読点・数字", read: "読みやすさ（長い文）",
    ruby: "難読語のルビ提案", noun: "固有名詞の誤記",
  };
  const on = new Set(st.checks || []);
  const d = await api("dict/get", {});
  modal("設定", `<div class="pad">
    <h2>校正でチェックする項目</h2>
    <div class="list">${Object.entries(checks).map(([k, v]) =>
      `<label class="check"><input type="checkbox" data-chk="${k}" ${
        on.has(k) ? "checked" : ""}> ${esc(v)}</label>`).join("")}</div>
    <div class="row" style="margin-top:14px">
      <label>1文の上限字数<input id="setMaxSent" type="number" value="${st.max_sentence || 90}"></label>
      <label class="check"><input type="checkbox" id="setNum" ${
        st.normalize_numbers !== false ? "checked" : ""}>
        取り込み時に数字を縦書きの慣行に合わせる（1桁は全角・2桁以上は半角）</label>
    </div>
    <h2 style="margin-top:18px">この号だけの固有名詞辞書</h2>
    <p class="hint">議員名・地名・施設名などを1行に1つ書いてください。
      ここに登録した語に似た表記が原稿にあると、誤記として指摘します。</p>
    <textarea id="setTerms" rows="7">${esc((d.dict.terms || []).join("\n"))}</textarea>
    <div class="row" style="margin-top:12px">
      <button class="primary" id="btnSaveSettings">保存</button>
    </div>
  </div>`);
  $("#btnSaveSettings").addEventListener("click", () => guard(async () => {
    const picked = $$("[data-chk]").filter((c) => c.checked).map((c) => c.dataset.chk);
    await api("project/settings", {
      settings: {
        checks: picked,
        max_sentence: Number($("#setMaxSent").value) || 90,
        normalize_numbers: $("#setNum").checked,
      },
    });
    await api("dict/save", {
      dict: {
        ...d.dict,
        terms: $("#setTerms").value.split("\n").map((s) => s.trim()).filter(Boolean),
      },
    });
    await refresh();
    $("#modal").hidden = true;
    toast("設定を保存しました");
  }));
}));

// ------------------------------------------------------------------ 起動

guard(loadWorkspace);
