/*
 * 別のアプリへ品目を送るための受け渡し。
 *
 * 家計簿でレシートから読み取った「買ったもの」を、冷蔵庫や備蓄の在庫として
 * 登録するために使う。アプリはどれも同じ場所（localStorage）に、それぞれの
 * 鍵で保存しているため、鍵と形を合わせれば足せる。
 *
 * 壊さないための約束:
 *  - 送り先のデータが読めないときは、何も書かずに失敗を返す（上書きしない）
 *  - 足すだけで、既にある項目には触れない
 *  - 送り先のアプリが起動していれば、次に開いたときに反映される
 */
(function (global) {
  "use strict";

  // 送り先ごとの、保存の鍵と項目の作り方
  var TARGETS = {
    fridge: {
      key: "fridge.v1",
      label: "冷蔵庫",
      make: function (item) {
        return {
          name: item.name,
          qty: 1,
          unit: "個",
          place: "冷蔵",
          expiresOn: "",          // 期限はレシートに載らないため空。冷蔵庫アプリで入れる
          note: item.note || ""
        };
      }
    },
    // 日用品は備蓄アプリの台帳に入れる。残りが少なくなったら知らせる仕組みが
    // そのまま使えるため。職場向けの備蓄と混ざらないよう、保管場所で分けている。
    household: {
      key: "stock.v1",
      label: "日用品",
      make: function (item) {
        return {
          name: item.name,
          qty: 1,
          unit: "個",
          minQty: null,
          place: "日用品",
          expiresOn: "",
          note: item.note || ""
        };
      }
    },
    // 常備薬も備蓄アプリの台帳に入れる。使用期限の管理がそのまま使えるため。
    // 期限はレシートに載らないので空で入る（箱を見て入れてもらう）。
    medicine: {
      key: "stock.v1",
      label: "医薬品",
      make: function (item) {
        return {
          name: item.name,
          qty: 1,
          unit: "個",
          minQty: null,
          place: "医薬品",
          expiresOn: "",
          note: item.note || ""
        };
      }
    },
    stock: {
      key: "stock.v1",
      label: "備蓄",
      make: function (item) {
        return {
          name: item.name,
          qty: 1,
          unit: "個",
          minQty: null,
          place: "",
          expiresOn: "",
          note: item.note || ""
        };
      }
    }
  };

  function uid() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  }

  function labelOf(target) {
    return TARGETS[target] ? TARGETS[target].label : target;
  }

  /**
   * 送り先に品目を足す。
   * @param target "fridge" | "stock"
   * @param items  [{ name, note }]
   * @returns { ok: true, added: n } / { ok: false, reason: "..." }
   */
  function add(target, items) {
    var spec = TARGETS[target];
    if (!spec) return { ok: false, reason: "送り先が分かりません" };
    var list = (items || []).filter(function (it) { return it && String(it.name || "").trim(); });
    if (!list.length) return { ok: false, reason: "送るものがありません" };

    var data;
    try {
      var raw = global.localStorage.getItem(spec.key);
      data = raw ? JSON.parse(raw) : { v: 1, items: [], log: [], codes: {} };
    } catch (e) {
      // 読めないものを上書きすると、送り先の台帳を壊すことになる
      return { ok: false, reason: spec.label + "のデータを読めませんでした。上書きを避けるため中止しました" };
    }
    if (!data || typeof data !== "object" || !Array.isArray(data.items)) {
      return { ok: false, reason: spec.label + "のデータの形が想定と違います。上書きを避けるため中止しました" };
    }

    var now = new Date().toISOString();
    list.forEach(function (it) {
      var v = spec.make({ name: String(it.name).trim(), note: it.note });
      v.id = uid();
      v.createdAt = now;
      data.items.push(v);
    });

    try {
      global.localStorage.setItem(spec.key, JSON.stringify(data));
    } catch (e) {
      return { ok: false, reason: "保存できませんでした（端末の空き容量を確認してください）" };
    }
    return { ok: true, added: list.length };
  }

  global.Inbox = { add: add, labelOf: labelOf, TARGETS: TARGETS };
})(typeof window !== "undefined" ? window : this);
