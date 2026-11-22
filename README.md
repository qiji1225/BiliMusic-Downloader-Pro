\# BiliMusic Downloader Pro · B站音频提取｜多格式导出｜元数据标签工坊

> 本地网页版B站音频提取工具，粘贴B站视频链接，下载音频，自动刮削\*\*封面、歌名、歌手、专辑、年代、曲目、曲风、时间轴歌词\*\*，完整内嵌到音频文件内部，支持批量任务、B站Cookie登录、收藏夹一键导入、多音频格式自由切换、配置自动持久化，可打包为独立单文件EXE，无需浏览器也可运行。



\---



\## ✨ 主要功能

1\. \*\*B站音频提取\*\*

&#x20;   - 支持完整视频链接、BV号、AV号、分P链接自动解析

&#x20;   - 批量粘贴导入任务，支持自定义`链接 | 歌名 | 歌手`格式

&#x20;   - \*\*单条任务独立处理\*\*：任务状态为「待处理」时鼠标悬浮，点击「立即处理」仅运行当前条目，不影响其他任务

&#x20;   - Bug修复：删除任务条目后，新增条目不会残留上一条旧数据

2\. \*\*B站账号能力（SESSDATA Cookie登录）\*\*

&#x20;   - 粘贴`SESSDATA`值或完整Cookie字符串完成登录，自动识别解析

&#x20;   - 解决403/412访问受限视频下载问题

&#x20;   - ⭐\*\*一键导入B站收藏夹\*\*：读取自建/默认收藏夹，分页加载，全选/勾选导入任务列表，自动过滤失效视频、音频类型收藏

&#x20;   - Cookie仅本地保存在`config.json`，不会上传任何第三方服务器，点击退出即可清除登录信息

3\. \*\*多音频导出格式自由选择\*\*

&#x20;   支持 `MP3 / M4A / WAV / FLAC / OGG`，切换格式自动适配对应标签容器，封面、时间轴歌词全部内嵌写入文件，不生成外挂文件。



| 格式 | 扩展名 | 编码 | 码率选项 | 标签容器说明 |

|---|---|---|---|---|

| MP3 | `.mp3` | LAME | 320 / 256 / 192 / 128 / VBR | ID3v2.3（APIC内嵌封面 + USLT时间轴歌词） |

| M4A | `.m4a` | AAC | 256 / 192 / 128 | MP4原子块（covr封面 + ©lyr歌词元数据） |

| WAV | `.wav` | PCM无损 | 不可调 | ID3v2.3写入WAV容器 |

| FLAC | `.flac` | FLAC无损 | 不可调 | Vorbis Comment + PICTURE图片块 |

| OGG | `.ogg` | Vorbis | 192 / 128 / 96 | Vorbis Comment + base64编码封面 |



> 无损格式(WAV/FLAC)码率选项会自动置灰提示不可调节；不同播放器对OGG标签兼容性有限，通用性优先推荐MP3 / M4A。



4\. \*\*元数据智能刮削（多源加权匹配）\*\*

&#x20;   - 数据源：网易云音乐、QQ音乐、iTunes Search、MusicBrainz、LRCLIB歌词兜底

&#x20;   - 算法归一化歌名歌手，加权相似度打分，过滤伴奏/Live/翻唱干扰版本；界面展示\*\*匹配来源、置信度分数\*\*

&#x20;   - 支持手动编辑全部标签，支持手动重新刮削，自定义写入歌词、封面

5\. \*\*配置自动持久化\*\*

&#x20;   - 网页端全部设置：输出格式、码率、输出目录、并发数、封面/歌词开关、刮削源，修改即自动保存至`config.json`，无需手动点保存按钮

&#x20;   - 任务草稿本地缓存：链接、歌名歌手信息浏览器本地存储，刷新页面、重启程序自动恢复任务列表，手动清空条目才会删除草稿

6\. \*\*主题切换\*\*

&#x20;   - 右上角主题切换按钮：\*\*亮色 / 暗色 / 跟随系统\*\*三种模式，主题选择配置同样自动保存

7\. \*\*输出下载\*\*

&#x20;   - 单条结果独立下载，预览内嵌封面、歌词、匹配信息

&#x20;   - 全部任务支持打包ZIP批量下载

&#x20;   - 文件同时落地本地`downloads`目录，路径可自定义修改

8\. \*\*部署方式\*\*

&#x20;   - 方式A：源码运行，Python环境；\*\*源码仓库不内置FFmpeg二进制\*\*，需要用户自行准备

&#x20;   - 方式B：PyQt6打包\*\*单文件EXE\*\*，内置Chromium内核+FFmpeg，双击打开原生窗口，不需要外部浏览器访问网页



\---



\## 🚀 Windows 启动教程



\### 方式一：源码直接运行（适合调试、二次修改）

> ⚠️ \*\*源码仓库不携带 ffmpeg.exe（规避GitHub单文件100MB限制）\*\*

> 1. 下载FFmpeg Windows静态版 `ffmpeg‑essentials\_build`，把 `ffmpeg.exe` 放入项目 `bin/` 文件夹

