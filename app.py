# -*- coding: utf-8 -*-
"""BiliMusic Downloader Pro — 本地 Web 服务（纯标准库 http.server，零额外依赖）。"""
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import urllib.parse
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core import bili, downloader, jobs, paths, scraper, tagger  # noqa: E402

ROOT = paths.RES_ROOT
sys.path.insert(0, ROOT)
# 源码模式用项目自带 vendor；打包成 exe 后 yt-dlp/mutagen 已随 PyInstaller 打进包里
if not paths.FROZEN:
    sys.path.insert(0, os.path.join(ROOT, "vendor"))

CONFIG_PATH = paths.CONFIG_FILE
STATIC_DIR = os.path.join(ROOT, "static")
TEMPLATE_DIR = os.path.join(ROOT, "templates")

DEFAULT_CONFIG = {
    "out_dir": paths.DOWNLOAD_DIR,
    "filename_template": "{artist} - {title}",
    "quality": "320",
    "format": "mp3",
    "concurrency": 1,
    "embed_lyrics": True,
    "embed_cover": True,
    "translate_lyrics": True,
    "cookies_browser": "",
    "bili_cookie": "",
    "bili_mid": 0,
    "bili_uname": "",
    "bili_face": "",
    "bili_vip": False,
    "bili_level": 0,
    "sources": ["netease", "qq", "itunes", "musicbrainz"],
    "port": 8787,
    "autosave": True,
}

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".txt": "text/plain; charset=utf-8",
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f) or {})
    except Exception:
        pass
    out = cfg.get("out_dir") or "downloads"
    if not os.path.isabs(out):
        cfg["out_dir"] = os.path.normpath(os.path.join(ROOT, out))
    return cfg


def save_config(new_cfg):
    cfg = load_config()
    for k in DEFAULT_CONFIG:
        if k in new_cfg and new_cfg[k] is not None:
            # 空 Cookie 不覆盖已有登录态（避免前端自动保存把登录冲掉）
            if k == "bili_cookie" and not str(new_cfg[k] or "").strip():
                continue
            cfg[k] = new_cfg[k]
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


def public_config(cfg):
    """给前端的配置：Cookie 不回传原文，只告诉前端「已登录」。"""
    out = dict(cfg)
    raw = out.pop("bili_cookie", "") or ""
    out["bili_cookie_set"] = bool(raw)
    out["bili_cookie_hint"] = ("SESSDATA=" + bili.sessdata_of(raw)[:6] + "…") if raw else ""
    return out


