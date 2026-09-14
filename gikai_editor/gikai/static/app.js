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
  outline: null,        // 構成（表紙→行政報告→…）ごとに記事をまとめたもの
  picked: new Set(),    // ②で選んでいる原稿の id（一括削除に使う）
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
  if (name === "layout") guard(loadLayout);
  if (name === "photo") renderPhotos();
  if (name === "edit") guard(refreshOutline);
}

/* ダイアログ。開くのは modal()、閉じるのは closeModal() に集約する。
   中身が空のまま開くことがないよう、開くときに必ず内容を入れる。 */
function modal(title, html) {
  $("#modalTitle").textContent = title || "";
  $("#modalBody").innerHTML = html || "";
  $("#modal").hidden = false;
  // 「閉じる」にキーボードの焦点を当てる（Enter でも閉じられるように）
  setTimeout(() => $("#modalClose").focus(), 0);
}

function closeModal() {
  const m = $("#modal");
  if (m.hidden) return;
  m.hidden = true;
  // 中身を空にして、次に開くまで残らないようにする
  $("#modalTitle").textContent = "";
  $("#modalBody").innerHTML = "";
  // 「閉じられた」ことを確認ダイアログ側が知る必要があるので知らせる
  m.dispatchEvent(new CustomEvent("modalclosed"));
}

/* 取り返しのつかない操作の前に出す確認ダイアログ。
   何をするのか・元に戻せるのかを日本語で書いて見せる。
   閉じる・Esc・背景クリックはすべて「やめる」扱いにする。 */
function confirmModal(title, html, okLabel = "実行する") {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => {
      if (done) return;
      done = true;
      $("#modal").removeEventListener("modalclosed", onClosed);
      if (v) closeModal();
      resolve(v);
    };
    const onClosed = () => finish(false);
    modal(title, `<div class="pad">${html}
      <div class="row" style="margin-top:16px">
        <button class="danger" id="cfmOk">${esc(okLabel)}</button>
        <button class="ghost" id="cfmNo">やめる</button>
      </div></div>`);
    $("#modal").addEventListener("modalclosed", onClosed);
    $("#cfmOk").addEventListener("click", () => finish(true));
    $("#cfmNo").addEventListener("click", () => closeModal());
    setTimeout(() => $("#cfmNo").focus(), 0);
  });
}

$("#modalClose").addEventListener("click", closeModal);
// 背景（暗い部分）をクリックしても閉じる
$("#modal").addEventListener("click", (e) => {
  if (e.target.id === "modal") closeModal();
});
// Esc キーで閉じる
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" || e.key === "Esc") closeModal();
});
// 念のため、読み込み直後は必ず閉じた状態から始める
$("#modal").hidden = true;

// ------------------------------------------------------------------ ① 号

async function loadWorkspace() {
  const el = $("#projectList");
  let d;
  try {
    d = await api("workspace");
  } catch (e) {
    // 一覧が取れなくても、画面が空白のまま固まらないようにする
    el.innerHTML = "<p class='empty'>保存済みの号を読み込めませんでした。" +
      esc(e.message) + "</p>";
    throw e;
  }
  $("#wsPath").textContent = "保存先: " + d.workspace;
  if (!d.projects.length) {
    el.innerHTML = "<p class='empty'>保存済みの号はありません。" +
      "上の「新しい号をはじめる」から作成してください。</p>";
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
      await setProject(r.project);
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
  await setProject(r.project);
  toast("作成しました: " + r.project.root);
  await loadWorkspace();
  showStep("import");
}));

async function setProject(p) {
  state.project = p;
  $("#projLabel").textContent = p ? p.title + "（" + p.articles.length + "件）" : "プロジェクト未選択";
  $("#templateState").textContent = p && p.has_template ? "読み込み済み" : "未読み込み";
  await loadOutline();
  renderImportList();
  renderOutline();
  renderPhotos();
}

async function refresh() {
  const r = await api("project");
  await setProject(r.project);
}

/* 構成（表紙→行政報告→…）を読み直す。
   一覧が出せないだけで作業が止まらないよう、失敗しても投げない。 */
async function loadOutline() {
  if (!state.project) { state.outline = null; return; }
  try {
    state.outline = await api("outline");
  } catch (e) {
    state.outline = null;
    toast("構成を読み込めませんでした: " + e.message, true);
  }
}

async function refreshOutline() {
  await loadOutline();
  renderOutline();
  renderImportList();
}

/** 画面で選べる区分の一覧（「未分類」は区分ではないので外す）。 */
function sectionDefs() {
  return (state.outline?.sections || []).filter((s) => s.id);
}

function sectionName(id) {
  return sectionDefs().find((s) => s.id === id)?.name || "";
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

  // 消えた記事が選択に残らないようにする
  const alive = new Set(arts.map((a) => a.id));
  [...state.picked].forEach((id) => { if (!alive.has(id)) state.picked.delete(id); });

  if (!arts.length) {
    el.innerHTML = "<p class='empty'>まだ原稿がありません。</p>";
    updateSelInfo();
    return;
  }

  const defs = sectionDefs();
  el.innerHTML = arts.map((a) => {
    const picked = state.picked.has(a.id);
    const opts = defs.map((s) =>
      `<option value="${esc(s.id)}" ${s.id === a.section ? "selected" : ""}>${esc(s.name)}</option>`).join("");
    const why = a.section_why ? "判定のもと: " + a.section_why : "区分をお選びください";
    return `
    <div class="item ${picked ? "picked" : ""}">
      <input class="pick" type="checkbox" data-pick="${a.id}" ${picked ? "checked" : ""}
             title="まとめて削除するときに選びます">
      <div class="main">
        <div class="name">${esc(a.title || a.source_file || "（見出し未設定）")}</div>
        <div class="meta">${esc(a.author || "執筆者不明")} ／ ${countOf(a.body)} 字 ／ ${esc(a.status)}</div>
      </div>
      ${defs.length
        ? `<select class="secpick" data-sec="${a.id}" title="${esc(why)}">
             <option value="" ${a.section ? "" : "selected"}>（未分類）</option>${opts}
           </select>`
        : `<span class="secbadge ${a.section ? "" : "none"}">${esc(sectionName(a.section) || "未分類")}</span>`}
      <button data-edit="${a.id}">編集</button>
      <button class="danger" data-del="${a.id}">削除</button>
    </div>`;
  }).join("");

  $$("[data-pick]", el).forEach((c) =>
    c.addEventListener("change", () => {
      if (c.checked) state.picked.add(c.dataset.pick);
      else state.picked.delete(c.dataset.pick);
      c.closest(".item").classList.toggle("picked", c.checked);
      updateSelInfo();
    }));

  // 区分の選び直し。自動判定が外れていても手で直せるようにしてある
  $$("[data-sec]", el).forEach((s) =>
    s.addEventListener("change", () => guard(async () => {
      await api("article/save", {
        article: { id: s.dataset.sec, section: s.value, order: 999,
                   section_why: s.value ? "手で選びました" : "" },
      });
      await refresh();
      toast(s.value ? "「" + sectionName(s.value) + "」に入れました" : "未分類に戻しました");
    })));

  $$("[data-edit]", el).forEach((b) =>
    b.addEventListener("click", () => { showStep("edit"); openArticle(b.dataset.edit); }));
  $$("[data-del]", el).forEach((b) =>
    b.addEventListener("click", () => guard(() => deleteArticles([b.dataset.del]))));

  updateSelInfo();
}

