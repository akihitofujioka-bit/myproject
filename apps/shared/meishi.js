/*
 * 名刺から読み取った文字を、決まった規則で項目に振り分ける。
 * 保存する前に、必ず人が確認して直す前提で作っている。
 */
(function (global) {
  "use strict";

  var WORDS = {
    company: ["株式会社", "(株)", "㈱", "有限会社", "合同会社", "市役所", "町役場", "村役場", "県庁", "議会", "協会", "組合", "法人", "事務所", "大学", "学校"],
    department: ["部", "課", "係", "室", "局", "センター", "委員会", "グループ"],
    title: ["代表取締役", "取締役", "社長", "部長", "課長", "係長", "主任", "主査", "主事", "参事", "室長", "所長", "局長", "議長", "副議長", "議員", "委員長", "理事", "会長", "教授"]
  };

  var PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"
  ];

  function emptyResult() {
    return {
      name: "",
      company: "",
      department: "",
      title: "",
      phones: [],
      email: "",
      address: "",
      url: "",
      memo: ""
    };
  }

  function normalizeSpaces(text) {
    return String(text == null ? "" : text)
      .replace(/[\s　]+/g, " ")
      .replace(/^ | $/g, "");
  }

  function makeLines(lines) {
    if (!Array.isArray(lines)) return [];
    return lines.map(function (line, index) {
      var source = typeof line === "string" ? { text: line } : (line || {});
      return {
        text: normalizeSpaces(source.text),
        height: typeof source.height === "number" ? source.height : 0,
        index: index,
        used: false
      };
    }).filter(function (line) {
      return line.text !== "";
    });
  }

  function addUnique(values, value) {
    if (values.indexOf(value) === -1) values.push(value);
  }

  function lastLabelIndex(text, pattern, before) {
    var part = text.slice(0, before);
    var match;
    var last = -1;
    pattern.lastIndex = 0;
    while ((match = pattern.exec(part)) !== null) last = match.index;
    return last;
  }

  function normalizeContactText(text) {
    return String(text).replace(/[０-９]/g, function (character) {
      return String.fromCharCode(character.charCodeAt(0) - 0xFEE0);
    }).replace(/(\d)\s*[－‐ー―−]\s*(?=\d)/g, "$1-");
  }

  function isFaxNumber(text, phone) {
    var normalized = normalizeContactText(text);
    var at = normalized.indexOf(phone);
    if (at === -1) return /(?:FAX|Fax|F\.)/.test(normalized);
    var faxAt = lastLabelIndex(normalized, /(?:FAX|Fax|F\.)/g, at + 1);
    var phoneAt = lastLabelIndex(normalized, /(?:TEL|Tel|電話|携帯|Mobile)/g, at + 1);
    return faxAt !== -1 && faxAt > phoneAt;
  }

  function startsWithPrefecture(text) {
    return PREFECTURES.some(function (name) {
      return text.indexOf(name) === 0;
    });
  }

  function isAddressStart(text) {
    return text.indexOf("〒") !== -1 || /\d{3}-\d{4}/.test(text) || startsWithPrefecture(text);
  }

  function isAddressContinuation(text) {
    return /\d|ビル|階|F/.test(text);
  }

  function findWord(text, words) {
    var found = "";
    var foundAt = -1;
    words.forEach(function (word) {
      var at = text.indexOf(word);
      if (at === -1) return;
      if (foundAt === -1 || at < foundAt || (at === foundAt && word.length > found.length)) {
        found = word;
        foundAt = at;
      }
    });
    return found ? { word: found, at: foundAt } : null;
  }

  function replacePart(line, start, length) {
    line.text = normalizeSpaces(line.text.slice(0, start) + " " + line.text.slice(start + length));
    if (!line.text) line.used = true;
  }

  function companyPart(text) {
    var found = findWord(text, WORDS.company);
    var prefixWords = ["株式会社", "(株)", "㈱", "有限会社", "合同会社"];
    var title;
    var end;
    if (!found) return null;

    if (prefixWords.indexOf(found.word) !== -1) {
      end = text.indexOf(" ", found.at);
      if (end === -1) end = text.length;
    } else {
      title = findWord(text.slice(found.at + found.word.length), WORDS.title);
      if (title) end = found.at + found.word.length + title.at;
      else {
        end = text.indexOf(" ", found.at);
        if (end === -1) end = text.length;
      }
    }
    return { text: normalizeSpaces(text.slice(0, end)), start: 0, length: end };
  }

  function hasNameCharacters(text) {
    return text.length >= 2 && text.length <= 10 &&
      /^[一-龯々〆ヵヶぁ-んァ-ヶー]+$/.test(text);
  }

  function isSpacedName(text) {
    var parts = normalizeSpaces(text).split(" ");
    return parts.length === 2 && parts.every(function (part) {
      return part.length >= 1 && part.length <= 5 && hasNameCharacters(part);
    });
  }

  function departmentPart(text) {
    var tokens = text.split(" ");
    var offset = 0;
    var i;
    var j;
    var at;
    var end;
    var best;

    if (isSpacedName(text) && !findWord(text, WORDS.title)) return null;

    for (i = 0; i < tokens.length; i++) {
      best = null;
      for (j = 0; j < WORDS.department.length; j++) {
        at = tokens[i].indexOf(WORDS.department[j]);
        if (at === -1) continue;
        end = at + WORDS.department[j].length;
        if (end < 3) continue;
        if (!best || end < best.length) {
          best = { text: tokens[i].slice(0, end), start: offset, length: end };
        }
      }
      if (best) return best;
      offset += tokens[i].length + 1;
    }
    return null;
  }

  function isName(text) {
    var normalized = normalizeSpaces(text);
    var compact = normalized.replace(/ /g, "");
    return hasNameCharacters(compact) && !departmentPart(normalized);
  }

  function parse(lines) {
    var result = emptyResult();
    var work = makeLines(lines);
    var memo = [];

    // 1. 電話・FAX・メール・URL
    work.forEach(function (line) {
      var found;
      var hasContact;
      if (!global.Contacts || typeof global.Contacts.find !== "function") return;
      found = global.Contacts.find(line.text);
      hasContact = found.phones.length || found.emails.length || found.urls.length;
      if (!hasContact) return;

      found.phones.forEach(function (phone) {
        if (isFaxNumber(line.text, phone)) memo.push("FAX: " + phone);
        else addUnique(result.phones, phone);
      });
      if (!result.email && found.emails.length) result.email = found.emails[0];
      if (!result.url && found.urls.length) result.url = found.urls[0];
      line.used = true;
    });

    // 2. 住所
    work.forEach(function (line, index) {
      var addressLines;
      var nextIndex;
      if (line.used || !isAddressStart(line.text)) return;
      addressLines = [line.text];
      line.used = true;
      nextIndex = index + 1;
      while (nextIndex < work.length && !work[nextIndex].used &&
          (isAddressStart(work[nextIndex].text) || isAddressContinuation(work[nextIndex].text))) {
        addressLines.push(work[nextIndex].text);
        work[nextIndex].used = true;
        nextIndex++;
      }
      if (!result.address) result.address = addressLines.join("\n");
      else memo.push(addressLines.join("\n"));
    });

    // 3. 会社
    work.forEach(function (line) {
      var part;
      if (line.used) return;
      part = companyPart(line.text);
      if (!part) return;
      if (!result.company) {
        result.company = part.text;
        replacePart(line, part.start, part.length);
      }
    });

    // 4. 部署
    work.forEach(function (line) {
      var part;
      if (line.used) return;
      part = departmentPart(line.text);
      if (!part) return;
      if (!result.department) {
        result.department = part.text;
        replacePart(line, part.start, part.length);
      }
    });

    // 5. 役職
    work.forEach(function (line) {
      var part;
      if (line.used) return;
      part = findWord(line.text, WORDS.title);
      if (!part) return;
      if (!result.title) {
        result.title = part.word;
        replacePart(line, part.at, part.word.length);
      }
    });

    // 6. 氏名
    work.forEach(function (line) {
      if (line.used || !isName(line.text)) return;
      if (!result.name || line.height > result.nameHeight) {
        result.name = normalizeSpaces(line.text);
        result.nameHeight = line.height;
        result.nameIndex = line.index;
      }
    });
    if (result.name) {
      work.forEach(function (line) {
        if (line.index === result.nameIndex) line.used = true;
      });
    }
    delete result.nameHeight;
    delete result.nameIndex;

    // 7. 残った行
    work.forEach(function (line) {
      if (!line.used && line.text) memo.push(line.text);
    });
    result.memo = memo.join("\n");
    return result;
  }

  function meetingCandidates(date, items, events) {
    var candidates = [];
    var byCalendarId = Object.create(null);

    (Array.isArray(items) ? items : []).forEach(function (item) {
      var candidate;
      if (!item || item.dueOn !== date) return;
      candidate = {
        scheduleId: item.id || "",
        calEventId: item.calEventId || "",
        title: item.title || "",
        date: item.dueOn,
        time: item.time || ""
      };
      candidates.push(candidate);
      if (candidate.calEventId) byCalendarId[candidate.calEventId] = candidate;
    });

    (Array.isArray(events) ? events : []).forEach(function (event) {
      var linked;
      if (!event || event.date !== date) return;
      linked = event.id ? byCalendarId[event.id] : null;
      if (linked) {
        linked.calEventId = event.id;
        if (!linked.time) linked.time = event.startTime || "";
        return;
      }
      candidates.push({
        scheduleId: "",
        calEventId: event.id || "",
        title: event.title || "",
        date: event.date,
        time: event.startTime || ""
      });
    });

    return candidates.map(function (candidate, index) {
      candidate.sortIndex = index;
      return candidate;
    }).sort(function (a, b) {
      var aParts;
      var bParts;
      var aMinutes;
      var bMinutes;
      if (!a.time && b.time) return -1;
      if (a.time && !b.time) return 1;
      aParts = /^(\d{1,2}):(\d{2})/.exec(a.time);
      bParts = /^(\d{1,2}):(\d{2})/.exec(b.time);
      aMinutes = aParts ? Number(aParts[1]) * 60 + Number(aParts[2]) : 0;
      bMinutes = bParts ? Number(bParts[1]) * 60 + Number(bParts[2]) : 0;
      if (aMinutes < bMinutes) return -1;
      if (aMinutes > bMinutes) return 1;
      return a.sortIndex - b.sortIndex;
    }).map(function (candidate) {
      delete candidate.sortIndex;
      return candidate;
    });
  }

  global.Meishi = {
    WORDS: WORDS,
    parse: parse,
    meetingCandidates: meetingCandidates
  };
})(typeof window !== "undefined" ? window : this);
