# -*- coding: utf-8 -*-
"""批量任务调度：下载 → 刮削 → 写入 MP3 标签 → 归档。"""
import os
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from core import downloader, paths, scraper, tagger

PROJECT_ROOT = paths.APP_ROOT
TMP_ROOT = os.path.join(paths.BUILD_DIR, "tmp")
DEFAULT_OUT = paths.DOWNLOAD_DIR


class Item(dict):
    pass


class Job:
    def __init__(self, items, options):
        self.id = uuid.uuid4().hex[:12]
        self.created = time.time()
        self.options = options
        self.status = "running"          # running / done / cancelled
        self.items = items
        self.logs = []
        self.lock = threading.RLock()
        self.cancel_flag = threading.Event()

    # ------------------------------------------------------------------
    def log(self, msg, level="info", item_idx=None):
        with self.lock:
            self.logs.append({
                "t": round(time.time() - self.created, 2),
                "msg": msg,
                "level": level,
                "item": item_idx,
            })
            if len(self.logs) > 400:
                del self.logs[:100]

    def update_item(self, idx, **kw):
        with self.lock:
            self.items[idx].update(kw)

    def snapshot(self):
        with self.lock:
            done = sum(1 for it in self.items
                       if it["status"] in ("done", "error", "skipped"))
            total = len(self.items)
            return {
                "id": self.id,
                "status": self.status,
                "created": self.created,
                "elapsed": round(time.time() - self.created, 1),
                "total": total,
                "finished": done,
                "overall": round(done / total * 100) if total else 0,
                "items": [dict(it) for it in self.items],
                "logs": self.logs[-120:],
                "options": self.options,
            }