function updateSelInfo() {
  const n = state.picked.size;
  const total = state.project ? state.project.articles.length : 0;
  $("#selInfo").textContent = n + " 件を選択中";
  $("#btnDeleteSel").disabled = n === 0;
  const all = $("#chkAll");
  all.checked = total > 0 && n === total;
  all.indeterminate = n > 0 && n < total;
}

$("#chkAll").addEventListener("change", () => {
  const arts = state.project ? state.project.articles : [];
  state.picked = $("#chkAll").checked ? new Set(arts.map((a) => a.id)) : new Set();
  renderImportList();
});

$("#btnDeleteSel").addEventListener("click", () =>
  guard(() => deleteArticles([...state.picked])));

/* 記事の削除。取り込んだ原本は消さないので、消しても取り込み直せる。
   何を消すのかを一覧で見せてから実行する。 */
async function deleteArticles(ids) {
  ids = (ids || []).filter(Boolean);
  if (!ids.length) return;
  const arts = (state.project?.articles || []).filter((a) => ids.includes(a.id));
  const names = arts.map((a) =>
    `<li>${esc(a.title || a.source_file || a.author || a.id)}</li>`).join("");
  const ok = await confirmModal(
    ids.length > 1 ? "選んだ原稿をまとめて削除します" : "この原稿を削除します",
    `<p>次の <b>${ids.length} 件</b>を、この号の記事一覧から取り除きます。</p>
     <ul class="hint" style="margin:8px 0 12px 18px">${names}</ul>
     <p class="hint"><b>消えるもの:</b> 記事としての登録（見出し・本文の編集内容・区分・写真との結びつけ）。</p>
     <p class="hint"><b>残るもの:</b> 取り込んだ元のファイル（<code>manuscripts</code> フォルダ）と、
       写真（<code>photos</code> フォルダ）。消したあとでも取り込み直せます。</p>
     <p class="hint">ただし、<b>ここで直した本文や要約は元に戻せません。</b>
       手を入れた原稿が含まれていないか確かめてください。</p>`,
    ids.length > 1 ? `${ids.length} 件を削除する` : "削除する");
  if (!ok) return;
  const r = await api("article/delete_many", { ids });
  ids.forEach((id) => state.picked.delete(id));
  if (ids.includes(state.currentArticle)) {
    state.currentArticle = null;
    $("#editorArea").innerHTML = "<p class='empty'>左の一覧から記事を選んでください。</p>";
  }
  await refresh();
  toast(r.deleted + " 件を削除しました（元の原稿ファイルは残っています）");
}

// 区分の自動振り分け
$("#btnAssignSections").addEventListener("click", () =>
  guard(() => assignSections(true)));

async function assignSections(onlyUnassigned) {
  const r = await api("outline/assign", { only_unassigned: onlyUnassigned });
  await refresh();
  const done = r.assigned.map((x) =>
    `<div class="item"><div class="main">
       <div class="name">${esc(x.label)}</div>
       <div class="meta">${esc(x.why)}</div></div>
     <span class="secbadge">${esc(x.section_name || x.section)}</span></div>`).join("");
  const ng = r.unknown.map((x) =>
    `<div class="item"><div class="main">
       <div class="name">${esc(x.label)}</div>
       <div class="meta">${esc(x.why)}</div></div>
     <span class="secbadge none">未分類</span></div>`).join("");
  modal("区分の振り分け結果", `<div class="pad">
    <p class="hint">ファイル名・見出し・本文の書き出しから見当を付けた結果です。
      違っていれば一覧の選択欄で直してください。</p>
    <h2>振り分けた（${r.assigned.length} 件）</h2>
    <div class="list">${done || "<p class='empty'>ありませんでした。</p>"}</div>
    <h2 style="margin-top:16px">判定できなかった（${r.unknown.length} 件）</h2>
    <div class="list">${ng || "<p class='empty'>ありませんでした。</p>"}</div>
    <div class="row" style="margin-top:16px">
      <button id="btnAssignAll">すでに区分がついたものも含めて、すべて振り分け直す</button>
    </div>
    <p class="hint">※ 手で直した区分も上書きされます。</p>
  </div>`);
  $("#btnAssignAll")?.addEventListener("click", () => guard(() => assignSections(false)));
  toast(`${r.assigned.length} 件を振り分けました` +
    (r.unknown.length ? `（${r.unknown.length} 件は判定できませんでした）` : ""));
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

/* 紙面の並び（表紙 → 行政報告 → … → 最終ページ）どおりに記事を出す。
   上から順に片付けていけば1号ぶんが仕上がる、という形にしてある。 */
function renderOutline() {
  const el = $("#outlineList");
  if (!el) return;
  if (!state.project) {
    el.innerHTML = "<p class='empty'>先に①で号を作成するか、保存済みの号を開いてください。</p>";
    return;
  }
  const groups = state.outline?.sections || [];
  if (!groups.length) {
    el.innerHTML = "<p class='empty'>構成を読み込めませんでした。</p>";
    return;
  }
  const total = groups.reduce((n, g) => n + g.count, 0);
  if (!total) {
    el.innerHTML = "<p class='empty'>原稿がありません。②で取り込んでください。</p>";
    return;
  }

  el.innerHTML = `<div class="outline">` + groups.map((g) => {
    const body = g.count
      ? g.articles.map((a, i) => oitem(a, i, g.count)).join("")
      : `<div class="oempty">${g.optional
          ? "この号は無し（ある号だけ使います）"
          : "まだ原稿がありません"}</div>`;
    return `<div class="ogroup ${g.count ? "" : "empty"}">
      <div class="ohead" title="${esc(g.note)}">${esc(g.name)}
        <span class="n">${g.count ? `${g.done}/${g.count} 本 ・ ${g.chars} 字` : "0 本"}</span>
      </div>${body}</div>`;
  }).join("") + `</div>`;

  $$("[data-open]", el).forEach((b) =>
    b.addEventListener("click", () => openArticle(b.dataset.open)));
  $$("[data-mv]", el).forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      guard(async () => {
        state.outline = await api("outline/move",
          { id: b.dataset.mv, delta: Number(b.dataset.delta) });
        renderOutline();
      });
    }));
}

