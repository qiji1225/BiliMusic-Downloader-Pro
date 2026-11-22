# -*- coding: utf-8 -*-
"""路径解析：源码运行 与 PyInstaller 打包（exe）两种模式通用。

- RES_ROOT：只读资源（templates / static / vendor / bin）所在目录
    · 源码：项目根
    · exe：sys._MEIPASS（PyInstaller 解压出来的临时目录）
- APP_ROOT：可写数据（config.json / downloads / _build）所在目录
    · 源码：项目根
    · exe：exe 自身所在目录
"""
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    RES_ROOT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    APP_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    RES_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    APP_ROOT = RES_ROOT

BUILD_DIR = os.path.join(APP_ROOT, "_build")
DOWNLOAD_DIR = os.path.join(APP_ROOT, "downloads")
CONFIG_FILE = os.path.join(APP_ROOT, "config.json")


def ensure_dirs():
    for d in (BUILD_DIR, DOWNLOAD_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