> 2. 或者直接下载 Release 打包好的EXE版本，开箱即用，无需手动准备FFmpeg



1\. 克隆或者下载本项目完整源码

```powershell

git clone \[https://github.com/](https://github.com/)你的用户名/BiliMusic-Downloader-Pro.git

cd BiliMusic-Downloader-Pro

```

2\. 创建并激活虚拟环境

```powershell

python -m venv venv

.\\venv\\Scripts\\Activate.ps1

```

> 如果PowerShell禁止执行脚本：`Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`，输入Y确认。



3\. 安装Python依赖

```powershell

pip install yt-dlp mutagen flask pyqt6 pyqt6‑webengine

```



4\. \*\*放入FFmpeg\*\*

将下载得到的 `ffmpeg.exe` 复制到项目 `bin/` 目录。



5\. 启动程序

\- 双击 `启动.bat`

\- 或者命令行：`python launcher.py`



程序启动成功后，浏览器自动打开 `\[http://127.0.0.1:8787](http://127.0.0.1:8787)`；关闭黑色控制台窗口代表停止服务。



> Python版本要求 >=3.10。

> 手动指定端口启动：

```powershell

python launcher.py --port 8899 --no-browser

```



\### 方式二：打包独立单文件EXE（普通用户推荐）

> 打包前注意：\*\*打包时请把ffmpeg.exe复制回 bin 目录\*\*，打包完成后再移出，不要提交到git源码。

> 打包环境：项目根目录，已经激活venv虚拟环境，目录内必须存在`launcher.py`、`templates`、`static`、`bin/ffmpeg.exe`。



PowerShell完整打包命令（注意使用反引号 `` ` ``作为续行符，不要使用CMD的`^`）

```powershell

pyinstaller --noconfirm --onefile --noconsole --name "BiliMusic Downloader Pro" `

\--add-data "templates;templates" `

\--add-data "static;static" `

\--add-data "bin;bin" `

\--collect-data yt\_dlp `

\--collect-data mutagen `

\--hidden-import core.bili `

\--hidden-import core.paths `

\--hidden-import optparse `

launcher.py

```

打包完成产物输出路径：`./dist/BiliMusic Downloader Pro.exe`



> 打包体积较大，因为内置QtWebEngine Chromium内核 + FFmpeg，实现脱离浏览器原生窗口运行。

> ⚠️ `dist`、`build`、`venv` 不要提交到GitHub仓库；打包好的EXE上传至项目 \*\*Releases附件\*\*，Release允许大于100MB文件。



\---



\## 📖 使用完整步骤

1\. \*\*B站Cookie登录（强烈推荐）【可选，但建议登录】\*\*

&#x20;   右侧面板「B站账号」，粘贴你的`SESSDATA`（可以只粘贴SESSDATA值，也可以直接粘贴浏览器完整Cookie字符串），点击登录B站。

&#x20;   > 获取SESSDATA：浏览器登录bilibili.com，F12开发者工具 → 存储/Cookie → `bilibili.com`，复制SESSDATA字段。

&#x20;   - 登录后可处理需要登录态的视频，支持⭐一键导入收藏夹。

&#x20;   - 全部Cookie只保存在本机`config.json`，不会上传网络，点退出即可清空。



2\. \*\*添加下载任务\*\*

&#x20;   - 单行输入B站链接，支持BV、AV、完整链接、分P链接；歌名歌手留空程序自动识别。

&#x20;   - 批量粘贴：每行一条任务，支持多种格式

&#x20;   ```

&#x20;   \[https://www.bilibili.com/video/BVxxxx](https://www.bilibili.com/video/BVxxxx)

&#x20;   \[https://www.bilibili.com/video/BVxxxx](https://www.bilibili.com/video/BVxxxx) | 歌曲名 | 歌手名

&#x20;   歌曲名 - 歌手 | \[https://www.bilibili.com/video/BVxxxx](https://www.bilibili.com/video/BVxxxx)

&#x20;   ```

&#x20;   - 收藏夹导入：登录后，点击【⭐导入收藏夹】弹窗，选择收藏夹，勾选视频，导入选中，自动填充到任务列表。失效视频、音频收藏自动过滤跳过。



3\. \*\*任务执行两种模式\*\*

&#x20;   - 全部任务：点击【开始处理】批量运行全部待处理条目。

&#x20;   - \*\*单条立即处理\*\*：鼠标悬浮任务行状态「待处理」，会显示▶立即处理，点击后\*\*仅执行当前这一行任务，其他任务保持原有状态\*\*。



4\. \*\*设置导出参数\*\*

&#x20;   右侧设置面板，选择导出音频格式、码率、输出保存路径、并发任务数，配置\*\*修改自动保存\*\*。右上角切换主题模式：亮色 / 暗色 / 跟随系统。



5\. \*\*处理完成\*\*

&#x20;   - 每条任务卡片：预览内嵌封面、歌词、匹配来源、置信度；支持单条下载。

&#x20;   - 编辑标签：手动修改歌名歌手专辑年代歌词封面，支持重新刮削元数据。

&#x20;   - 全部打包下载，输出文件同时保存在本地`downloads`文件夹。



\---



\## 📊 元数据刮削匹配逻辑

