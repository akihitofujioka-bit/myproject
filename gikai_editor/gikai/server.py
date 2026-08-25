"""ローカル専用の HTTP サーバ。

画面は Web ブラウザで表示するが、通信するのはこのパソコンの中だけ。
外部への接続は一切行わない（127.0.0.1 だけで待ち受ける）。

標準ライブラリだけで動くので、Python さえ入っていれば追加の
インストールなしに起動できる。
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import socket
import threading
import traceback
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import photos as photos_mod
from .project import Article, Photo, Project, _new_id
from .proofread import Dictionaries, apply_fixes, proofread
from .proofread import Issue
from .summarize import shorten
from .textutil import count_chars, estimate_lines, normalize_manuscript

STATIC_DIR = Path(__file__).parent / "static"


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
        self.message = message


class AppState:
    """開いているプロジェクトを保持する。"""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.project: Project | None = None
        self.lock = threading.Lock()
        # サーバを止めるための呼び出し口（serve() が差し込む）
        self.shutdown_server = None

    def require(self) -> Project:
        if self.project is None:
            raise ApiError("プロジェクトが開かれていません", 409)
        return self.project


# ====================================================================== API


def _decode_upload(payload: dict) -> tuple[str, bytes]:
    """ブラウザから送られてきた {name, data(base64)} を復元する。"""
    name = payload.get("name") or "無題"
    raw = payload.get("data") or ""
    if "," in raw and raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        return name, base64.b64decode(raw)
    except Exception as e:
        raise ApiError(f"ファイルを読み取れませんでした: {e}")


def _built_files(p: Project) -> dict:
    """組み上がった Word と PDF の場所。画面の「開く」ボタンに使う。"""
    docx = sorted(p.output_dir.glob("*自動組版*.docx"),
                  key=lambda f: f.stat().st_mtime, reverse=True)
    pdf = sorted(p.output_dir.glob("*自動組版*.pdf"),
                 key=lambda f: f.stat().st_mtime, reverse=True)
    return {
        "docx": docx[0].name if docx else "",
        "pdf": pdf[0].name if pdf else "",
        "output_dir": str(p.output_dir),
    }


def _make_pdf(p: Project, name: str = "") -> dict:
    """組み上がった Word を PDF にする（プレビュー用）。

    Word も LibreOffice も無いパソコンがあるので、作れなかったときは
    そのことと、代わりに何をすればよいかを返す。行き止まりにしない。
    """
    from .docxio import docx_to_pdf

    built = _built_files(p)
    target = p.output_dir / (name or built["docx"])
    if not built["docx"] or not target.exists():
        raise ApiError("先に「議会だよりを作る」を押してください。")
    pdf = docx_to_pdf(target, p.output_dir)
    if pdf is None:
        return {
            "pdf": "",
            "message": ("このパソコンでは PDF を作れませんでした"
                        "（Word も LibreOffice も見つかりません）。\n"
                        "「Word で開く」を押すと、そのまま Word で確認できます。"),
        }
    return {"pdf": pdf.name, "message": ""}


def _resolve_open(p: Project, what: str) -> Path:
    """「開く」で開いてよい場所を、号のフォルダの中だけに限る。"""
    from . import easy

    named = {
        "inbox": easy.inbox_dir(p),
        "project": p.root,
        "output": p.output_dir,
    }
    if what in named:
        target = named[what]
    else:
        # 出力フォルダの中のファイル名（組み上がった Word / PDF）
        target = p.output_dir / Path(what).name
    target = target.resolve()
    if not str(target).startswith(str(p.root.resolve())):
        raise ApiError("この場所は開けません。")
    if not target.exists():
        raise ApiError(f"{target.name} がまだありません。")
    return target


def handle_api(state: AppState, path: str, body: dict, query: dict) -> dict:
    """API の入口。path は "/api/" を除いたもの。"""

    # ---------------- 稼働確認・終了 ----------------
    if path == "ping":
        # 起動しているかどうかの確認。バッチファイルと二重起動の判定に使う。
        from . import __version__

        return {
            "app": "gikai_editor",
            "version": __version__,
            "workspace": str(state.workspace),
            "project": state.project.root.name if state.project else "",
        }

    if path == "quit":
        # 黒い画面を閉じたあとでも終われるようにするための出口。
        # 応答を返しきってから止めたいので、少し遅らせて実行する。
        if state.shutdown_server is not None:
            threading.Timer(0.4, state.shutdown_server).start()
        return {"ok": True, "message": "終了しました"}

    # ---------------- プロジェクト ----------------
    if path == "workspace":
        # フォルダが消されていても一覧が失敗しないよう、毎回作り直す
        state.workspace.mkdir(parents=True, exist_ok=True)
        items = []
        for d in sorted(state.workspace.iterdir()):
            if (d / "project.json").exists():
                try:
                    with open(d / "project.json", encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception:
                    meta = {}
                items.append({
                    "name": d.name,
                    "path": str(d),
                    "title": meta.get("title", d.name),
                    "updated": meta.get("updated", ""),
                    "articles": len(meta.get("articles", [])),
                })
        return {"workspace": str(state.workspace), "projects": items}

    if path == "project/create":
        title = (body.get("title") or "").strip()
        if not title:
            raise ApiError("号の名前を入力してください（例: 第204号）")
        state.workspace.mkdir(parents=True, exist_ok=True)
        root = state.workspace / re.sub(r'[<>:"/\\|?*]', "_", title)
        if root.exists():
            raise ApiError(f"「{title}」はすでにあります")
        state.project = Project.create(root, title)
        state.project.data["issue_no"] = body.get("issue_no", "")
        state.project.data["issue_date"] = body.get("issue_date", "")
        state.project.save()
        return {"project": _project_summary(state.project)}

    if path == "project/open":
        name = body.get("name") or query.get("name", [""])[0]
        root = state.workspace / name
        if not (root / "project.json").exists():
            raise ApiError(f"{name} が見つかりません", 404)
        state.project = Project.open(root)
        return {"project": _project_summary(state.project)}

    if path == "project":
        p = state.require()
        return {"project": _project_summary(p)}

    if path == "project/settings":
        p = state.require()
        p.data["settings"].update(body.get("settings", {}))
        for k in ("title", "issue_no", "issue_date"):
            if k in body:
                p.data[k] = body[k]
        p.save()
        return {"project": _project_summary(p)}

    # ---------------- 様式 ----------------
    if path == "template/upload":
        p = state.require()
        name, data = _decode_upload(body)
        tmp = p.root / ("_upload_" + re.sub(r'[<>:"/\\|?*]', "_", name))
        tmp.write_bytes(data)
        try:
            result = p.set_template(tmp)
        finally:
            tmp.unlink(missing_ok=True)
        return result

    if path == "template/slots":
        p = state.require()
        return p.template_slots()

    if path == "template/image":
        p = state.require()
        name = query.get("name", [""])[0]
        data = p.template().image_bytes(name)
        if data is None:
            raise ApiError("その画像は様式にありません", 404)
        return {"_binary": data, "_mime": mimetypes.guess_type(name)[0] or "image/png"}

    # ---------------- 記事 ----------------
    if path == "article/import":
        p = state.require()
        name, data = _decode_upload(body)
        p.manuscripts_dir.mkdir(exist_ok=True)
        dest = p.manuscripts_dir / re.sub(r'[<>:"/\\|?*]', "_", name)
        dest.write_bytes(data)
        art = p.import_manuscript(dest)
        return {"article": art.to_dict(), "warnings": []}

    if path == "article/paste":
        p = state.require()
        text = body.get("text", "")
        if not text.strip():
            raise ApiError("原稿が空です")
        if body.get("normalize", True):
            text = normalize_manuscript(
                text, numbers=p.data["settings"].get("normalize_numbers", True)
            )
        art = Article(
            id=_new_id("art"),
            title=body.get("title", ""),
            author=body.get("author", ""),
            raw=body.get("text", ""),
            body=text,
        )
        p.put_article(art)
        return {"article": art.to_dict()}

    if path == "article/list":
        p = state.require()
        return {"articles": [a.to_dict() for a in p.articles()]}

    if path == "article/save":
        p = state.require()
        data = body.get("article") or {}
        art = p.get_article(data.get("id", ""))
        if not art:
            raise ApiError("記事が見つかりません", 404)
        before = art.body
        for k, v in data.items():
            if hasattr(art, k) and k != "id":
                setattr(art, k, v)
        # 本文に手が入ったら印を付ける。かんたんモードで作り直すと
        # フォルダの原稿から組み直すので、その前に確認を出すため
        if art.body != before:
            art.hand_edited = True
        p.put_article(art)
        return {"article": art.to_dict()}

    if path == "article/delete":
        p = state.require()
        p.delete_article(body.get("id", ""))
        return {"ok": True}

    if path == "article/delete_many":
        p = state.require()
        return p.delete_articles(body.get("ids") or [])

    if path == "outline":
        p = state.require()
        return p.outline()

    if path == "outline/sections":
        p = state.require()
        return p.set_sections(body.get("sections") or [])

    if path == "outline/assign":
        p = state.require()
        report = p.assign_sections(
            only_unassigned=body.get("only_unassigned", True))
        return {**report, "outline": p.outline()}

    if path == "outline/move":
        p = state.require()
        return p.move_article(body.get("id", ""), int(body.get("delta") or 0))

    if path == "article/proofread":
        p = state.require()
        return p.proofread_article(body.get("id", ""))

    if path == "article/autofix":
        p = state.require()
        art = p.get_article(body.get("id", ""))
        if not art:
            raise ApiError("記事が見つかりません", 404)
        st = p.data["settings"]
        issues = proofread(
            art.body, p.dictionaries,
            enabled=set(st.get("checks", [])),
            max_sentence=st.get("max_sentence", 90),
        )
        rule_ids = set(body["rule_ids"]) if body.get("rule_ids") else None
        before = art.body
        art.body = apply_fixes(art.body, issues, rule_ids)
        p.put_article(art)
        return {
            "article": art.to_dict(),
            "changed": before != art.body,
            "before": before,
        }

    if path == "article/fit":
        p = state.require()
        return p.fit_article(body.get("id", ""), target=body.get("target"))

    if path == "article/shorten":
        p = state.require()
        art = p.get_article(body.get("id", ""))
        if not art:
            raise ApiError("記事が見つかりません", 404)
        text = shorten(art.body, drop_fillers=bool(body.get("drop_fillers")))
        return {"text": text, "chars": count_chars(text), "before": count_chars(art.body)}

    if path == "article/titles":
        p = state.require()
        return p.suggest_titles(body.get("id", ""), body.get("max_chars", 13))

    if path == "text/measure":
        text = body.get("text", "")
        cpl = int(body.get("chars_per_line") or 0)
        return {
            "chars": count_chars(text),
            "lines": estimate_lines(text, cpl) if cpl else 0,
        }

    if path == "text/proofread":
        p = state.project
        dic = p.dictionaries if p else Dictionaries()
        st = p.data["settings"] if p else {}
        issues = proofread(
            body.get("text", ""), dic,
            enabled=set(st.get("checks", [])) if st.get("checks") else None,
            max_sentence=st.get("max_sentence", 90),
        )
        return {"issues": [i.to_dict() for i in issues]}

    # ---------------- 写真 ----------------
    if path == "photo/upload":
        p = state.require()
        name, data = _decode_upload(body)
        photo = p._store_photo(data, name)
        if body.get("article_id"):
            art = p.get_article(body["article_id"])
            if art:
                art.photos.append(photo.id)
                p.put_article(art)
        return {"photo": photo.to_dict()}

    if path == "photo/list":
        p = state.require()
        return {"photos": [x.to_dict() for x in p.photos()]}

    if path == "photo/save":
        p = state.require()
        data = body.get("photo") or {}
        ph = p.get_photo(data.get("id", ""))
        if not ph:
            raise ApiError("写真が見つかりません", 404)
        for k, v in data.items():
            if hasattr(ph, k) and k not in ("id", "file"):
                setattr(ph, k, v)
        p.put_photo(ph)
        return {"photo": ph.to_dict()}

    if path == "photo/delete":
        p = state.require()
        p.delete_photo(body.get("id", ""))
        return {"ok": True}

    if path == "photo/autolayout":
        p = state.require()
        return p.auto_layout(
            match_names=body.get("match_names", True),
            assign_slots=body.get("assign_slots", True),
        )

    if path == "template/images":
        p = state.require()
        tpl = p.template()
        return {"anchors": tpl.image_anchors()}

    if path == "photo/thumb":
        p = state.require()
        pid = query.get("id", [""])[0]
        data = p.photo_bytes(pid)
        return {"_binary": photos_mod.to_thumbnail(data), "_mime": "image/jpeg"}

    if path == "photo/preview":
        p = state.require()
        pid = query.get("id", [""])[0]
        slot = query.get("slot", [""])[0]
        data = p.photo_bytes(pid)
        if slot:
            original = p.template().image_bytes(slot)
            data = photos_mod.prepare_for_slot(data, slot, original)
        return {"_binary": photos_mod.to_thumbnail(data, 480), "_mime": "image/jpeg"}

    # ---------------- 自動組版 ----------------
    if path == "layout/get":
        p = state.require()
        spec = p.layout_spec
        return {"layout": spec.to_dict(), "metrics": spec.metrics(),
                "settings": p.data.get("settings", {})}

    if path == "layout/save":
        p = state.require()
        out = p.set_layout(body.get("layout") or {})
        if "settings" in body:
            p.data["settings"].update(body["settings"])
            p.save()
        return out

    if path == "compose":
        p = state.require()
        return p.compose(body.get("filename", ""))

    if path == "layout/plan":
        p = state.require()
        return p.plan_pages(int(body.get("target_pages") or 0))

    if path == "layout/fit":
        p = state.require()
        return p.fit_to_pages(int(body.get("target_pages") or 0))

    if path == "help":
        from .help import help_doc

        return help_doc()

    # ---------------- かんたんモード ----------------
    if path == "easy/state":
        p = state.require()
        from . import easy

        return {
            **easy.scan(p),
            "max_pages": int(p.data["settings"].get("target_pages") or 0),
            "hand_edited": easy.hand_edited(p),
            "missing": easy.missing_sections(p),
            "default_max_pages": easy.MAX_PAGES,
            "built": _built_files(p),
        }

    if path == "easy/folders":
        p = state.require()
        from . import easy

        return easy.ensure_folders(p)

    if path == "easy/max_pages":
        p = state.require()
        n = max(0, min(64, int(body.get("max_pages") or 0)))
        p.data["settings"]["target_pages"] = n
        p.save()
        return {"max_pages": n}

    if path == "easy/rename":
        p = state.require()
        from . import easy

        try:
            r = easy.rename(
                p, body.get("file", ""), body.get("name", ""),
                section_id=body.get("section", ""),
                with_photos=bool(body.get("with_photos")))
        except ValueError as e:
            raise ApiError(str(e))
        return {**r, **easy.scan(p)}

    if path == "easy/photo_plan":
        p = state.require()
        from . import easy

        return easy.photo_plan(p)

    if path == "easy/assign_photos":
        p = state.require()
        from . import easy

        try:
            r = easy.assign_photos(p, body.get("mapping") or {})
        except ValueError as e:
            raise ApiError(str(e))
        return {**r, **easy.scan(p)}

    if path == "easy/photo":
        p = state.require()
        from . import easy

        try:
            data, mime = easy.photo_bytes(p, query.get("file", [""])[0])
        except ValueError as e:
            raise ApiError(str(e), 404)
        return {"_binary": photos_mod.to_thumbnail(data, 360), "_mime": "image/jpeg"} \
            if photos_mod.HAS_PIL else {"_binary": data, "_mime": mime}

    if path == "easy/note_read":
        p = state.require()
        from . import easy

        try:
            return easy.read_note(p, body.get("file", ""))
        except ValueError as e:
            raise ApiError(str(e))

    if path == "easy/note_write":
        p = state.require()
        from . import easy

        try:
            r = easy.write_note(p, body.get("section", ""), body.get("name", ""),
                                body.get("text", ""), rel=body.get("file", ""))
        except ValueError as e:
            raise ApiError(str(e))
        return {**r, **easy.scan(p)}

    if path == "easy/renumber":
        p = state.require()
        from . import easy

        try:
            r = easy.renumber(p, body.get("section", ""))
        except ValueError as e:
            raise ApiError(str(e))
        return {**r, **easy.scan(p)}

    if path == "easy/build":
        p = state.require()
        from . import easy

        res = easy.build(p, max_pages=int(body.get("max_pages") or 0))
        return {**res, "built": _built_files(p)}

    if path == "easy/pdf":
        p = state.require()
        return _make_pdf(p, body.get("name", ""))

    if path == "open":
        p = state.require()
        from .shellopen import open_path

        what = body.get("what", "")
        target = _resolve_open(p, what)
        ok, msg = open_path(target)
        if not ok:
            raise ApiError(msg)
        return {"ok": True, "message": msg, "path": str(target)}

    # ---------------- 書き出し ----------------
    if path == "export":
        p = state.require()
        return p.export(body.get("filename", ""), make_pdf=bool(body.get("pdf")))

    if path == "export/preview":
        p = state.require()
        from .preview import build_preview

        return {"html": build_preview(p)}

    if path == "download":
        p = state.require()
        rel = query.get("file", [""])[0]
        target = (p.output_dir / Path(rel).name).resolve()
        if not str(target).startswith(str(p.output_dir.resolve())) or not target.exists():
            raise ApiError("ファイルが見つかりません", 404)
        out = {
            "_binary": target.read_bytes(),
            "_mime": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        }
        # プレビューは画面の中に出したいので、そのときだけ保存を促さない
        if not query.get("inline"):
            out["_filename"] = target.name
        return out

    # ---------------- 辞書 ----------------
    if path == "dict/get":
        p = state.require()
        f = p.root / "user_dict.json"
        if f.exists():
            return {"dict": json.loads(f.read_text(encoding="utf-8"))}
        return {"dict": {"terms": [], "rules": [], "ignore": []}}

    if path == "dict/save":
        p = state.require()
        f = p.root / "user_dict.json"
        f.write_text(
            json.dumps(body.get("dict", {}), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        p.reload_dictionaries()
        return {"ok": True}

    raise ApiError(f"不明な API: {path}", 404)


def _project_summary(p: Project) -> dict:
    return {
        "root": str(p.root),
        "name": p.root.name,
        "title": p.data.get("title", ""),
        "issue_no": p.data.get("issue_no", ""),
        "issue_date": p.data.get("issue_date", ""),
        "updated": p.data.get("updated", ""),
        "settings": p.data.get("settings", {}),
        "has_template": bool(p.data.get("template")),
        "articles": [a.to_dict() for a in p.articles()],
        "photos": [x.to_dict() for x in p.photos()],
    }


# ====================================================================== HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "GikaiEditor"
    state: AppState  # サーバ起動時に差し込む

    # ブラウザのコンソールを静かに保つ
    def log_message(self, fmt, *args):  # noqa: A003
        pass

    # -------------------------------------------------- 共通

    def _send(self, status: int, body: bytes, mime: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # ローカル専用。外部からの読み込みを禁止する
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, obj: dict):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _guard_origin(self) -> bool:
        """ローカル以外からのアクセスを拒否する。"""
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "::1", ""):
            self._json(403, {"error": "このツールはこのパソコンの中でのみ動きます"})
            return False
        return True

    # -------------------------------------------------- ルーティング

    def do_GET(self):  # noqa: N802
        if not self._guard_origin():
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        if path.startswith("/api/"):
            return self._run_api(path[5:], {}, query)

        # 静的ファイル
        rel = path.lstrip("/") or "index.html"
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if mime.startswith("text/") or mime == "application/javascript":
            mime += "; charset=utf-8"
        return self._send(200, target.read_bytes(), mime)

    def do_POST(self):  # noqa: N802
        if not self._guard_origin():
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if not path.startswith("/api/"):
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "送信内容を読み取れませんでした"})
        return self._run_api(path[5:], body, parse_qs(parsed.query))

    def _run_api(self, name: str, body: dict, query: dict):
        try:
            with self.state.lock:
                result = handle_api(self.state, name.strip("/"), body, query)
        except ApiError as e:
            return self._json(e.status, {"error": e.message})
        except FileNotFoundError as e:
            return self._json(404, {"error": str(e)})
        except Exception as e:  # pragma: no cover
            traceback.print_exc()
            return self._json(500, {"error": f"処理中にエラーが起きました: {e}"})

        if isinstance(result, dict) and "_binary" in result:
            extra = {}
            if result.get("_filename"):
                # 日本語のファイル名が化けないよう RFC 5987 形式で渡す
                name = result["_filename"]
                ascii_fallback = re.sub(r"[^\x20-\x7e]", "_", name).replace('"', "_")
                extra["Content-Disposition"] = (
                    f'attachment; filename="{ascii_fallback}"; '
                    f"filename*=UTF-8''{quote(name, safe='')}"
                )
            return self._send(200, result["_binary"], result.get("_mime", "application/octet-stream"), extra)
        return self._json(200, result)


def find_free_port(preferred: int = 8730) -> int:
    for port in range(preferred, preferred + 40):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def serve(workspace: Path | str, port: int = 0) -> ThreadingHTTPServer:
    state = AppState(Path(workspace))
    Handler.state = state
    port = port or find_free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    # 画面の「終了」ボタンからサーバを止められるようにする
    state.shutdown_server = httpd.shutdown
    return httpd