def bili_session(cfg):
    cookie = cfg.get("bili_cookie") or ""
    if not cookie:
        return None
    mid = int(cfg.get("bili_mid") or 0)
    return {
        "ok": True,
        "logged_in": True,
        "mid": mid,
        "uname": cfg.get("bili_uname") or "",
        "face": cfg.get("bili_face") or "",
        "vip": bool(cfg.get("bili_vip")),
        "level": int(cfg.get("bili_level") or 0),
        "cookie_hint": "SESSDATA=" + bili.sessdata_of(cookie)[:6] + "…",
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "BiliMusicDownloaderPro/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 静音访问日志
        pass

    # ------------------------------------------------------------------ utils
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return {}

    def _serve_file(self, path, download_name=None, inline=False):
        if not os.path.isfile(path):
            self._send(404, {"error": "文件不存在"})
            return
        ctype = MIME.get(os.path.splitext(path)[1].lower())
        if not ctype:
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        if download_name:
            disp = "inline" if inline else "attachment"
            ascii_name = re.sub(r"[^\x20-\x7e]", "_", download_name).replace('"', "'")
            quoted = urllib.parse.quote(download_name)
            self.send_header("Content-Disposition",
                             '%s; filename="%s"; filename*=UTF-8\'\'%s'
                             % (disp, ascii_name, quoted))
        self.end_headers()
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            fp = os.path.join(TEMPLATE_DIR, "index.html")
            if os.path.isfile(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            return self._send(404, "<h1>index.html 缺失</h1>", "text/html; charset=utf-8")

        if path.startswith("/static/"):
            name = path[len("/static/"):]
            fp = os.path.normpath(os.path.join(STATIC_DIR, name))
            if os.path.commonpath([STATIC_DIR, fp]) != STATIC_DIR:
                return self._send(403, {"error": "forbidden"})
            return self._serve_file(fp)

        if path == "/favicon.ico":
            return self._send(204, b"")

        if path == "/api/health":
            cfg = load_config()
            return self._send(200, {
                "ok": True,
                "python": sys.version.split()[0],
                "ytdlp": downloader.ytdlp_version(),
                "ffmpeg": downloader.ffmpeg_version() or "未找到",
                "ffmpeg_path": downloader.find_ffmpeg() or "",
                "config": public_config(cfg),
                "formats": [{"key": k, "label": v[1], "ext": v[0]}
                            for k, v in tagger.FORMATS.items()],
                "out_dir": cfg.get("out_dir"),
                "root": ROOT,
                "bili": bili_session(cfg),
            })

        if path == "/api/job":
            job = jobs.manager.get((query.get("id") or [""])[0])
            if not job:
                return self._send(404, {"error": "任务不存在"})
            return self._send(200, job.snapshot())

        if path.startswith("/api/cover/"):
            parts = path.strip("/").split("/")
            if len(parts) != 4:
                return self._send(400, {"error": "bad request"})
            job = jobs.manager.get(parts[2])
            if not job:
                return self._send(404, {"error": "任务不存在"})
            try:
                item = job.items[int(parts[3])]
            except Exception:
                return self._send(404, {"error": "条目不存在"})
            fp = item.get("file")
            if not fp or not os.path.isfile(fp):
                return self._send(404, {"error": "文件不存在"})
            tags = tagger.read_tags(fp)
            data = tags.get("cover_bytes")
            if not data:
                return self._send(404, {"error": "无封面"})
            return self._send(200, data, tags.get("cover_mime") or "image/jpeg",
                              {"Cache-Control": "max-age=3600"})

        if path.startswith("/api/lyrics/"):
            parts = path.strip("/").split("/")
            if len(parts) != 4:
                return self._send(400, {"error": "bad request"})
            job = jobs.manager.get(parts[2])
            if not job:
                return self._send(404, {"error": "任务不存在"})
            try:
                item = job.items[int(parts[3])]
            except Exception:
                return self._send(404, {"error": "条目不存在"})
            fp = item.get("file")
            if not fp or not os.path.isfile(fp):
                return self._send(404, {"error": "文件不存在"})
            tags = tagger.read_tags(fp)
            return self._send(200, {"lyrics": tags.get("lyrics_text") or ""})

        if path.startswith("/api/file/"):
            parts = path.strip("/").split("/")
            if len(parts) != 4:
                return self._send(400, {"error": "bad request"})
            job = jobs.manager.get(parts[2])
            if not job:
                return self._send(404, {"error": "任务不存在"})
            try:
                item = job.items[int(parts[3])]
            except Exception:
                return self._send(404, {"error": "条目不存在"})
            fp = item.get("file")
            if not fp:
                return self._send(404, {"error": "尚未生成"})
            return self._serve_file(fp, os.path.basename(fp),
                                    inline=(query.get("inline") or ["0"])[0] == "1")

        if path.startswith("/api/zip/"):
            job_id = path[len("/api/zip/"):]
            job = jobs.manager.get(job_id)
            if not job:
                return self._send(404, {"error": "任务不存在"})
            files = [(it["file"], it["filename"]) for it in job.items
                     if it["status"] == "done" and os.path.isfile(it["file"] or "")]
            if not files:
                return self._send(404, {"error": "没有可打包的文件"})
            zip_dir = os.path.join(ROOT, "_build", "zip")
            os.makedirs(zip_dir, exist_ok=True)
            zp = os.path.join(zip_dir, "BiliMusicDownloaderPro_%s.zip" % job_id)
            with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED) as z:
                used = set()
                for fp, name in files:
                    base = name
                    i = 2
                    while base in used:
                        stem, ext = os.path.splitext(name)
                        base = "%s (%d)%s" % (stem, i, ext)
                        i += 1
                    used.add(base)
                    z.write(fp, base)
            return self._serve_file(zp, "BiliMusicDownloaderPro_%s.zip" % job_id)

        if path == "/api/config":
            return self._send(200, public_config(load_config()))

        if path == "/api/bili/status":
            return self._send(200, {"bili": bili_session(load_config())})

        if path == "/api/bili/folders":
            cfg = load_config()
            cookie = cfg.get("bili_cookie") or ""
            if not cookie:
                return self._send(401, {"error": "还没登录，请先粘贴 SESSDATA"})
            try:
                mid = int(cfg.get("bili_mid") or 0) or bili.nav(cookie)["mid"]
                return self._send(200, {"folders": bili.folders(cookie, mid)})
            except bili.BiliError as e:
                return self._send(400, {"error": str(e)})

        if path == "/api/bili/fav":
            cfg = load_config()
            cookie = cfg.get("bili_cookie") or ""
            if not cookie:
                return self._send(401, {"error": "还没登录，请先粘贴 SESSDATA"})
            try:
                media_id = (query.get("media_id") or [""])[0]
                page = int((query.get("page") or ["1"])[0] or 1)
                size = int((query.get("size") or ["20"])[0] or 20)
                if not media_id:
                    return self._send(400, {"error": "缺少收藏夹 id"})
                return self._send(200, bili.folder_page(cookie, media_id, page, size))
            except bili.BiliError as e:
                return self._send(400, {"error": str(e)})

        return self._send(404, {"error": "not found"})

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._json_body()

        try:
            if path == "/api/config":
                return self._send(200, public_config(save_config(body)))

            if path == "/api/bili/login":
                raw = (body.get("cookie") or "").strip()
                cookie = bili.normalize_cookie(raw)
                if not cookie:
                    return self._send(400, {"error": "请先粘贴 SESSDATA 或整行 Cookie"})
                try:
                    info = bili.nav(cookie)
                except bili.BiliError as e:
                    return self._send(400, {"error": str(e)})
                cfg = save_config({
                    "bili_cookie": cookie,
                    "bili_mid": info["mid"],
                    "bili_uname": info["uname"],
                    "bili_face": info["face"],
                    "bili_vip": info["vip"],
                    "bili_level": info["level"],
                })
                try:
                    bili.cookie_file(cookie)
                except Exception:
                    pass
                return self._send(200, {"ok": True, "bili": bili_session(cfg)})

            if path == "/api/bili/logout":
                cfg = save_config({
                    "bili_cookie": "__clear__",
                    "bili_mid": 0, "bili_uname": "", "bili_face": "",
                    "bili_vip": False, "bili_level": 0,
                })
                # save_config 会拦截空 Cookie，这里显式清空
                cfg["bili_cookie"] = ""
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                return self._send(200, {"ok": True, "bili": bili_session(cfg)})

            if path == "/api/probe":
                urls = [u.strip() for u in (body.get("urls") or []) if u.strip()]
                cfg = load_config()
                out = []
                for u in urls[:8]:
                    info = downloader.probe(u, cfg.get("cookies_browser") or None,
                                            cfg.get("bili_cookie") or None)
                    if info.get("title") and not info.get("uploader"):
                        pass
                    out.append(info)
                return self._send(200, {"results": out})

            if path == "/api/start":
                rows = body.get("rows") or []
                if not rows:
                    return self._send(400, {"error": "请至少填写一条链接"})
                cfg = load_config()
                opts = dict(cfg)
                opts.update(body.get("options") or {})
                job = jobs.manager.create(rows, opts)
                return self._send(200, {"job_id": job.id})

            if path.startswith("/api/cancel/"):
                job = jobs.manager.get(path[len("/api/cancel/"):])
                if not job:
                    return self._send(404, {"error": "任务不存在"})
                jobs.manager.cancel(job)
                return self._send(200, {"ok": True})

            if path == "/api/rescrape":
                title = (body.get("title") or "").strip()
                artist = (body.get("artist") or "").strip()
                if not title:
                    return self._send(400, {"error": "请填写歌名"})
                meta = scraper.scrape(
                    title, artist,
                    duration=int(body.get("duration") or 0),
                    want_translation=bool(body.get("translate_lyrics", True)))
                cover_preview = ""
                if meta.get("cover_bytes"):
                    import base64
                    cover_preview = "data:%s;base64,%s" % (
                        meta.get("cover_mime") or "image/jpeg",
                        base64.b64encode(meta["cover_bytes"]).decode())
                return self._send(200, {
                    "title": meta["title"], "artist": meta["artist"],
                    "album": meta.get("album", ""), "year": meta.get("year", ""),
                    "track": meta.get("track", ""), "genre": meta.get("genre", ""),
                    "source": meta.get("source", ""),
                    "confidence": meta.get("confidence", 0),
                    "lyrics": (meta.get("lyrics") or "")[:3000],
                    "candidates": meta.get("candidates") or [],
                    "cover": cover_preview,
                })

            if path == "/api/retag":
                job = jobs.manager.get(body.get("job_id") or "")
                if not job:
                    return self._send(404, {"error": "任务不存在"})
                idx = int(body.get("idx", -1))
                item = job.items[idx]
                fp = item.get("file")
                if not fp or not os.path.isfile(fp):
                    return self._send(404, {"error": "文件不存在"})
                fields = body.get("fields") or {}
                meta = dict(item.get("meta") or {})
                meta.update({k: fields.get(k, meta.get(k, "")) for k in
                             ("title", "artist", "album", "year", "track", "genre")})
                if fields.get("lyrics") is not None:
                    meta["lyrics"] = fields["lyrics"]
                    meta["lyrics_plain"] = scraper._lrc_to_plain(fields["lyrics"]) \
                        if "[" in (fields["lyrics"] or "") else fields["lyrics"]
                old = tagger.read_tags(fp)
                if old.get("cover_bytes"):
                    meta["cover_bytes"] = old["cover_bytes"]
                    meta["cover_mime"] = old["cover_mime"]
                tagger.write_tags(fp, meta, embed_lyrics=True, embed_cover=True)
                # 封面二进制用完即丢，否则 job 快照 / JSON 响应会被它撑爆
                meta.pop("cover_bytes", None)
                meta.pop("cover_mime", None)
                # 若歌名/歌手变更，尝试同步文件名
                if body.get("rename", True):
                    newname = tagger.build_filename(
                        meta, load_config().get("filename_template"),
                        tagger.fmt_of_path(fp))
                    if os.path.basename(fp) != newname:
                        newpath = jobs._unique_path(os.path.dirname(fp), newname)
                        try:
                            os.rename(fp, newpath)
                            item["file"] = newpath
                            item["filename"] = os.path.basename(newpath)
                        except Exception:
                            pass
                item["meta"] = meta
                item["title_in"] = meta.get("title", item["title_in"])
                item["artist_in"] = meta.get("artist", item["artist_in"])
                return self._send(200, {"ok": True, "filename": item.get("filename"),
                                        "meta": meta})

            if path == "/api/open-folder":
                d = load_config().get("out_dir") or jobs.DEFAULT_OUT
                os.makedirs(d, exist_ok=True)
                if os.name == "nt":
                    os.startfile(d)  # noqa: S606
                else:
                    import subprocess
                    subprocess.Popen(["open", d])
                return self._send(200, {"ok": True, "dir": d})

            return self._send(404, {"error": "not found"})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._send(500, {"error": "%s: %s" % (e.__class__.__name__, e)})


def create_server(host="127.0.0.1", port=None):
    """建好 HTTP 服务但不阻塞，返回 (httpd, url, cfg)。供 exe 外壳与命令行共用。"""
    cfg = load_config()
    want = int(port or cfg.get("port") or 8787)
    paths.ensure_dirs()
    os.makedirs(cfg.get("out_dir") or jobs.DEFAULT_OUT, exist_ok=True)

    httpd = None
    got = want
    for p in range(want, want + 60):
        try:
            httpd = ThreadingHTTPServer((host, p), Handler)
            got = p
            break
        except OSError:
            continue
    if httpd is None:
        raise RuntimeError("端口被占用，无法启动。请关闭占用 %d 的程序后重试。" % want)
    httpd.daemon_threads = True
    return httpd, "http://%s:%d/" % (host, got), cfg


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    try:
        httpd, url, cfg = create_server(args.host, args.port)
    except RuntimeError as e:
        print(e)
        return 1

    print("=" * 56)
    print("  BiliMusic Downloader Pro 已启动")
    print("  地址：%s" % url)
    print("  输出：%s" % cfg.get("out_dir"))
    print("  FFmpeg：%s" % (downloader.ffmpeg_version() or "未找到"))
    print("  关闭此窗口即停止服务")
    print("=" * 56)
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
