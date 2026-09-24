/*
 * 撮り方（カメラの種類）の設定。
 *
 * 2種類あり、どちらも一長一短のため利用者が選べるようにしている（2026-09-24）。
 *
 *   silent   … 無音カメラ。シャッター音が鳴らない。会議中や窓口で使いやすい。
 *              ただし書類の四隅を自動で切り出さないため、まっすぐ大きく写す必要がある
 *   document … iOS 標準の書類カメラ。四隅を自動で切り出し、斜めからでも歪みを直す。
 *              そのぶん文字を読み取りやすいが、撮影時にシャッター音が鳴る
 *
 * 選んだ内容はこの端末の中（localStorage）だけに残り、どのアプリでも同じ設定が使われる。
 */
(function (global) {
  "use strict";

  var KEY = "camera.v1";
  var MODES = {
    silent: { label: "無音で撮る", hint: "音は鳴らない／自動の切り出しなし" },
    document: { label: "自動で切り出す", hint: "読み取りやすい／シャッター音が鳴る" }
  };
  var DEFAULT = "silent";

  function get() {
    try {
      var v = global.localStorage.getItem(KEY);
      return MODES[v] ? v : DEFAULT;
    } catch (e) {
      return DEFAULT;
    }
  }

  function set(mode) {
    var value = MODES[mode] ? mode : DEFAULT;
    try { global.localStorage.setItem(KEY, value); } catch (e) { /* 保存できなくても動く */ }
    return value;
  }

  /**
   * 撮り方を選ぶボタンを作って container に入れる。
   * どのアプリでも同じ見た目・同じ設定になるよう、ここでまとめて作っている。
   */
  function mount(container, onChange) {
    if (!container) return;
    container.innerHTML = "";
    container.classList.add("chips");

    var label = document.createElement("span");
    label.className = "footnote";
    label.style.cssText = "align-self:center;margin:0 4px 0 0";
    label.textContent = "撮り方";
    container.appendChild(label);

    var buttons = {};
    Object.keys(MODES).forEach(function (mode) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip";
      btn.setAttribute("data-camera", mode);
      btn.textContent = MODES[mode].label;
      btn.title = MODES[mode].hint;
      btn.addEventListener("click", function () {
        set(mode);
        paint();
        if (typeof onChange === "function") onChange(mode);
      });
      container.appendChild(btn);
      buttons[mode] = btn;
    });

    var hint = document.createElement("p");
    hint.className = "footnote";
    hint.style.cssText = "flex-basis:100%;margin:4px 0 0";
    container.appendChild(hint);

    function paint() {
      var current = get();
      Object.keys(buttons).forEach(function (mode) {
        buttons[mode].setAttribute("aria-pressed", mode === current ? "true" : "false");
      });
      hint.textContent = MODES[current].hint;
    }
    paint();
  }

  global.CameraPref = { get: get, set: set, mount: mount, modes: MODES };
})(typeof window !== "undefined" ? window : this);