function oitem(a, i, n) {
  const done = ["校正済み", "割付済み", "確定"].includes(a.status);
  return `<div class="oitem ${state.currentArticle === a.id ? "on" : ""}" data-open="${a.id}">
    <div class="main">
      <div class="nm">${esc(a.title || a.source_file || "（見出し未設定）")}</div>
      <div class="mt">${esc(a.author || "—")} ／ ${countOf(a.body)} 字</div>
    </div>
    <span class="ostat ${done ? "done" : "draft"}">${esc(a.status)}</span>
    <span class="mv">
      <button data-mv="${a.id}" data-delta="-1" title="1つ上へ" ${i === 0 ? "disabled" : ""}>▲</button>
      <button data-mv="${a.id}" data-delta="1" title="1つ下へ" ${i === n - 1 ? "disabled" : ""}>▼</button>
    </span>
  </div>`;
}

function article(id) {
  return (state.project?.articles || []).find((a) => a.id === id);
}

function openArticle(id) {
  state.currentArticle = id;
  renderOutline();
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
        <label>紙面の区分<select id="fSection">
          <option value="" ${a.section ? "" : "selected"}>（未分類）</option>
          ${sectionDefs().map((s) =>
            `<option value="${esc(s.id)}" ${s.id === a.section ? "selected" : ""}>${esc(s.name)}</option>`).join("")}
        </select></label>
      </div>
      ${a.section_why ? `<p class="hint">区分の判定のもと: ${esc(a.section_why)}</p>` : ""}
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
      $("#fTitle").value = b.dataset.pick; closeModal();
    }));
    $$("[data-lead]").forEach((b) => b.addEventListener("click", () => {
      $("#fLead").value = b.dataset.lead; closeModal();
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
  const before = article(id);
  const sect = $("#fSection") ? $("#fSection").value : (before?.section || "");
  const payload = {
    id,
    title: $("#fTitle").value,
    author: $("#fAuthor").value,
    lead: $("#fLead").value,
    body: $("#fBody").value,
    limit_chars: Number($("#fLimit").value) || 0,
    chars_per_line: Number($("#fCpl").value) || 0,
    lines: Number($("#fLines").value) || 0,
    status: $("#fStatus").value,
    section: sect,
  };
  // 区分を手で変えたときは、移った先の区分の末尾に置く
  if (before && sect !== before.section) {
    payload.order = 999;
    payload.section_why = sect ? "手で選びました" : "";
  }
  const r = await api("article/save", { article: payload });
  const i = state.project.articles.findIndex((a) => a.id === id);
  if (i >= 0) state.project.articles[i] = r.article;
  // 見出しや状態が変わると構成の一覧の見え方も変わるので読み直す
  await refreshOutline();
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
    closeModal();
    toast("反映しました（「保存」を押すと確定します）");
  });
  $("#btnCancelDiff").addEventListener("click", closeModal);
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

function articleOfPhoto(pid) {
  return (state.project?.articles || []).find((a) => a.photos.includes(pid));
}

function photoCard(p) {
  const info = p.info || {};
  const art = articleOfPhoto(p.id);
  const link = art
    ? `<span class="link">記事: ${esc(art.title || art.author || "無題")}</span>`
    : '<span class="link none">記事に未結び付け</span>';
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
      ${link}
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

/* 様式の枠・画像の一覧を用意する。写真の画面でも差し込み先を
   選べるようにするため、⑤ を開いていなくても読み込んでおく。 */
async function ensureTemplateInfo() {
  if (state.slots.length || !state.project || !state.project.has_template) return;
  const r = await api("template/slots");
  state.slots = r.slots;
  state.images = r.images;
}

function renderPhotos() {
  const el = $("#photoGrid");
  if (!el) return;
  const ps = state.project ? state.project.photos : [];
  el.innerHTML = ps.length
    ? ps.map(photoCard).join("")
    : "<p class='empty'>写真がありません。</p>";
  wirePhotoCards(el);
  // 差し込み先の一覧がまだ無ければ読み込んで、選択状態を反映し直す
  if (ps.length && !state.images.length && state.project?.has_template) {
    guard(async () => {
      await ensureTemplateInfo();
      const el2 = $("#photoGrid");
      el2.innerHTML = state.project.photos.map(photoCard).join("");
      wirePhotoCards(el2);
    });
  }
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

$("#btnAutoLayout").addEventListener("click", () => guard(async () => {
  if (!state.project) throw new Error("先に号を作成または選択してください");
  const withSlots = $("#autoSlots").checked;
  if (withSlots && !state.project.has_template) {
    throw new Error("様式が読み込まれていません。⑤ で様式を読み込むか、"
      + "「様式の写真枠まで割り当てる」のチェックを外してください");
  }
  toast("割り付けています…");
  const r = await api("photo/autolayout", { assign_slots: withSlots });
  await refresh();
  state.slots = []; state.images = [];
  await ensureTemplateInfo();
  renderPhotos();
  showAutoReport(r);
}));

function showAutoReport(r) {
  const rows = (list, cls) => list.map((m) => `
    <div class="line">
      <span class="nm">${esc(m.photo_name)}</span>
      <span class="to">${cls === "ok" ? "→ " + esc(m.article_label) : "—"}</span>
      <span class="why">${esc(m.reason)}</span>
    </div>`).join("");

  const total = r.matched.length + r.unmatched.length;
  modal("自動割り付けの結果", `<div class="pad report">
    ${r.message ? `<p class="hint">${esc(r.message)}</p>` : ""}
    <p>写真 ${total} 枚のうち <b>${r.matched.length} 枚</b>を記事に結び付け、
      <b>${r.slots.length} 枚</b>を様式の写真枠に入れました。
      ${r.captions ? `説明文の枠 ${r.captions} か所も押さえました。` : ""}</p>
    ${r.matched.length ? `<h3>結び付いた写真</h3>${rows(r.matched, "ok")}` : ""}
    ${r.unmatched.length ? `<h3>判定できなかった写真</h3>
      <p class="hint">ファイル名を原稿に合わせるか、下の一覧で手で選んでください。</p>
      ${rows(r.unmatched, "ng")}` : ""}
    <p class="hint" style="margin-top:14px">
      結果は写真の一覧に反映されています。違っているものは、
      各写真の「差し込み先」で選び直せます。</p>
  </div>`);
}

// ------------------------------------------------------------------ ⑤ 紙面に組む

const LY = {
  columns: "lyCols", body_pt: "lyBody", heading_pt: "lyHead", line_spacing: "lyLine",
  margin_top_mm: "lyMT", margin_bottom_mm: "lyMB", column_gap_mm: "lyGap",
  body_font: "lyFont", heading_font: "lyHFont", photo_height_ratio: "lyPhoto",
};

function currentMode() {
  return $('input[name="mode"]:checked')?.value || "auto";
}

function applyMode() {
  const auto = currentMode() === "auto";
  $("#autoPane").hidden = !auto;
  $("#pagePane").hidden = !auto;
  $("#slotsPane").hidden = auto;
  $$(".slotsOnly").forEach((el) => (el.hidden = auto));
  if (!auto) loadSlots();
}

$$('input[name="mode"]').forEach((r) =>
  r.addEventListener("change", () => guard(async () => {
    applyMode();
    await api("layout/save", { settings: { compose_mode: currentMode() } });
  })));

async function loadLayout() {
  if (!state.project) return;
  const r = await api("layout/get", {});
  for (const [key, id] of Object.entries(LY)) {
    const el = $("#" + id);
    if (el && r.layout[key] !== undefined) el.value = r.layout[key];
  }
  const mx = r.layout.margin_left_mm;
  if ($("#lyMX") && mx !== undefined) $("#lyMX").value = mx;
  const st = r.settings || {};
  const mode = st.compose_mode || "auto";
  $$('input[name="mode"]').forEach((x) => (x.checked = x.value === mode));
  if (st.target_pages) $("#lyTarget").value = st.target_pages;
  showMetrics(r.metrics);
  applyMode();
}

function showMetrics(m) {
  if (!m) return;
  $("#lyMetrics").textContent =
    `1段 ${m.chars_per_line} 字 × ${m.lines_per_column} 行` +
    `（段の高さ ${m.column_height_mm} mm）／ 1ページ 約 ${m.chars_per_page} 字`;
}

$("#btnSaveLayout").addEventListener("click", () => guard(async () => {
  const layout = {};
  for (const [key, id] of Object.entries(LY)) {
    const v = $("#" + id).value;
    layout[key] = isNaN(Number(v)) || v === "" ? v : Number(v);
  }
  const mx = Number($("#lyMX").value);
  layout.margin_left_mm = mx; layout.margin_right_mm = mx;
  const r = await api("layout/save", { layout, settings: { compose_mode: currentMode() } });
  showMetrics(r.metrics);
  toast("紙面の決まりごとを保存しました");
}));

$("#btnPlan").addEventListener("click", () => guard(async () => {
  const r = await api("layout/plan", { target_pages: Number($("#lyTarget").value) || 0 });
  renderPlan(r, false);
}));

$("#btnFitPages").addEventListener("click", () => guard(async () => {
  const target = Number($("#lyTarget").value) || 0;
  if (target <= 0) throw new Error("目標ページ数を入れてください");
  if (!confirm(
    `目標 ${target} ページに収まるよう、すべての記事をまとめて詰めます。\n\n` +
    "本文が短くなります。元に戻したいときは、③ の各記事で\n" +
    "「取り込んだ原稿に戻す」を押してください。\n\nよろしいですか？"
  )) return;
  toast("詰めています…");
  const r = await api("layout/fit", { target_pages: target });
  await refresh();
  renderPlan(r, true);
}));

function renderPlan(r, applied) {
  const el = $("#planResult");
  if (!r.need_cut) {
    el.innerHTML = `<p class="metrics">${esc(r.message)}</p>`;
    return;
  }
  const rows = (applied ? r.applied || [] : r.plan).map((x) => `
    <div class="r">
      <span class="nm">${esc(x.label)}</span>
      ${applied
        ? `<span class="n">${x.before} 字 → ${x.after} 字</span>
           <span class="cut">${esc(x.method)}</span>`
        : `<span class="n">いま ${x.now} 字</span>
           <span class="cut">${x.cut > 0 ? "−" + x.cut + " 字" : "そのまま"}</span>`}
    </div>`).join("");
  el.innerHTML = `
    <p class="metrics">${esc(r.message)}
      ${applied && r.pages_after ? `　→ 詰めたあと 約 ${r.pages_after} ページ` : ""}</p>
    <div class="planlist">${rows}</div>
    ${applied ? `<p class="hint" style="margin-top:10px">
      <b>要約は機械的な処理です。</b>③ の各記事で内容を必ず確認してください。
      元に戻すときは「取り込んだ原稿に戻す」を押します。</p>` : ""}`;
}

// ------------------------------------------------------------------ ⑤ 割付（差し込み方式）

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

  if (currentMode() === "auto") {
    const c = await api("compose", { filename: $("#expName").value.trim() });
    const base = c.docx.split(/[\\/]/).pop();
    $("#exportResult").innerHTML = `
      <div class="card" style="margin-top:12px">
        <h2>組み上がりました</h2>
        <p>${esc(c.docx)}</p>
        <p class="metrics">本文 ${c.chars} 字 ／ 写真 ${c.photos} 枚 ／
          <b>約 ${c.pages} ページ</b>（${c.lines_used} 行 ÷ 1ページ ${c.lines_per_page} 行）</p>
        ${c.warnings.length ? `<p style="color:var(--warn)">⚠ ${c.warnings.map(esc).join("／")}</p>` : ""}
        <p class="hint">ページ数の目安は Word で開くと確定します。
          1ページ ${$("#lyCols").value} 段・縦書きは固定で、分量に応じて段送りと
          ページ数が調節されています。</p>
        <div class="row"><button id="btnDl">Word をダウンロード</button></div>
      </div>`;
    $("#btnDl").addEventListener("click", () => {
      window.location = "/api/download?file=" + encodeURIComponent(base);
    });
    toast("組み上がりました");
    return;
  }

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
    closeModal();
    toast("設定を保存しました");
  }));
}));

