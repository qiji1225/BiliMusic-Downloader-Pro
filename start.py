# -*- coding: utf-8 -*-
"""BiliMusic Downloader Pro 启动器：检查环境 → 启动本地服务 → 自动打开浏览器。"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(ROOT, "vendor")
sys.path.insert(0, VENDOR)
sys.path.insert(0, ROOT)

BANNER = r"""
 ____  _ _ _ __  __ _                 
| __ )(_) (_)  \/  (_)_ __ ___   ___ 
|  _ \| | | | |\/| | | '_ ` _ \ / _ \
| |_) | | | | |  | | | | | | | |  __/
|____/|_|_|_|_|  |_|_|_| |_| |_|\___|
"""


def fail(msg):
    print("\n[错误] " + msg)
    try:
        input("\n按回车键退出…")
    except Exception:
        pass
    sys.exit(1)


def main():
    if sys.version_info < (3, 8):
        fail("需要 Python 3.8 或更高版本，当前为 %s。\n请到 python.org 安装最新版 Python。" % sys.version.split()[0])

    try:
        import yt_dlp  # noqa: F401
        import mutagen  # noqa: F401
    except Exception as e:
        fail("内置依赖加载失败：%s\n请确认项目 vendor 目录完整（yt_dlp / mutagen）。" % e)

    from core import downloader
    if not downloader.find_ffmpeg():
        print("[警告] 未检测到 FFmpeg，MP3 转码会失败。")
        print("        请把 ffmpeg.exe / ffprobe.exe 放到：%s" % os.path.join(ROOT, "bin"))

    print(BANNER)
    print(" Python %s | yt-dlp %s | FFmpeg %s" % (
        sys.version.split()[0], downloader.ytdlp_version(), downloader.ffmpeg_version() or "未找到"))
    print("-" * 52)

    import app
    try:
        return app.main()
    except Exception:
        traceback.print_exc()
        fail("服务启动失败，请把上面的错误信息发给开发者。")


if __name__ == "__main__":
    sys.exit(main())
