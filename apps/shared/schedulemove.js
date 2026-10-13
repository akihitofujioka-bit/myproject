/*
 * 書類トラッカーの会議・予定を、予定アプリへ1回だけ引っ越す。
 * 保存は「控え → 予定 → 書類」の順に行い、途中で失敗した場合は
 * 書類を元のまま残して、次に開いたときにやり直せるようにする。
 */
(function (global) {
  "use strict";

  var DOCS_KEY = "docs-tracker.v1";
  var BACKUP_KEY = "docs-tracker.v1.backup-2026-10";
  var SCHEDULE_KEY = "schedule.v1";
  var UNIFY_KEY = "migration.schedule-unify-2026-10";
  var UNIFY_BACKUP_KEY = "schedule.v1.backup-unify-2026-10";

  function result(moved, skipped, error) {
    return { moved: moved, skipped: skipped, error: error || "" };
  }

  function message(error) {
    if (error && error.message) return String(error.message);
    return String(error || "保存に失敗しました");
  }

  function removeSchedule(storage) {
    if (!storage || typeof storage.removeItem !== "function") {
      throw new Error("schedule.v1 を元に戻せません");
    }
    storage.removeItem(SCHEDULE_KEY);
  }

  function failAndRollback(storage, error) {
    var text = message(error);
    try {
      removeSchedule(storage);
    } catch (rollbackError) {
      text += "（元に戻す処理にも失敗しました: " + message(rollbackError) + "）";
    }
    return result(0, false, text);
  }

  function run(storage) {
    if (!storage || typeof storage.getItem !== "function" || typeof storage.setItem !== "function") {
      return result(0, false, "保存場所を利用できません");
    }

    try {
      if (storage.getItem(SCHEDULE_KEY) !== null) return result(0, true, "");
    } catch (error) {
      return result(0, false, message(error));
    }

    var original;
    try {
      original = storage.getItem(DOCS_KEY);
    } catch (error) {
      return result(0, false, message(error));
    }

    var docs = null;
    if (original !== null) {
      try {
        docs = JSON.parse(original);
        if (!docs || typeof docs !== "object" || !Array.isArray(docs.items)) docs = null;
      } catch (error) {
        docs = null;
      }
    }

    // 元データが無い、または壊れている場合は書類側に触れず、空の予定だけを作る。
    if (!docs) {
      try {
        storage.setItem(SCHEDULE_KEY, JSON.stringify({ version: 1, items: [] }));
        return result(0, false, "");
      } catch (error) {
        return failAndRollback(storage, error);
      }
    }

    // 何度もカレンダーから取り込んで重なった予定を見分けるための鍵。
    // 種別・件名・日付・開始時刻・場所がすべて同じなら、同じ予定とみなす
    function sameKey(item) {
      var time = item.startTime || item.time || "";
      if (!time) {
        var m = String(item.note || "").match(/(?:^|\n)\s*(\d{1,2}:\d{2})/);
        time = m ? m[1] : "";
      }
      return [item.kind, item.title, item.dueOn, time, item.dest || ""].join("|");
    }
    var seen = {};

    var scheduleItems = [];
    var docsItems = [];
    docs.items.forEach(function (item) {
      if (item && (item.kind === "会議" || item.kind === "予定")) {
        // 重なった予定は最初の 1 件だけ移す（残りは控えにだけ残る）
        if (seen[sameKey(item)]) return;
        seen[sameKey(item)] = true;
        scheduleItems.push(item);
      } else {
        docsItems.push(item);
      }
    });

    // カレンダーに書き込んだ予定との対応表（calIds）も写す。写さないと、予定アプリで
    // 登録し直したときに、同じ予定がカレンダーに二重にできてしまう
    var calIds = docs.calIds && typeof docs.calIds === "object" ? docs.calIds : {};
    var schedule = { version: 1, items: scheduleItems, calIds: calIds };
    var remaining = {};
    Object.keys(docs).forEach(function (key) { remaining[key] = docs[key]; });
    remaining.items = docsItems;

    // 控えは最初の1回だけ作り、既にある控えを上書きしない。
    try {
      if (storage.getItem(BACKUP_KEY) === null) storage.setItem(BACKUP_KEY, original);
    } catch (error) {
      return result(0, false, message(error));
    }

    try {
      storage.setItem(SCHEDULE_KEY, JSON.stringify(schedule));
    } catch (error) {
      return failAndRollback(storage, error);
    }

    try {
      storage.setItem(DOCS_KEY, JSON.stringify(remaining));
    } catch (error) {
      return failAndRollback(storage, error);
    }

    return result(scheduleItems.length, false, "");
  }

  function unifyResult(merged, skipped, error) {
    return { merged: merged, skipped: skipped, error: error || "" };
  }

  function itemTime(item) {
    var direct = item.startTime || item.time || "";
    if (direct) return direct;
    var match = String(item.note || "").match(/^\s*(\d{1,2}:\d{2})/);
    return match ? match[1] : "";
  }

  function itemEndTime(item) {
    if (item.endTime) return item.endTime;
    var match = String(item.note || "").match(/^\s*\d{1,2}:\d{2}[^\d]+(\d{1,2}:\d{2})/);
    return match ? match[1] : "";
  }

  function informationScore(item) {
    var note = String(item.note || "");
    return (item.dest ? 1 : 0) +
      (itemTime(item) ? 1 : 0) +
      (itemEndTime(item) ? 1 : 0) +
      (note ? 1 : 0) +
      (note.indexOf("懇親会") !== -1 ? 1 : 0) +
      (item.calEventId ? 1 : 0);
  }

  function sameSchedule(a, b, knownTime) {
    if (a.title !== b.title || a.dueOn !== b.dueOn) return false;
    var aTime = knownTime || itemTime(a);
    var bTime = itemTime(b);
    return !aTime || !bTime || aTime === bTime;
  }

  function addMissingInformation(keep, remove) {
    if (!keep.dest && remove.dest) keep.dest = remove.dest;
    if (!keep.calEventId && remove.calEventId) keep.calEventId = remove.calEventId;
    var keepNote = String(keep.note || "");
    var removeNote = String(remove.note || "");
    if (removeNote && keepNote.indexOf(removeNote) === -1) {
      keep.note = keepNote ? keepNote + "\n" + removeNote : removeNote;
    }
  }

  function unifiedItems(items) {
    var output = [];
    var groupTimes = [];
    var merged = 0;
    items.forEach(function (original) {
      var item = {};
      Object.keys(original || {}).forEach(function (key) { item[key] = original[key]; });
      item.kind = "予定";
      var found = -1;
      for (var i = 0; i < output.length; i++) {
        if (sameSchedule(output[i], item, groupTimes[i])) {
          found = i;
          break;
        }
      }
      if (found === -1) {
        output.push(item);
        groupTimes.push(itemTime(item));
        return;
      }
      if (!groupTimes[found]) groupTimes[found] = itemTime(item);
      var first = output[found];
      if (informationScore(item) > informationScore(first)) {
        addMissingInformation(item, first);
        output[found] = item;
      } else {
        addMissingInformation(first, item);
      }
      merged++;
    });
    return { items: output, merged: merged };
  }

  function unify(storage) {
    if (!storage || typeof storage.getItem !== "function" || typeof storage.setItem !== "function") {
      return unifyResult(0, false, "保存場所を利用できません");
    }
    try {
      if (storage.getItem(UNIFY_KEY) !== null) return unifyResult(0, true, "");
    } catch (error) {
      return unifyResult(0, false, message(error));
    }

    var original;
    try {
      original = storage.getItem(SCHEDULE_KEY);
    } catch (error) {
      return unifyResult(0, false, message(error));
    }
    var schedule = null;
    if (original !== null) {
      try {
        schedule = JSON.parse(original);
        if (!schedule || typeof schedule !== "object" || !Array.isArray(schedule.items)) schedule = null;
      } catch (error) {
        schedule = null;
      }
    }
    if (!schedule) {
      try {
        storage.setItem(UNIFY_KEY, "1");
        return unifyResult(0, false, "");
      } catch (error) {
        return unifyResult(0, false, message(error));
      }
    }

    var combined = unifiedItems(schedule.items);
    var changed = {};
    Object.keys(schedule).forEach(function (key) { changed[key] = schedule[key]; });
    changed.items = combined.items;
    try {
      if (storage.getItem(UNIFY_BACKUP_KEY) === null) storage.setItem(UNIFY_BACKUP_KEY, original);
      storage.setItem(SCHEDULE_KEY, JSON.stringify(changed));
      storage.setItem(UNIFY_KEY, "1");
      return unifyResult(combined.merged, false, "");
    } catch (error) {
      var text = message(error);
      try {
        storage.setItem(SCHEDULE_KEY, original);
      } catch (rollbackError) {
        text += "（元に戻す処理にも失敗しました: " + message(rollbackError) + "）";
      }
      return unifyResult(combined.merged, false, text);
    }
  }

  global.ScheduleMove = { run: run, unify: unify };
})(typeof window !== "undefined" ? window : this);
