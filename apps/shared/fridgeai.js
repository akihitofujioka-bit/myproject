/*
 * 冷蔵庫の在庫から、端末内 AI に渡す献立相談を組み立てる。
 * 在庫データは並べ替えと整形だけを行い、変更しない。
 */
(function (global) {
  "use strict";

  function dateValue(value) {
    var match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return null;
    var time = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    var date = new Date(time);
    if (date.getUTCFullYear() !== Number(match[1]) || date.getUTCMonth() !== Number(match[2]) - 1 || date.getUTCDate() !== Number(match[3])) return null;
    return time;
  }

  function sortInventory(items) {
    return (Array.isArray(items) ? items : []).filter(function (item) {
      return item && String(item.name || "").trim();
    }).slice().sort(function (a, b) {
      var aDate = dateValue(a.expiresOn);
      var bDate = dateValue(b.expiresOn);
      if (aDate === null && bDate !== null) return 1;
      if (aDate !== null && bDate === null) return -1;
      if (aDate !== bDate) return aDate - bDate;
      return String(a.name).localeCompare(String(b.name), "ja");
    });
  }

  function daysFrom(today, target) {
    var start = dateValue(today);
    var end = dateValue(target);
    return start === null || end === null ? null : Math.round((end - start) / 86400000);
  }

  function deadlineText(item, today) {
    var days = daysFrom(today, item.expiresOn);
    if (days === null) return "期限なし";
    if (days < 0) return Math.abs(days) + "日超過（利用できるか要確認）";
    if (days === 0) return "今日まで";
    return "あと" + days + "日";
  }

  function buildRequest(items, today) {
    var sorted = sortInventory(items).slice(0, 30);
    var lines = sorted.map(function (item) {
      var quantity = (item.qty || item.qty === 0) ? "、" + item.qty + (item.unit || "") : "";
      var note = item.note ? "、メモ: " + String(item.note).replace(/[\r\n]+/g, " ") : "";
      return "- " + String(item.name).trim() + quantity + "、" + deadlineText(item, today) + note;
    });
    return {
      instructions: "あなたは家庭の献立を考える補助役です。在庫だけを主な食材として使い、期限が近い食材を優先してください。調味料や水、油は一般家庭にあるものとして構いません。回答は指定した JSON だけにしてください。",
      prompt: "今日の日付は " + today + " です。次の在庫から、異なる献立を3つ提案してください。食べられるか不明な期限超過品は、確認を促してください。\n\n" +
        (lines.length ? lines.join("\n") : "（在庫なし）") +
        "\n\n次の形の JSON で答えてください。name は献立名、ingredients は実際に使う在庫の食材名、description は短い作り方です。\n" +
        '{"menus":[{"name":"献立名","ingredients":["食材名"],"description":"短い作り方"}]}',
      inventory: sorted
    };
  }

  function firstObject(text) {
    var source = String(text || "");
    var start = source.indexOf("{");
    if (start < 0) return "";
    var depth = 0;
    var quoted = false;
    var escaped = false;
    for (var i = start; i < source.length; i++) {
      var ch = source.charAt(i);
      if (quoted) {
        if (escaped) escaped = false;
        else if (ch === "\\") escaped = true;
        else if (ch === '"') quoted = false;
        continue;
      }
      if (ch === '"') quoted = true;
      else if (ch === "{") depth++;
      else if (ch === "}" && --depth === 0) return source.slice(start, i + 1);
    }
    return "";
  }

  function cleanText(value, max) {
    if (typeof value !== "string") return "";
    return value.trim().slice(0, max);
  }

  function parseResponse(text, inventory) {
    var json = firstObject(text);
    if (!json) return null;
    var data;
    try { data = JSON.parse(json); } catch (e) { return null; }
    if (!data || !Array.isArray(data.menus) || data.menus.length !== 3) return null;

    var allowed = {};
    sortInventory(inventory).forEach(function (item) { allowed[String(item.name).trim()] = true; });
    var menus = [];
    for (var i = 0; i < data.menus.length; i++) {
      var raw = data.menus[i];
      if (!raw || typeof raw !== "object" || !Array.isArray(raw.ingredients)) return null;
      var name = cleanText(raw.name, 80);
      var description = cleanText(raw.description, 300);
      var ingredients = [];
      raw.ingredients.forEach(function (value) {
        var ingredient = cleanText(value, 80);
        if (ingredient && allowed[ingredient] && ingredients.indexOf(ingredient) < 0) ingredients.push(ingredient);
      });
      if (!name || !description || !ingredients.length) return null;
      menus.push({ name: name, ingredients: ingredients, description: description });
    }
    return menus;
  }

  global.FridgeAI = {
    sortInventory: sortInventory,
    buildRequest: buildRequest,
    parseResponse: parseResponse
  };
})(typeof window !== "undefined" ? window : this);
