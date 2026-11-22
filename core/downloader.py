# -*- coding: utf-8 -*-
"""基于 yt-dlp 的 B 站音频下载 + FFmpeg 转 MP3。"""
import os
import re
import shutil
import subprocess
import sys
import time

import yt_dlp

from core import bili, paths

PROJECT_ROOT = paths.RES_ROOT
BIN_DIR = os.path.join(PROJECT_ROOT, "bin")


class DownloadError(RuntimeError):
    pass


# --------------------------------------------------------------------------
def find_ffmpeg():
    """优先使用项目内置 bin/ffmpeg.exe，其次系统 PATH。返回目录或 None。"""
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for p in (os.path.join(BIN_DIR, exe), os.path.join(BIN_DIR, "ffmpeg", "bin", exe)):
        if os.path.isfile(p):
            return BIN_DIR
    found = shutil.which("ffmpeg")
    if found:
        return os.path.dirname(os.path.abspath(found))
    return None


def ffmpeg_version():
    loc = find_ffmpeg()
    if not loc:
        return ""
    try:
        exe = os.path.join(loc, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=10)
        m = re.search(r"ffmpeg version (\S+)", out.stdout or "")
        return m.group(1) if m else "可用"
    except Exception:
        return "可用"


def ytdlp_version():
    try:
        return yt_dlp.version.__version__
    except Exception:
        return "未知"


# --------------------------------------------------------------------------
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _base_opts(cookies_browser=None, cookies_raw=None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 25,
        "http_headers": {
            "User-Agent": _UA,
            "Referer": "https://www.bilibili.com/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        "extractor_args": {"bilibili": {"prefer_multi_flv": ["false"]}},
    }
    ff = find_ffmpeg()
    if ff:
        opts["ffmpeg_location"] = ff
    if cookies_raw:
        # 粘贴的 SESSDATA Cookie：既带请求头，也写成 cookie 文件供 CDN 请求复用
        opts["http_headers"]["Cookie"] = cookies_raw
        cf = bili.cookie_file(cookies_raw)
        if cf:
            opts["cookiefile"] = cf
    elif cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser, None, None, None)
    return opts


def probe(url, cookies_browser=None, cookies_raw=None):
    """只取元信息，不下载。"""
    opts = _base_opts(cookies_browser, cookies_raw)
    opts.update({"skip_download": True, "extract_flat": False})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info.get("_type") == "playlist":
            info = (info.get("entries") or [{}])[0] or {}
        return {
            "ok": True,
            "title": info.get("title") or "",
            "uploader": info.get("uploader") or info.get("channel") or "",
            "duration": int(info.get("duration") or 0),
            "thumbnail": info.get("thumbnail") or "",
            "upload_date": info.get("upload_date") or "",
            "webpage_url": info.get("webpage_url") or url,
            "id": info.get("id") or "",
            "view_count": info.get("view_count"),
            "description": (info.get("description") or "")[:800],
        }
    except Exception as e:
        return {"ok": False, "error": _friendly_error(e, url)}


def _friendly_error(err, url=""):
    msg = str(err)
    low = msg.lower()
    if "412" in msg or "precondition failed" in low:
        return ("B 站要求登录态（HTTP 412）。请在右上角「B 站账号」里粘贴你的 SESSDATA 登录后重试。")
    if "403" in msg:
        return ("B 站拒绝访问（HTTP 403）。通常是地区限制或需要登录，"
                "可在「B 站账号」粘贴 SESSDATA 后重试。")
    if "ffmpeg" in low or "ffprobe" in low:
        return "缺少 FFmpeg，无法转码。请确认项目 bin 目录中存在 ffmpeg.exe。"
    if "unsupported url" in low or "no suitable" in low or "not a valid url" in low:
        return "无法识别的链接，请确认是 B 站视频地址（如 https://www.bilibili.com/video/BVxxxx）。"
    if "private" in low or "会员" in msg or "vip" in low:
        return "该视频为会员/充电专属，需要登录 Cookie。"
    if "timed out" in low or "timeout" in low:
        return "网络超时，请重试或检查网络/代理。"
    return re.sub(r"\x1b\[[0-9;]*m", "", msg)[:400]