class JobManager:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()

    def get(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)

    def create(self, rows, options):
        items = []
        for i, r in enumerate(rows):
            items.append({
                "idx": i,
                "url": r.get("url", "").strip(),
                "title_in": (r.get("title") or "").strip(),
                "artist_in": (r.get("artist") or "").strip(),
                "status": "pending",
                "stage": "等待中",
                "percent": 0,
                "speed": "",
                "error": "",
                "meta": {},
                "file": "",
                "filename": "",
                "filesize": 0,
                "duration": 0,
                "bitrate": 0,
                "source": "",
                "confidence": 0,
                "cover": "",
                "has_lyrics": False,
                "started": 0,
                "finished": 0,
            })
        job = Job(items, options)
        with self.lock:
            self.jobs[job.id] = job
            # 清理过期任务，保留最近 30 个
            if len(self.jobs) > 30:
                for k in sorted(self.jobs, key=lambda x: self.jobs[x].created)[:-30]:
                    self.jobs.pop(k, None)
        t = threading.Thread(target=self._run, args=(job,), daemon=True)
        t.start()
        return job

    def cancel(self, job):
        job.cancel_flag.set()
        job.status = "cancelled"
        job.log("已请求取消，正在结束当前任务…", "warn")

    # ------------------------------------------------------------------
    def _run(self, job):
        opt = job.options
        workers = max(1, min(3, int(opt.get("concurrency", 1))))
        job.log("任务开始：共 %d 条，并发 %d" % (len(job.items), workers))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(self._process_item, job, it) for it in job.items]
            for f in futures:
                try:
                    f.result()
                except Exception:
                    pass
        if job.status != "cancelled":
            job.status = "done"
        ok = sum(1 for it in job.items if it["status"] == "done")
        fail = sum(1 for it in job.items if it["status"] == "error")
        job.log("任务结束：成功 %d 条，失败 %d 条" % (ok, fail),
                "success" if fail == 0 else "warn")

    # ------------------------------------------------------------------
    def _process_item(self, job, it):
        idx = it["idx"]
        if job.cancel_flag.is_set():
            job.update_item(idx, status="skipped", stage="已取消")
            return
        opt = job.options
        out_dir = opt.get("out_dir") or DEFAULT_OUT
        out_dir = os.path.abspath(out_dir)
        os.makedirs(out_dir, exist_ok=True)
        tmp_dir = os.path.join(TMP_ROOT, job.id, str(idx))
        os.makedirs(tmp_dir, exist_ok=True)
        job.update_item(idx, status="running", stage="准备中", started=time.time())
        label = it["title_in"] or it["url"]

        def on_prog(pct, speed=""):
            job.update_item(idx, percent=round(pct, 1), speed=speed)

        def on_stage(s):
            job.update_item(idx, stage=s)
            job.log("[%d] %s" % (idx + 1, s), item_idx=idx)

        try:
            url = it["url"]
            if not url.startswith(("http://", "https://")):
                # 允许直接粘贴 BV 号
                if url.upper().startswith("BV"):
                    url = "https://www.bilibili.com/video/" + url
                elif url.isdigit():
                    url = "https://www.bilibili.com/video/av" + url
            job.update_item(idx, url=url)

            cookies = opt.get("bili_cookie") or None
            cookies_browser = opt.get("cookies_browser") or None
            info = downloader.probe(url, cookies_browser, cookies)
            if not info.get("ok"):
                raise downloader.DownloadError(info.get("error", "解析失败"))
            if not it["title_in"]:
                job.update_item(idx, title_in=downloader_probe_title(info, it))
            job.log("[%d] 识别到：%s / %s / %ds" % (
                idx + 1, info["title"][:60], info["uploader"], info["duration"]),
                item_idx=idx)

            on_stage("下载音频")
            fmt = (opt.get("format") or "mp3").lower()
            dl = downloader.download_audio(
                url, tmp_dir,
                quality=str(opt.get("quality", "320")),
                cookies_browser=cookies_browser,
                cookies_raw=cookies,
                fmt=fmt,
                on_progress=on_prog, on_stage=on_stage)
            if job.cancel_flag.is_set():
                job.update_item(idx, status="skipped", stage="已取消")
                _rmtree(tmp_dir)
                return
            job.update_item(idx, percent=97)

            # ---- 元数据 ----
            title_g = it["title_in"]
            artist_g = it["artist_in"]
            if not title_g or not artist_g:
                p_title, p_artist = scraper.parse_title_artist(info["title"], info["uploader"])
                title_g = title_g or p_title
                artist_g = artist_g or p_artist
                job.update_item(idx, title_in=title_g, artist_in=artist_g)

            meta = scraper.scrape(
                title_g, artist_g,
                duration=info["duration"],
                album_hint="",
                want_translation=bool(opt.get("translate_lyrics", True)),
                sources=tuple(opt.get("sources") or ("netease", "itunes", "musicbrainz")),
            )
            meta["video_url"] = info["webpage_url"]

            if not meta["artist"]:
                meta["artist"] = scraper.clean_uploader(info["uploader"]) or "未知歌手"
            if not meta["title"]:
                meta["title"] = scraper.strip_noise(info["title"]) or "未知歌曲"

            job.log("[%d] 匹配：%s | %s | %s | %s | 置信度 %.2f" % (
                idx + 1, meta["source"], meta["title"][:40], meta["artist"][:30],
                meta.get("album") or "-", meta.get("confidence", 0)),
                "success" if meta.get("confidence", 0) >= 0.42 else "warn",
                item_idx=idx)

            # ---- 命名并归档 ----
            template = opt.get("filename_template") or "{artist} - {title}"
            filename = tagger.build_filename(meta, template, fmt)
            job.update_item(idx, stage="写入标签")
            final_path = _unique_path(out_dir, filename)

            target_tmp = os.path.join(tmp_dir, "tagged" + tagger.format_ext(fmt))
            shutil.move(dl["path"], target_tmp)
            stats = tagger.write_tags(
                target_tmp, meta,
                embed_lyrics=bool(opt.get("embed_lyrics", True)),
                embed_cover=bool(opt.get("embed_cover", True)),
            )
            shutil.move(target_tmp, final_path)
            _rmtree(tmp_dir)

            item_meta = {
                "title": meta["title"],
                "artist": meta["artist"],
                "album": meta.get("album") or "",
                "year": meta.get("year") or "",
                "track": meta.get("track") or "",
                "genre": meta.get("genre") or "",
                "source": meta.get("source") or "",
                "confidence": meta.get("confidence", 0),
                "cover_url": meta.get("cover_url") or "",
                "has_cover": stats["has_cover"],
                "has_lyrics": stats["has_lyrics"],
                "lyrics_preview": (meta.get("lyrics_plain") or "")[:600],
                "candidates": meta.get("candidates") or [],
                "video_title": info["title"],
                "uploader": info["uploader"],
            }
            job.update_item(
                idx, status="done", stage="完成", percent=100, speed="",
                file=final_path, filename=os.path.basename(final_path),
                filesize=stats["size"], duration=stats["duration"],
                bitrate=stats["bitrate"], meta=item_meta,
                source=item_meta["source"], confidence=item_meta["confidence"],
                has_lyrics=stats["has_lyrics"], finished=time.time(),
                cover="/api/cover/%s/%d" % (job.id, idx),
            )
            job.log("[%d] 完成 → %s (%.1f MB)" % (
                idx + 1, os.path.basename(final_path), stats["size"] / 1024 / 1024),
                "success", item_idx=idx)
        except Exception as e:
            msg = str(e) or e.__class__.__name__
            job.update_item(idx, status="error", stage="失败", error=msg.rstrip(),
                            speed="", finished=time.time())
            job.log("[%d] 失败：%s" % (idx + 1, msg[:300]), "error", item_idx=idx)
            _rmtree(tmp_dir)


def downloader_probe_title(info, it):
    return it["title_in"] or info["title"]


def _unique_path(dir_path, filename):
    path = os.path.join(dir_path, filename)
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(filename)
    for i in range(2, 200):
        p = os.path.join(dir_path, "%s (%d)%s" % (stem, i, ext))
        if not os.path.exists(p):
            return p
    return os.path.join(dir_path, "%s (%s)%s" % (stem, int(time.time()), ext))


def _rmtree(path):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


manager = JobManager()