// ------------------------------------------------------------------ 終了

$("#btnQuit").addEventListener("click", () => guard(async () => {
  if (!confirm(
    "議会だより 原稿編集ツールを終了します。よろしいですか？\n\n" +
    "編集中の内容で保存していないものがあれば、先に「保存」を押してください。"
  )) return;
  try {
    await api("quit", {});
  } catch (e) {
    // 終了処理の途中で通信が切れることがあるが、それは正常
  }
  document.body.innerHTML = `
    <div class="farewell">
      <img src="icon.png" alt="">
      <h1>終了しました</h1>
      <p>このタブは閉じてかまいません。</p>
      <p>もう一度使うときは、デスクトップのアイコンから起動してください。</p>
    </div>`;
}));

// ============================================================ かんたん作成

/* 考え方はひとつだけ。「フォルダの中身が、そのまま紙面になる」。
   区分の振り分けも写真の割り付けも、どのフォルダに入れたかで決まるので、
   画面で覚えることが無い。 */

let easyState = null;

$$(".modebar .mode").forEach((b) =>
  b.addEventListener("click", () => showMode(b.dataset.mode)));

function showMode(mode) {
  $$(".modebar .mode").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  $("#steps").hidden = mode === "easy";
  $("#modeHint").textContent = mode === "easy"
    ? "フォルダに入れて、ボタンひとつで作ります。"
    : "手順を1つずつ確かめながら進めます。";
  if (mode === "easy") {
    $$(".pane").forEach((x) => x.classList.toggle("on", x.id === "pane-easy"));
    guard(loadEasy);
  } else {
    showStep(state.project ? "import" : "project");
  }
}

