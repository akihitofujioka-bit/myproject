/*
 * キャラクター写真の登録欄。
 *
 * 写真と設定は Character を通して端末内だけに保存する。
 */
(function (global) {
  "use strict";

  var SLOT_LABELS = {
    top: "トップ",
    fridge: "冷蔵庫",
    "docs-tracker": "書類",
    stock: "備蓄",
    kakeibo: "家計簿",
    cards: "ポイントカード"
  };

  var INTERVALS = [
    { value: "day", label: "毎日" },
    { value: "week", label: "毎週" },
    { value: "month", label: "毎月" }
  ];

  var VEILS = [
    { value: "light", label: "薄い" },
    { value: "normal", label: "普通" },
    { value: "strong", label: "濃い" }
  ];

  function addOption(select, item) {
    var option = global.document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    select.appendChild(option);
  }

  function addSelect(parent, labelText, items, value, onChange) {
    var label = global.document.createElement("label");
    label.style.cssText = "display:flex;align-items:center;gap:8px";
    label.appendChild(global.document.createTextNode(labelText + " "));

    var select = global.document.createElement("select");
    select.style.cssText = "font:inherit;color:var(--text);background:var(--surface);border:1px solid var(--border);border-radius:7px;padding:8px;min-height:44px";
    items.forEach(function (item) { addOption(select, item); });
    select.value = value;
    select.addEventListener("change", function () { onChange(select.value); });
    label.appendChild(select);
    parent.appendChild(label);
  }

  function makeButton(label, onClick) {
    var button = global.document.createElement("button");
    button.type = "button";
    button.className = "small";
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  function photoAlbumPlugin() {
    var cap = global.Capacitor;
    return cap && cap.Plugins && cap.Plugins.PhotoAlbum ? cap.Plugins.PhotoAlbum : null;
  }

  function mount(container, opts) {
    if (!container || !global.Character) return;
    opts = opts || {};
    var onChange = typeof opts.onChange === "function" ? opts.onChange : function () {};
    var toast = typeof opts.toast === "function" ? opts.toast : function () {};
    var editors = [];

    function emptyRecord(slot) {
      return {
        slot: slot,
        interval: "day",
        veil: "normal",
        startDate: global.Character.todayString(new Date()),
        photos: [],
        album: null,
        albumIds: [],
        manualPhotos: []
      };
    }

    function createEditor(slot) {
      var box = global.document.createElement("div");
      box.style.cssText = "border-top:1px solid var(--border);padding-top:14px;margin-top:14px";
      container.appendChild(box);

      var editor = { slot: slot, box: box, record: emptyRecord(slot), urls: [], albumStatus: "ok" };
      editors.push(editor);

      function clearURLs() {
        editor.urls.forEach(function (url) { global.URL.revokeObjectURL(url); });
        editor.urls = [];
      }

      function render() {
        clearURLs();
        box.innerHTML = "";

        var heading = global.document.createElement("h3");
        heading.style.cssText = "font-size:15px;margin:0 0 10px";
        heading.textContent = SLOT_LABELS[slot];
        box.appendChild(heading);

        var noticeText = global.Character.albumNotice(
          editor.albumStatus,
          editor.record.album ? editor.record.album.title : ""
        );
        if (noticeText) {
          var notice = global.document.createElement("p");
          notice.className = "note";
          notice.style.margin = "0 0 10px";
          notice.textContent = noticeText;
          box.appendChild(notice);
        }

        var photos = global.document.createElement("div");
        photos.style.cssText = "display:grid;gap:10px;margin-bottom:10px";
        if (!editor.record.photos.length) {
          var empty = global.document.createElement("p");
          empty.className = "note";
          empty.style.margin = "0";
          empty.textContent = "写真はまだありません";
          photos.appendChild(empty);
        }

        editor.record.photos.forEach(function (photo, index) {
          var row = global.document.createElement("div");
          row.style.cssText = "display:flex;align-items:center;gap:8px;flex-wrap:wrap";

          var url = global.URL.createObjectURL(photo);
          editor.urls.push(url);
          var image = global.document.createElement("img");
          image.src = url;
          image.alt = SLOT_LABELS[slot] + "の写真 " + (index + 1);
          image.style.cssText = "width:64px;height:64px;object-fit:cover;border-radius:8px;border:1px solid var(--border)";
          row.appendChild(image);

          if (!editor.record.album) {
            var up = makeButton("上へ", function () { move(index, -1); });
            up.disabled = index === 0;
            row.appendChild(up);
            var down = makeButton("下へ", function () { move(index, 1); });
            down.disabled = index === editor.record.photos.length - 1;
            row.appendChild(down);
            row.appendChild(makeButton("削除", function () { remove(index); }));
          }
          photos.appendChild(row);
        });
        box.appendChild(photos);

        if (editor.record.album) {
          var connected = global.document.createElement("p");
          connected.className = "note";
          connected.textContent = "アルバム『" + editor.record.album.title + "』とつないでいます（" + editor.record.photos.length + "枚）";
          box.appendChild(connected);
          box.appendChild(makeButton("つなげるのをやめる", disconnectAlbum));
        } else {
          var fileLabel = global.document.createElement("label");
          fileLabel.style.cssText = "display:block;margin-bottom:10px";
          fileLabel.appendChild(global.document.createTextNode("写真を追加 "));
          var input = global.document.createElement("input");
          input.type = "file";
          input.accept = "image/*";
          input.multiple = true;
          input.addEventListener("change", function () { addPhotos(input); });
          fileLabel.appendChild(input);
          box.appendChild(fileLabel);

          var plugin = photoAlbumPlugin();
          if (plugin) {
            var albumArea = global.document.createElement("div");
            albumArea.style.cssText = "margin-bottom:10px";
            albumArea.appendChild(makeButton("アルバムとつなげる", function () {
              showAlbums(albumArea, plugin);
            }));
            box.appendChild(albumArea);
          }
        }

        var settings = global.document.createElement("div");
        settings.style.cssText = "display:flex;flex-wrap:wrap;gap:10px 16px";
        addSelect(settings, "切り替え", INTERVALS, editor.record.interval, function (value) {
          update({ interval: value }, true);
        });
        addSelect(settings, "膜の濃さ", VEILS, editor.record.veil, function (value) {
          update({ veil: value }, false);
        });
        box.appendChild(settings);
      }

      function save(next) {
        return global.Character.save(next).then(function () {
          editor.record = next;
          render();
          onChange(slot);
        }).catch(function () {
          toast("保存できませんでした");
          render();
        });
      }

      function changedRecord() {
        return {
          slot: editor.record.slot,
          interval: editor.record.interval,
          veil: editor.record.veil,
          startDate: global.Character.todayString(new Date()),
          photos: editor.record.photos.slice(),
          album: editor.record.album,
          albumIds: editor.record.albumIds.slice(),
          manualPhotos: editor.record.manualPhotos.slice()
        };
      }

      function update(values, resetDate) {
        var next = changedRecord();
        if (!resetDate) next.startDate = editor.record.startDate;
        Object.keys(values).forEach(function (key) { next[key] = values[key]; });
        save(next);
      }

      function move(index, direction) {
        var next = changedRecord();
        var other = index + direction;
        var photo = next.photos[index];
        next.photos[index] = next.photos[other];
        next.photos[other] = photo;
        save(next);
      }

      function remove(index) {
        if (!global.confirm("この写真を削除しますか？")) return;
        var next = changedRecord();
        next.photos.splice(index, 1);
        save(next);
      }

      function addPhotos(input) {
        var files = Array.prototype.slice.call(input.files || []);
        if (!files.length) return;
        Promise.all(files.map(function (file) { return global.Character.resize(file); })).then(function (photos) {
          var next = changedRecord();
          next.photos = next.photos.concat(photos);
          return save(next);
        }).catch(function () {
          toast("保存できませんでした");
          render();
        });
      }

      function showAlbums(parent, plugin) {
        Promise.resolve(plugin.listAlbums()).then(function (result) {
          var status = result && result.status;
          if (status !== "ok") {
            editor.albumStatus = status === "limited" ? "limited" : "denied";
            render();
            return;
          }
          editor.albumStatus = "ok";
          var old = parent.querySelector("select");
          if (old) old.remove();
          var select = global.document.createElement("select");
          select.style.cssText = "display:block;margin-top:8px;font:inherit;max-width:100%;padding:8px";
          addOption(select, { value: "", label: "アルバムを選んでください" });
          (result.albums || []).forEach(function (album) {
            addOption(select, { value: album.id, label: album.title + "（" + album.count + "枚）" });
          });
          select.addEventListener("change", function () {
            var album = (result.albums || []).find(function (item) { return item.id === select.value; });
            if (album) connectAlbum(album, plugin);
          });
          parent.appendChild(select);
        }, function () {
          toast("アルバムを読み込めませんでした");
        });
      }

      function connectAlbum(album, plugin) {
        var next = changedRecord();
        next.manualPhotos = editor.record.photos.slice();
        next.album = { id: album.id, title: album.title };
        next.albumIds = [];
        next.startDate = global.Character.todayString(new Date());
        save(next).then(function () {
          return global.Character.syncAlbum(slot, plugin);
        }).then(function (result) {
          editor.albumStatus = result.status;
          return global.Character.load(slot);
        }).then(function (record) {
          editor.record = record;
          render();
          onChange(slot);
        }).catch(function () {
          toast("アルバムを読み込めませんでした");
        });
      }

      function disconnectAlbum() {
        var next = changedRecord();
        next.photos = editor.record.manualPhotos.slice();
        next.album = null;
        next.albumIds = [];
        next.manualPhotos = [];
        next.startDate = global.Character.todayString(new Date());
        editor.albumStatus = "ok";
        save(next);
      }

      global.Character.load(slot).then(function (record) {
        editor.record = record;
        editor.albumStatus = global.Character.albumStatus(slot);
        render();
      }).catch(function () {
        editor.record = emptyRecord(slot);
        render();
      });
    }

    global.Character.SLOTS.forEach(createEditor);
    global.addEventListener("pagehide", function () {
      editors.forEach(function (editor) {
        editor.urls.forEach(function (url) { global.URL.revokeObjectURL(url); });
        editor.urls = [];
      });
    }, { once: true });
  }

  global.CharacterSettings = { mount: mount };
})(typeof window !== "undefined" ? window : this);
