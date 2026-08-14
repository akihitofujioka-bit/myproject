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
        for k, v in data.items():
            if hasattr(art, k) and k != "id":
                setattr(art, k, v)
        p.put_article(art)
        return {"article": art.to_dict()}

    if path == "article/delete":
        p = state.require()
        p.delete_article(body.get("id", ""))
        return {"ok": True}

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
        return {
            "_binary": target.read_bytes(),
            "_mime": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            "_filename": target.name,
        }

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