async function loadEasy() {
  // 保存済みの号を選べるようにする
  const ws = await api("workspace");
  const sel = $("#ezOpen");
  $("#ezOpenRow").hidden = !ws.projects.length;
  sel.innerHTML = ws.projects.map((x) =>
    `<option value="${esc(x.name)}">${esc(x.title)}（記事 ${x.articles} 件）</option>`).join("");

  $("#ezProj").textContent = state.project
    ? "いまの号: " + state.project.title
    : (ws.projects.length ? "" : "はじめての方は、右上の「使い方」をご覧ください");
  const on = !!state.project;
  ["ezStep2", "ezStep3", "ezStep4"].forEach((id) => $("#" + id).classList.toggle("off", !on));
  if (!on) {
    $("#ezFolders").innerHTML = "";
    $("#ezInboxPath").textContent = "";
    return;
  }
  await refreshEasy();
}

async function refreshEasy() {
  easyState = await api("easy/state");
  $("#ezPages").value = easyState.max_pages || easyState.default_max_pages || 0;
  $("#ezInboxPath").textContent = easyState.inbox;
  renderFolders();
  renderBuilt();
}

function renderFolders() {
  const el = $("#ezFolders");
  if (!easyState) { el.innerHTML = ""; return; }
  el.innerHTML = easyState.sections.map((f) => {
    const n = f.docs.length, m = f.photos.length;
    const chip = (name, kind) =>
      `<button class="chip ${kind}" data-ren="${esc(f.folder + "/" + name)}"
         title="名前を変える／別の区分へ移す">${esc(name)}</button>`;
    const files = f.docs.map((x) => chip(x, "doc"))
      .concat(f.photos.map((x) => chip(x, "img"))).join("");
    const need = !n && !f.optional;      // 毎号ある区分なのに空
    return `<div class="fold ${n + m ? "" : "zero"} ${need ? "need" : ""}">
      <div class="fname">${esc(f.folder)}</div>
      <div class="fnote">${esc(f.note)}${f.optional ? "（無い号もあります）" : ""}</div>
      <div class="fcount">${n ? `原稿 ${n} 件` : (need ? "原稿がまだです" : "原稿なし")}${
        m ? ` ／ 写真 ${m} 枚` : ""}</div>
      ${files ? `<div class="flist">${files}</div>` : ""}
      <div class="foldbtns">
        <button class="renum" data-write="${esc(f.id)}"
          title="この区分の記事を、画面で直接書きます">直接書く</button>
        ${n > 1 ? `<button class="renum" data-renum="${esc(f.id)}"
          title="いまの並びで 01_ 02_ … を付け直します">番号を振り直す</button>` : ""}
      </div>
    </div>`;
  }).join("");

  $$("[data-ren]", el).forEach((b) =>
    b.addEventListener("click", () => renameDialog(b.dataset.ren)));
  $$("[data-write]", el).forEach((b) =>
    b.addEventListener("click", () => writeDialog({ section: b.dataset.write })));
  $$("[data-renum]", el).forEach((b) =>
    b.addEventListener("click", () => guard(async () => {
      const r = await api("easy/renumber", { section: b.dataset.renum });
      easyState = { ...easyState, ...r };
      renderFolders();
      toast(r.message);
    })));

  $("#ezPhotoRow").hidden = !easyState.photos;
  $("#ezPhotoNote").textContent = easyState.photos
    ? "カメラの名前（IMG_2451.jpg など）のままでも、写真を見ながら選ぶだけで名前がそろいます。"
    : "";
}

/* 記事を画面で直接書く。

   「審議したこと・決まったこと」のように、議員から届くのではなく
   **事務局が自分で書く**記事がある。そのためだけに Word を立ち上げて
   フォルダに置くのは手間なので、ここで書いてそのまま保存する。
   保存の形はテキストファイルなので、「フォルダの中身がそのまま紙面」
   という決まりは崩れない。 */
function writeDialog({ section = "", file = "" } = {}) {
  guard(async () => {
    let name = "", text = "";
    if (file) {
      const r = await api("easy/note_read", { file });
      name = r.name; text = r.text;
    }
    const secs = easyState.sections.filter((s) => s.id);
    const where = file
      ? `<p class="hint">いまの場所　<code>${esc(file)}</code></p>`
      : `<div class="row"><label>入れる区分<select id="wrSec">${secs.map((s) =>
          `<option value="${esc(s.id)}" ${s.id === section ? "selected" : ""}>${
            esc(s.folder)}</option>`).join("")}</select></label></div>`;

    modal(file ? "原稿を書きかえる" : "記事を直接書く", `<div class="pad">
      ${where}
      ${file ? "" : `<div class="row"><label>見出し（ファイル名になります）
        <input id="wrName" placeholder="例: 6月定例会で決まったこと"></label></div>`}
      <p class="hint">1行目が見出しになります。段落は改行で分けてください。</p>
      <textarea id="wrText" rows="16" placeholder="ここに本文を書きます。">${esc(text)}</textarea>
      <div class="row" style="margin-top:12px">
        <button class="primary" id="wrOk">保存する</button>
        <button class="ghost" id="wrNo">やめる</button>
        <span class="hint" id="wrCount"></span>
      </div></div>`);

    if (!file) $("#wrName").value = name;
    const count = () => {
      $("#wrCount").textContent = countOf($("#wrText").value) + " 字";
    };
    $("#wrText").addEventListener("input", count);
    count();
    $("#wrNo").addEventListener("click", closeModal);
    setTimeout(() => ($("#wrName") || $("#wrText")).focus(), 0);

    $("#wrOk").addEventListener("click", () => guard(async () => {
      const body = { text: $("#wrText").value };
      if (file) body.file = file;
      else {
        body.section = $("#wrSec").value;
        body.name = $("#wrName").value.trim();
        // 見出しが空なら、本文の1行目を使う
        if (!body.name) body.name = ($("#wrText").value.split("\n")[0] || "").trim();
      }
      const r = await api("easy/note_write", body);
      closeModal();
      easyState = { ...easyState, ...r };
      renderFolders();
      toast(r.message);
    }));
  });
}

/* 写真を原稿に割り当てる。

   議員から届く写真は IMG_2451.jpg のように、原稿とはまったく違う名前で
   来る。名前で結びつける決まりにしている以上、どこかで人が「これは誰の
   写真か」を教えるしかない。ここでは**写真を見ながら選ぶだけ**にして、
   名前を打ち直す手間をなくす。 */
$("#ezAssign").addEventListener("click", () => guard(openAssign));

