# -*- coding: utf-8 -*-
"""BiliMusic 桌面外壳：PyQt6 + QtWebEngine（内置 Chromium），不需要外部浏览器。

启动流程：
1. 起本地 HTTP 服务（app.create_server，只监听 127.0.0.1，自动选可用端口）
2. 用原生窗口加载这个地址
3. 网页里的「下载 / 打包下载」走 Chromium 原生下载，文件落到输出目录
"""
import os
import sys
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from core import paths  # noqa: E402

if not paths.FROZEN:
    sys.path.insert(0, os.path.join(BASE, "vendor"))

paths.ensure_dirs()

# 窗口模式没有控制台，print/异常统一写日志，避免 stdout=None 时报错
_LOG = open(os.path.join(paths.BUILD_DIR, "run.log"), "a", encoding="utf-8", buffering=1)


class _Tee(object):
    def __init__(self, f):
        self.f = f

    def write(self, s):
        try:
            self.f.write(s)
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            self.f.flush()
        except Exception:
            pass

    def isatty(self):
        return False


sys.stdout = _Tee(_LOG)
sys.stderr = _Tee(_LOG)

import app as bili_app  # noqa: E402

from PyQt6.QtCore import QUrl  # noqa: E402
from PyQt6.QtGui import QIcon  # noqa: E402
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile  # noqa: E402
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMainWindow  # noqa: E402


class WebPage(QWebEnginePage):
    """把网页里的 JS 报错写进 run.log，出问题时方便定位。"""

    def javaScriptConsoleMessage(self, level, msg, line, src):
        try:
            sys.stderr.write("[js] %s:%s %s\n" % (os.path.basename(src or ""), line, msg))
        except Exception:
            pass


def _dedupe(path):
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    n = 1
    while os.path.exists("%s (%d)%s" % (root, n, ext)):
        n += 1
    return "%s (%d)%s" % (root, n, ext)


def main():
    httpd, url, cfg = bili_app.create_server("127.0.0.1", None)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("BiliMusic Downloader Pro")
    for cand in ("static/icon.ico", "static/logo.png"):
        p = os.path.join(BASE, *cand.split("/"))
        if os.path.isfile(p):
            qt_app.setWindowIcon(QIcon(p))
            break

    # 持久化浏览器配置：主题、列表草稿（localStorage）关掉再开还在
    profile = QWebEngineProfile("bilimusic", qt_app)
    profile.setPersistentStoragePath(os.path.join(paths.BUILD_DIR, "webprofile"))
    profile.setCachePath(os.path.join(paths.BUILD_DIR, "webcache"))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
    )

    win = QMainWindow()
    win.setWindowTitle("BiliMusic Downloader Pro")
    # 按屏幕大小自适应，避免小屏/缩放比例大时窗口右侧被切掉
    scr = qt_app.primaryScreen().availableGeometry()
    w = max(900, min(1360, scr.width() - 40))
    h = max(620, min(900, scr.height() - 60))
    win.resize(w, h)
    win.setMinimumSize(min(1020, w), min(700, h))

    view = QWebEngineView(win)
    view.setPage(WebPage(profile, view))

    out_dir = cfg.get("out_dir") or paths.DOWNLOAD_DIR

    def on_download(item):
        try:
            name = item.suggestedFileName() or "download"
            target = _dedupe(os.path.join(out_dir, os.path.basename(name)))
            item.setDownloadDirectory(os.path.dirname(target))
            item.setDownloadFileName(os.path.basename(target))

            def done():
                if item.isFinished() and not item.isPaused():
                    win.statusBar().showMessage("已保存：" + item.downloadFileName(), 8000)

            item.isFinishedChanged.connect(done)
            item.accept()
        except Exception as e:
            win.statusBar().showMessage("下载失败：%s" % e, 8000)

    profile.downloadRequested.connect(on_download)

    view.setUrl(QUrl(url))
    win.setCentralWidget(view)
    win.statusBar().showMessage("就绪 · 输出目录：" + out_dir, 6000)
    win.show()
    qt_app.aboutToQuit.connect(lambda: httpd.shutdown())
    return qt_app.exec()


if __name__ == "__main__":
    sys.exit(main())