| 数据源 | 提供信息 |

|---|---|

| 网易云音乐（主源） | 中文歌曲库，歌名、歌手、专辑、年份、800×800高清封面、带翻译LRC时间轴歌词 |

| QQ音乐（补充源） | 网易云缺失版权歌曲，发行信息、曲风、曲序、封面、歌词 |

| iTunes Search API | 海外曲目兜底，风格Genre、发行时间、高清封面 |

| MusicBrainz + Cover Art Archive | 兜底元数据，ISRC编码，专辑曲目排序 |

| LRCLIB | 歌词兜底，无需API Key获取LRC |



匹配逻辑：对输入歌名歌手做清洗归一化，多源候选做相似度加权打分（歌名权重0.62，歌手权重0.33，时长辅助微调），自动降低伴奏、Live现场、翻唱版本得分；低于置信阈值则保留用户原始输入，界面标记「未匹配」，可以手动编辑标签。



写入音频内部完整元数据（不同格式自动适配标签块）：

歌名、歌手、专辑艺术家、专辑、发行年代、曲目序号、曲风、作曲、发行方；

内嵌Front‑Cover封面图片；带时间轴LRC歌词；同时记录原视频链接、元数据来源、匹配置信度自定义字段。



> 标签兼容：Windows资源管理器、foobar2000、千千静听、移动端主流播放器。



\---



\## ❗ 常见问题排错表



| 现象 | 原因 \& 解决方法 |

|---|---|

| B站返回403 / 412 | 视频需要登录权限，粘贴SESSDATA Cookie登录后重试；B站风控可以等待片刻再操作 |

| FFmpeg找不到 | 源码版确认`bin/ffmpeg.exe`已放置；被杀毒软件隔离，恢复；或者直接使用Release打包EXE版本 |

| 元数据匹配到翻唱/Live版本 | 在结果卡片点击【编辑标签】→重新刮削，或者手动修改歌名歌手保存标签 |

| 没有歌词 | 纯音乐、公开曲库无该歌曲歌词属于正常，支持手动粘贴LRC歌词保存到文件 |

| 网页访问打不开 | 端口被别的软件占用，控制台会打印实际访问地址；程序会自动顺延可用端口 |

| 下载速度很慢 | B站服务端限速，属于正常现象；右侧设置调低并发数到1 |

| EXE打包运行提示index.html缺失 | pyinstaller打包命令缺少`--add‑data`参数，确保templates、static、bin资源被打进程序 |

| 删除条目后新增任务携带旧数据 | 确认使用最新版代码，浏览器Ctrl+F5强制刷新页面清除旧JS缓存 |



\---



\## 📂 项目目录（GitHub源码版本）

```

BiliMusic‑Downloader‑Pro/

├─ 启动.bat                # Windows双击启动脚本

├─ launcher.py             # 程序统一入口，同时支持网页模式 / PyQt6 EXE窗口模式

├─ start.py

├─ app.py

├─ README.md

├─ .gitignore

├─ core/

│  ├─ downloader.py        # yt‑dlp下载，ffmpeg音频转码，包含FFmpeg缺失检测

│  ├─ scraper.py           # 多源元数据刮削、相似度打分匹配

│  ├─ tagger.py            # mutagen多格式标签写入（MP3/M4A/WAV/FLAC/OGG）

│  ├─ bili.py              # SESSDATA登录、B站收藏夹接口处理

│  └─ jobs.py              # 任务队列管理，单条/批量任务调度

├─ templates/

│  └─ index.html           # 网页主界面模板

├─ static/

│  ├─ app.js               # 前端交互逻辑：任务管理、主题切换、单条立即处理、草稿缓存

│  └─ style.css            # 页面样式，亮色/暗色/系统主题样式

├─ bin/

│  └─ .gitkeep             # git占位文件，ffmpeg.exe需要用户自行放入，不上传git

├─ downloads/              # 默认音频输出文件夹（本地运行自动生成，不提交仓库）

└─ \_build/                 # 程序运行临时目录（本地运行自动生成，不提交仓库）

```



\### `.gitignore`

```gitignore

\# Python 缓存

\_\_pycache\_\_/

\*.pyc

\*.pyo

\*.pyd



\# 虚拟环境

venv/

env/



\# PyInstaller打包产物

build/

dist/

\*.spec



\# 二进制大文件（ffmpeg不上传源码仓库）

bin/\*.exe



\# 程序运行输出

downloads/

\_build/

\*.log

config.json



\# IDE

.vscode/

.idea/

\*.swp

\*.swo

```



\---



\## ⚖️ 法律与免责声明

> 本项目仅供个人学习、技术研究，仅用于整理你已经获得合法授权的B站内容。

1\. 使用本工具请严格遵守 \*\*B站用户协议\*\* 和国家著作权相关法律法规。

2\. 下载音频版权全部归视频原作者、版权方所有，禁止将下载内容商用、二次分发、公开传播。

3\. 元数据信息来自各个公开第三方接口，会存在错配、缺失情况，以人工核对为准。

4\. Cookie登录能力仅用于本地程序访问接口，程序不会收集、上传你的任何账号信息。