async function openAssign() {
  const plan = await api("easy/photo_plan", {});
  if (!plan.photos) {
    modal("写真を原稿に割り当てる",
      `<div class="pad"><p class="empty">原稿フォルダに写真が入っていません。</p></div>`);
    return;
  }
  const body = plan.sections.map((sec) => {
    if (!sec.docs.length) {
      return `<div class="asec"><h3>${esc(sec.folder)}</h3>
        <p class="none">この区分に原稿がありません。
          写真だけでは載せられないので、先に原稿を入れてください。</p></div>`;
    }
    const cards = sec.photos.map((ph) => {
      const opts = sec.docs.map((d) =>
        `<option value="${esc(d)}" ${d === ph.doc ? "selected" : ""}>${esc(d)}</option>`).join("");
      return `<div class="pcard ${ph.decided ? "" : "todo"}">
        <img class="shot" loading="lazy" alt="${esc(ph.name)}"
             src="/api/easy/photo?file=${encodeURIComponent(ph.rel)}">
        <div class="pn">${esc(ph.name)}</div>
        <select data-ph="${esc(ph.rel)}" class="${ph.decided ? "" : "todo"}">
          <option value="" ${ph.doc ? "" : "selected"}>（どの原稿か選ぶ）</option>
          ${opts}
          <option value="__unused__">この号では使わない</option>
        </select></div>`;
    }).join("");
    return `<div class="asec"><h3>${esc(sec.folder)}</h3>
      <div class="agrid">${cards}</div></div>`;
  }).join("");

  modal("写真を原稿に割り当てる", `<div class="pad">
    <p class="hint">写真を見て、<b>どの原稿のものか</b>を選んでください。
      選んだとおりに名前をそろえます（1枚なら
      <code>01_森下けい子.jpg</code>、複数なら
      <code>01_森下けい子1.jpg</code> <code>01_森下けい子2.jpg</code>）。</p>
    <p class="hint">名前がすでに合っているものは、初めから選んであります。
      <b>色が付いているものだけ</b>選べば済みます（${plan.unmatched} 枚）。
      「この号では使わない」を選ぶと、消さずに
      「使わない写真」フォルダへよけます。</p>
    <div class="assign">${body}</div>
    <div class="row" style="margin-top:14px">
      <button class="primary" id="asOk">この割り当てで名前をそろえる</button>
      <button class="ghost" id="asNo">やめる</button>
    </div></div>`);

  $("#asNo").addEventListener("click", closeModal);
  $$("[data-ph]").forEach((sel) =>
    sel.addEventListener("change", () => {
      const on = !!sel.value;
      sel.classList.toggle("todo", !on);
      sel.closest(".pcard").classList.toggle("todo", !on);
    }));

  $("#asOk").addEventListener("click", () => guard(async () => {
    const mapping = {};
    $$("[data-ph]").forEach((sel) => {
      if (sel.value === "__unused__") mapping[sel.dataset.ph] = "使わない写真";
      else if (sel.value) mapping[sel.dataset.ph] = sel.value;
    });
    const r = await api("easy/assign_photos", { mapping });
    closeModal();
    easyState = { ...easyState, ...r };
    renderFolders();
    toast(r.message);
  }));
}

/* 届く原稿は名前がばらばら。載せる順番は先頭の番号で決まり、写真は
   原稿と同じ名前で結びつくので、名前をそろえる作業がどうしても要る。
   エクスプローラーへ行かずに、ここで済ませられるようにする。 */
function renameDialog(rel) {
  const [folder, file] = [rel.slice(0, rel.indexOf("/")), rel.slice(rel.indexOf("/") + 1)];
  const dot = file.lastIndexOf(".");
  const stem = dot > 0 ? file.slice(0, dot) : file;
  const ext = dot > 0 ? file.slice(dot) : "";
  const cur = easyState.sections.find((s) => s.folder === folder);
  const isDoc = !!cur && cur.docs.includes(file);

  modal("名前を変える", `<div class="pad">
    <p class="hint">いまの場所　<code>${esc(rel)}</code></p>
    <div class="row">
      <label>新しい名前<input id="rnName" value="${esc(stem)}"></label>
      <span class="hint" style="align-self:flex-end;padding-bottom:8px">${esc(ext)}</span>
    </div>
    <div class="row">
      <label>入れる区分<select id="rnSec">${easyState.sections.map((s) =>
        `<option value="${esc(s.id)}" ${s.folder === folder ? "selected" : ""}>${
          esc(s.folder)}</option>`).join("")}</select></label>
    </div>
    ${isDoc ? `<label class="check" style="margin-top:8px">
      <input type="checkbox" id="rnPhotos" checked>
      この原稿に付いている写真の名前も、あわせてそろえる</label>
      <p class="hint">写真は原稿と同じ名前で結びついているので、
        原稿だけ名前を変えると外れてしまいます。</p>` : ""}
    <p class="hint" style="margin-top:10px">種類（${esc(ext)}）は変わりません。
      番号を付けたいときは <code>01_</code> のように先頭に足してください。</p>
    <div class="row" style="margin-top:14px">
      <button class="primary" id="rnOk">名前を変える</button>
      ${/\.(txt|md)$/i.test(file)
        ? `<button id="rnEdit">中身を書きかえる</button>` : ""}
      <button class="ghost" id="rnNo">やめる</button>
    </div></div>`);

  $("#rnEdit")?.addEventListener("click", () => {
    closeModal();
    writeDialog({ file: rel });
  });
  $("#rnNo").addEventListener("click", closeModal);
  $("#rnName").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("#rnOk").click();
  });
  setTimeout(() => $("#rnName").select(), 0);
  $("#rnOk").addEventListener("click", () => guard(async () => {
    const r = await api("easy/rename", {
      file: rel,
      name: $("#rnName").value.trim(),
      section: $("#rnSec").value,
      with_photos: $("#rnPhotos") ? $("#rnPhotos").checked : false,
    });
    closeModal();
    easyState = { ...easyState, ...r };
    renderFolders();
    toast(r.renamed.length
      ? r.renamed.map((x) => x.to.split("/").pop()).join("、") + " にしました"
      : r.message);
  }));
}

function renderBuilt() {
  const b = easyState?.built || {};
  const has = !!b.docx;
  ["ezPreview", "ezOpenWord", "ezOpenOut"].forEach((id) => ($("#" + id).disabled = !has));
  $("#ezOutNote").textContent = has
    ? `${b.docx}　（保存先: ${b.output_dir}）`
    : "まだ作っていません。";
}

$("#ezCreate").addEventListener("click", () => guard(async () => {
  const title = $("#ezTitle").value.trim();
  if (!title) throw new Error("号の名前を入れてください（例: 第204号）");
  const r = await api("project/create", {
    title, issue_no: title.replace(/[^0-9]/g, ""), issue_date: $("#ezDate").value.trim(),
  });
  await setProject(r.project);
  await api("easy/max_pages", { max_pages: Number($("#ezPages").value) || 0 });
  const f = await api("easy/folders", {});
  await loadEasy();
  toast(`「${r.project.title}」を作りました。原稿フォルダを開いて、原稿と写真を入れてください。`);
  modal("原稿フォルダを作りました", `<div class="pad">
    <p>この場所に、区分ごとのフォルダを作りました。</p>
    <p class="hint" style="word-break:break-all"><code>${esc(f.inbox)}</code></p>
    <div class="list">${f.folders.map((x) =>
      `<div class="item"><div class="main"><div class="name">${esc(x.folder)}</div>
        <div class="meta">${esc(x.note)}</div></div></div>`).join("")}</div>
    <p class="hint" style="margin-top:12px">載せたい区分のフォルダへ、原稿と写真を入れてください。
      入れ終わったら「入れ終わったので数え直す」を押します。</p>
    <div class="row" style="margin-top:12px">
      <button class="primary" id="mdOpenInbox">原稿フォルダを開く</button>
    </div></div>`);
  $("#mdOpenInbox")?.addEventListener("click", () => {
    closeModal();
    guard(() => openThing("inbox"));
  });
}));