# --------------------------------------------------------------------------
# 导出格式 → (yt-dlp 编码, 文件扩展名)
AUDIO_CODECS = {
    "mp3": ("mp3", ".mp3"),
    "m4a": ("m4a", ".m4a"),
    "wav": ("wav", ".wav"),
    "flac": ("flac", ".flac"),
    "ogg": ("vorbis", ".ogg"),
}
LOSSY_FORMATS = ("mp3", "m4a", "ogg")


def _fmt_pair(fmt):
    return AUDIO_CODECS.get((fmt or "mp3").lower(), AUDIO_CODECS["mp3"])


def download_audio(url, out_dir, quality="0", cookies_browser=None, cookies_raw=None,
                   fmt="mp3", on_progress=None, on_stage=None):
    """下载最佳音轨并按指定格式转码（mp3/m4a/wav/flac/ogg）。

    quality: '0'=最高/VBR/无损忽略, '320'=320kbps 等。
    返回 dict(path, title, uploader, duration, thumbnail, video_id)。
    """
    fmt = (fmt or "mp3").lower()
    if fmt not in AUDIO_CODECS:
        fmt = "mp3"
    codec, ext = _fmt_pair(fmt)
    if not find_ffmpeg():
        raise DownloadError("缺少 FFmpeg，无法转换音频格式。")
    os.makedirs(out_dir, exist_ok=True)
    uid = str(int(time.time() * 1000))[-8:]
    opts = _base_opts(cookies_browser, cookies_raw)
    opts.update({
        "format": "bestaudio/best",
        "outtmpl": os.path.join(out_dir, "%(id)s." + uid + ".%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": codec,
            "preferredquality": str(quality) if codec in ("mp3", "m4a", "vorbis") else "0",
        }],
        "overwrites": True,
    })

    def hook(d):
        if not on_progress:
            return
        try:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                pct = (done / total * 100) if total else 0
                speed = d.get("speed") or 0
                on_progress(min(95, pct), _fmt_speed(speed))
            elif d.get("status") == "finished":
                on_progress(96, "转码中")
        except Exception:
            pass

    opts["progress_hooks"] = [hook]
    if on_stage:
        on_stage("解析视频信息")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        raise DownloadError(_friendly_error(e, url))

    if info.get("_type") == "playlist":
        entries = [x for x in (info.get("entries") or []) if x]
        if not entries:
            raise DownloadError("该链接没有可下载的音频。")
        info = entries[0]

    base = os.path.join(out_dir, "%s.%s" % (info.get("id"), uid))
    out_file = base + ext
    if not os.path.isfile(out_file):
        for f in os.listdir(out_dir):
            if f.startswith("%s.%s" % (info.get("id"), uid)) and f.lower().endswith(ext):
                out_file = os.path.join(out_dir, f)
                break
    if not os.path.isfile(out_file):
        for f in os.listdir(out_dir):
            if f.startswith("%s.%s" % (info.get("id"), uid)) and not f.endswith(".part"):
                cand = os.path.join(out_dir, f)
                if os.path.splitext(cand)[1].lower() in (".mp3", ".m4a", ".wav", ".flac", ".ogg"):
                    out_file = cand
                    break
    if not os.path.isfile(out_file):
        raise DownloadError("转码未生成音频文件（FFmpeg 可能执行失败）。")
    if on_stage:
        on_stage("刮削元数据")
    return {
        "path": out_file,
        "title": info.get("title") or "",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": int(info.get("duration") or 0),
        "thumbnail": info.get("thumbnail") or "",
        "video_id": info.get("id") or "",
        "upload_date": info.get("upload_date") or "",
    }


def _fmt_speed(bps):
    if not bps:
        return ""
    if bps > 1024 * 1024:
        return "%.1f MB/s" % (bps / 1024 / 1024)
    return "%.0f KB/s" % (bps / 1024)