$("#ezOpenBtn").addEventListener("click", () => guard(async () => {
  const name = $("#ezOpen").value;
  if (!name) return;
  const r = await api("project/open", { name });
  await setProject(r.project);
  await api("easy/folders", {});
  await loadEasy();
  toast(`「${r.project.title}」を開きました`);
}));

$("#ezSavePages").addEventListener("click", () => guard(async () => {
  const n = Number($("#ezPages").value) || 0;
  const r = await api("easy/max_pages", { max_pages: n });
  toast(r.max_pages
    ? `最大 ${r.max_pages} ページに収めます`
    : "ページ数は成り行きにしました（原稿の分量どおり）");
  if (easyState) easyState.max_pages = r.max_pages;
}));

$("#ezOpenInbox").addEventListener("click", () => guard(() => openThing("inbox")));
$("#ezOpenOut").addEventListener("click", () => guard(() => openThing("output")));
$("#ezOpenWord").addEventListener("click", () =>
  guard(() => openThing(easyState?.built?.docx || "")));

async function openThing(what) {
  if (!state.project) throw new Error("先に号をはじめてください");
  const r = await api("open", { what });
  toast(r.message);
}

$("#ezRescan").addEventListener("click", () => guard(async () => {
  await refreshEasy();
  toast(`原稿 ${easyState.docs} 件 ／ 写真 ${easyState.photos} 枚 が入っています`);
}));

$("#ezBuild").addEventListener("click", () => guard(buildEasy));

async function buildEasy() {
  if (!state.project) throw new Error("先に号をはじめてください");
  await refreshEasy();
  if (!easyState.docs) {
    throw new Error("原稿フォルダに原稿が入っていません。" +
      "「原稿フォルダを開く」から、区分のフォルダへ原稿を入れてください。");
  }
  // 画面で本文を直していた場合だけ、消えることを先に伝える
  if (easyState.hand_edited.length) {
    const ok = await confirmModal("画面で直した本文が元に戻ります",
      `<p>「くわしく編集」で本文を直した記事が <b>${easyState.hand_edited.length} 件</b>あります。</p>
       <ul class="hint" style="margin:8px 0 12px 18px">${
         easyState.hand_edited.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
       <p class="hint"><b>作り直すと:</b> フォルダに入っている原稿から組み直すので、
         画面で直した本文は元に戻ります。同じフォルダからは必ず同じ紙面ができる、
         という作りにしているためです。</p>
       <p class="hint"><b>直した内容を残したいときは:</b> このまま「やめる」を押し、
         「くわしく編集」の⑤から組んでください。
         または、直した内容をフォルダの原稿ファイル自体に反映してから作り直してください。</p>`,
      "元に戻して作り直す");
    if (!ok) return;
  }

  const btn = $("#ezBuild");
  btn.disabled = true;
  btn.textContent = "作って、ページ数を数えています…";
  $("#ezResult").innerHTML = "";
  try {
    const r = await api("easy/build", { max_pages: Number($("#ezPages").value) || 0 });
    await refresh();
    easyState = { ...easyState, built: r.built };
    renderBuilt();
    renderFolders();
    showBuildResult(r);
    toast(`できあがりました（${r.compose.pages} ページ）`);
  } finally {
    btn.disabled = false;
    btn.textContent = "議会だよりを作る";
  }
}

function showBuildResult(r) {
  const pages = r.pages ?? r.compose.pages;
  const max = r.max_pages;
  const over = max > 0 && pages > max;
  const bars = Array.from({ length: Math.min(pages, 40) },
    (_, i) => `<i class="${max && i >= max ? "over" : ""}"></i>`).join("");
  // 数えたのか、目安なのかをはっきり書く。ここを曖昧にすると、
  // 「収まりました」と言われて実際にあふれたときに信用を失う
  const how = r.counted
    ? "実際に数えたページ数です。"
    : "このパソコンでは PDF を作れないため、<b>目安</b>です"
      + "（1ページほど前後することがあります）。Word で開いてご確認ください。";

  const secs = r.outline.sections.filter((g) => g.count).map((g) =>
    `<div><b>${esc(g.name)}</b> … ${g.count} 本 ／ ${g.chars} 字</div>`).join("");

  const rep = r.report;
  const line = (label, arr) => arr.length
    ? `<div><b>${label}</b> ${arr.length} 件<span class="flist"> ${
        arr.slice(0, 8).map(esc).join("、")}${arr.length > 8 ? " ほか" : ""}</span></div>`
    : "";

  const fit = r.fit && r.fit.applied && r.fit.applied.length
    ? `<div class="ezbox"><h3>ページ数に合わせて詰めたところ</h3>
        <div class="ezrows">${r.fit.applied.map((a) =>
          `<div><b>${esc(a.label)}</b> ${a.before} 字 → ${a.after} 字</div>`).join("")}</div>
        <p class="hint" style="margin-top:8px">原稿にあった文を選んで残しています
          （文章を作り変えてはいません）。気になるところは「くわしく編集」の③で直せます。</p>
        ${r.natural_pages && r.natural_pages > pages
          ? `<p class="hint"><b>詰めたくないときは、最大ページ数を
              ${r.natural_pages} ページにしてください。</b>
              1字も詰めずに組むと ${r.natural_pages} ページになります。</p>` : ""}
      </div>`
    : "";

  const missing = (r.missing || []).length
    ? `<div class="ezbox"><h3>原稿が入っていない区分があります</h3>
        <div class="ezrows">${r.missing.map((m) =>
          `<div><b>${esc(m.name)}</b>　<span class="flist">${esc(m.folder)} フォルダ</span></div>`
          ).join("")}</div>
        <p class="hint" style="margin-top:8px">入れ忘れでなければ、このまま進めて構いません。
          入れたあと「議会だよりを作る」をもう一度押せば入ります。</p></div>`
    : "";

  const warn = (r.compose.warnings || []).length
    ? `<div class="ezbox"><h3>気を付けるところ</h3><div class="ezrows">${
        r.compose.warnings.map((w) => `<div>${esc(w)}</div>`).join("")}</div></div>`
    : "";

  const skipped = rep.skipped.length
    ? `<div class="ezbox"><h3>読めなかったファイル</h3><div class="ezrows">${
        rep.skipped.map((x) => `<div><b>${esc(x.file)}</b> … ${esc(x.why)}</div>`).join("")}
      </div></div>`
    : "";

  $("#ezResult").innerHTML = `
    <div class="ezbox">
      <div class="ezbig ${over ? "over" : ""}">できあがり ${pages} ページ${
        max ? `（最大 ${max} ページ${over ? " … はみ出しています" : "に収まりました"}）` : ""}</div>
      <div class="pagebar">${bars}</div>
      <div class="ezrows">記事 ${r.counts.articles} 本 ／ 写真 ${r.counts.photos} 枚 ／
        本文 ${r.counts.chars} 字</div>
      <p class="hint">${how}</p>
      ${over ? `<p class="hint">最大ページ数を増やすか、原稿を減らしてもう一度お試しください。</p>` : ""}
      ${r.print_hint && r.print_hint.message
        ? `<p class="hint ${r.print_hint.ok ? "" : "warnhint"}">
            ${esc(r.print_hint.message)}</p>` : ""}
    </div>
    <div class="ezbox"><h3>紙面の並び</h3><div class="ezrows">${secs}</div></div>
    <div class="ezbox"><h3>フォルダから取り込んだもの</h3><div class="ezrows">
      ${line("新しく入った", rep.added)}
      ${line("差し替えられていたので読み直した", rep.updated)}
      ${line("そのまま", rep.kept)}
      ${line("フォルダから消えたので外した", rep.removed)}
      ${line("写真を入れた", rep.photos_added)}
    </div></div>
    ${missing}${fit}${warn}${skipped}`;
}

/* できあがりを見る。

   PDF をそのまま埋め込むやり方（iframe）だと、パソコンの設定によっては
   何も出ないことがある。**1ページずつ画にして並べる**ほうが確かなので、
   そちらを本筋にして、PDF を開く道も残しておく。 */

$("#ezPreview").addEventListener("click", () => guard(async () => {
  const box = $("#ezPreviewBox");
  box.innerHTML = `<div class="ezbox">できあがりを作っています… 少しお待ちください</div>`;
  const r = await api("easy/preview", {});
  if (!r.pdf) {
    box.innerHTML = `<div class="ezbox"><h3>できあがりを見る</h3>
      <div class="ezrows">${esc(r.message).replace(/\n/g, "<br>")}</div></div>`;
    return;
  }
  const openPdf = `<button class="ghost" data-open="pdf">PDF を開く</button>`;
  if (!r.can_show || !r.pages) {
    box.innerHTML = `<div class="ezbox"><h3>できあがりを見る</h3>
      <div class="ezrows">${esc(r.message || "画面に出せませんでした。")}</div>
      <div class="row" style="margin-top:10px">${openPdf}</div></div>`;
    wirePreviewButtons(box);
    return;
  }
  const stamp = Date.now();          // 前に見た画が残らないようにする
  const sheets = Array.from({ length: r.pages }, (_, i) => `
    <figure class="pvpage">
      <img loading="lazy" alt="${i + 1} ページ目"
           src="/api/easy/preview_page?page=${i + 1}&w=900&t=${stamp}">
      <figcaption>${i + 1} ページ</figcaption>
    </figure>`).join("");
  box.innerHTML = `
    <div class="ezbox">
      <div class="row" style="justify-content:space-between;align-items:center">
        <div class="ezbig">できあがり ${r.pages} ページ</div>
        <div class="row">${openPdf}
          <button class="ghost" data-open="output">フォルダを開く</button></div>
      </div>
      <p class="hint">刷り上がりと同じ形です。写真は枠だけ空けてあります。
        直したいところがあれば、フォルダの原稿を直して
        「議会だよりを作る」をもう一度押してください。</p>
    </div>
    <div class="pvpages">${sheets}</div>`;
  wirePreviewButtons(box);
}));

function wirePreviewButtons(box) {
  box.querySelectorAll("[data-open]").forEach((b) =>
    b.addEventListener("click", () => guard(async () => {
      const r = await api("open", { what: b.dataset.open });
      toast(r.message || "開きました");
    })));
}

// ------------------------------------------------------------------ 使い方

/* 使い方は道具の中で完結させる。役場の端末で README を探して開く、
   という運用は現実的でないため。文章は gikai/help.py の1か所にあり、
   ここはそれを並べるだけ。 */

let helpDoc = null;

$("#btnHelp").addEventListener("click", () => guard(() => openHelp()));
$$("[data-help]").forEach((b) =>
  b.addEventListener("click", () => guard(() => openHelp(b.dataset.help))));

async function openHelp(focusId = "") {
  if (!helpDoc) helpDoc = await api("help");
  const secs = helpDoc.sections;
  modal("使い方", `<div class="pad">
    <div class="helpnav">${secs.map((x) =>
      `<button data-goto="${esc(x.id)}">${esc(x.title)}</button>`).join("")}</div>
    <div class="help" id="helpBody">${secs.map((x) =>
      `<h3 id="h-${esc(x.id)}">${esc(x.title)}</h3>${x.blocks.map(helpBlock).join("")}`
      ).join("")}</div>
    <div class="helpfoot">
      <button id="helpPrint">印刷する</button>
      <span class="hint">紙に出して、パソコンの横に置いておけます。</span>
    </div></div>`);

  $("#helpPrint").addEventListener("click", () => window.print());
  $$("[data-goto]").forEach((b) =>
    b.addEventListener("click", () => {
      $$("[data-goto]").forEach((x) => x.classList.toggle("on", x === b));
      $("#h-" + b.dataset.goto)?.scrollIntoView({ block: "start" });
    }));
  if (focusId) {
    const btn = $(`[data-goto="${focusId}"]`);
    if (btn) { btn.classList.add("on"); btn.click(); }
  }
}

/* 太字とコードだけ、書いたとおりに見せる。
   使い方の文章は自分たちで書いたものなので、ここで組み立ててよい。 */
function helpText(s) {
  return esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

function helpBlock(b) {
  if (b.p) return `<p>${helpText(b.p)}</p>`;
  if (b.list) return `<ul>${b.list.map((x) => `<li>${helpText(x)}</li>`).join("")}</ul>`;
  if (b.steps) return `<ol>${b.steps.map((x) => `<li>${helpText(x)}</li>`).join("")}</ol>`;
  if (b.note) return `<div class="hnote">${helpText(b.note)}</div>`;
  if (b.warn) return `<div class="hwarn">${helpText(b.warn)}</div>`;
  if (b.code) return `<pre>${esc(b.code)}</pre>`;
  if (b.table) {
    return `<table><thead><tr>${b.table.head.map((h) =>
      `<th>${helpText(h)}</th>`).join("")}</tr></thead><tbody>${
      b.table.rows.map((r) => `<tr>${r.map((c) =>
        `<td>${helpText(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }
  return "";
}

// ------------------------------------------------------------------ 起動

guard(async () => {
  await loadWorkspace();
  await loadEasy();
});
