# -*- coding: utf-8 -*-
"""多源音乐元数据刮削：网易云音乐 / iTunes / MusicBrainz+CoverArtArchive / LRCLIB。

设计原则：
1. 全部使用标准库 urllib（零第三方依赖）。
2. 多源并行尝试，按「歌名+歌手」相似度评分选出最优候选。
3. 任一源失败都不影响其它源，最终返回尽可能完整的字段。
"""
import difflib
import html
import json
import re
import ssl
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


# --------------------------------------------------------------------------
# 基础 HTTP
# --------------------------------------------------------------------------
def http_get(url, headers=None, data=None, timeout=12, encoding=None):
    h = dict(_DEFAULT_HEADERS)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h,
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        raw = r.read()
        if encoding is None:
            encoding = r.headers.get_content_charset() or "utf-8"
            if encoding.lower() in ("gb2312", "gbk"):
                encoding = "gb18030"
        return raw.decode(encoding, "replace") if encoding else raw


def http_json(url, headers=None, data=None, timeout=12):
    txt = http_get(url, headers=headers, data=data, timeout=timeout, encoding="utf-8")
    return json.loads(txt)


def http_bytes(url, headers=None, timeout=20):
    h = dict(_DEFAULT_HEADERS)
    h["Referer"] = "https://music.163.com/"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        ctype = (r.headers.get_content_type() or "image/jpeg").lower()
        return r.read(), ctype


def _norm_mime(mime):
    """把 image/jpg 这类非标准 MIME 归一化为播放器/ID3 认的值。"""
    m = (mime or "").lower()
    if "png" in m:
        return "image/png"
    return "image/jpeg"


# --------------------------------------------------------------------------
# 文本工具
# --------------------------------------------------------------------------
_BRACKET_RE = re.compile(r"[【\[（(]\s*[^】\]）)]*\s*[】\]）)]")
_NOISE_WORDS = [
    "官方", "高清", "完整版", "无损", "MV", "mv", "现场", "live", "Live", "LIVE",
    "翻唱", "翻自", "cover", "COVER", "Cover", "动态歌词", "字幕版", "中文字幕",
    "4K", "1080P", "超清", "原唱", "纯享", "纯享版", "竖屏", "横屏", "完整",
    "演唱会", "MV版", "音频", "合集", "片段", "饭制", "混剪", "伴奏", "消音",
    "哔哩哔哩", "bilibili", "BILIBILI", "A站", "抖音", "TikTok", "tiktok",
]
_QUALITY_TAGS = re.compile(r"(4K|8K|1080P|720P|HDR|60FPS|杜比|Dolby|Hi-Res|flac|FLAC)", re.I)


def strip_noise(text):
    """去掉 B 站标题里的噪声标记，保留核心歌名。"""
    if not text:
        return ""
    t = html.unescape(str(text))
    # 全角转半角（仅标点/字母，保留中文）
    t = t.replace("｜", "|").replace("：", ":").replace("　", " ")
    t = _BRACKET_RE.sub(" ", t)
    t = _QUALITY_TAGS.sub(" ", t)
    for w in _NOISE_WORDS:
        t = t.replace(w, " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^[-–—_|:·,，.、]+|[-–—_|:·,，.、]+$", "", t).strip()
    return t


def norm(text, keep_brackets=False):
    """用于相似度比较的归一化。keep_brackets=True 时保留括号内文字（歌手别名常用）。"""
    if not text:
        return ""
    t = html.unescape(str(text)).lower()
    if keep_brackets:
        t = re.sub(r"[（(【\[]|[）)】\]]", "", t)
    else:
        t = re.sub(r"[（(【\[].*?[）)】\]]", "", t)
    t = re.sub(r"[\s\-–—_·•.,，。!！?？'\"“”‘’()（）\[\]【】/\\|&+:：;；~]", "", t)
    t = t.replace("&", "").replace("feat", "").replace("ft.", "")
    return t.strip()


def similarity(a, b, keep_brackets=False):
    a, b = norm(a, keep_brackets), norm(b, keep_brackets)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85 + 0.15 * (min(len(a), len(b)) / max(len(a), len(b)))
    return difflib.SequenceMatcher(None, a, b).ratio()


def parse_title_artist(raw_title, uploader=""):
    """从 B 站标题/UP 主名里猜测 (歌名, 歌手)。"""
    t = strip_noise(raw_title)
    artist = ""
    title = t
    # 常见格式： 歌手 - 歌名 / 歌手—歌名 / 歌名 - 歌手
    m = re.match(r"^(.*?)\s*[-–—|]\s*(.*)$", t)
    if m:
        left, right = m.group(1).strip(), m.group(2).strip()
        # 《歌名》优先
        book = re.findall(r"《([^》]+)》", t)
        if book:
            title = book[0]
            others = [x for x in (left, right) if x and x != title]
            if others:
                artist = others[0]
        elif left and right:
            # 左侧短 → 更像歌手名
            if 1 <= len(left) <= 12:
                artist, title = left, right
            else:
                title, artist = left, right
    else:
        book = re.findall(r"《([^》]+)》", t)
        if book:
            title = book[0]
    # 「歌名 歌手名」无分隔符时，若歌手出现在标题中则切掉
    up = strip_noise(uploader)
    if not artist and up:
        if norm(up) and norm(up) in norm(title) and len(norm(up)) < len(norm(title)):
            idx = norm(title).find(norm(up))
            title = re.sub(re.escape(up), "", title).strip()
            artist = up
    if not title:
        title = strip_noise(raw_title) or "未知歌曲"
    return title[:120], artist[:120]


def clean_uploader(uploader):
    if not uploader:
        return ""
    u = re.sub(r"^(UP主|up主|作者)\s*:\s*", "", uploader).strip()
    u = u.replace("Official", "").replace("OFFICIAL", "").replace("official", "").strip()
    return u.strip(" -_|.")


# --------------------------------------------------------------------------
# 网易云音乐
# --------------------------------------------------------------------------
_NETEASE_HEADERS = {
    "Referer": "https://music.163.com/",
    "Origin": "https://music.163.com",
    "Cookie": "appver=2.0.2; os=pc;",
}


def netease_search(keyword, limit=8):
    """搜索单曲，返回简化候选列表。"""
    kw = urllib.parse.quote(keyword)
    urls = [
        "https://music.163.com/api/search/get/web?s=%s&type=1&offset=0&limit=%d&total=true" % (kw, limit),
        "https://music.163.com/api/cloudsearch/pc?s=%s&type=1&offset=0&limit=%d" % (kw, limit),
    ]
    songs = []
    for u in urls:
        try:
            data = http_json(u, headers=_NETEASE_HEADERS)
            res = data.get("result") or {}
            songs = res.get("songs") or []
            if songs:
                break
        except Exception:
            continue
    out = []
    for s in songs:
        try:
            artists = " / ".join(a.get("name", "") for a in (s.get("artists") or s.get("ar") or []))
            album = s.get("album") or s.get("al") or {}
            # 搜索结果的 picUrl 才是真实完整地址；仅凭 picId 拼出的 URL 会 404
            pic = album.get("picUrl") or ""
            dur = s.get("duration") or s.get("dt") or 0
            out.append({
                "source": "netease",
                "id": s.get("id"),
                "title": s.get("name", ""),
                "artist": artists,
                "album": album.get("name", ""),
                "album_id": album.get("id"),
                "cover": pic,
                "duration": int(dur / 1000) if dur else 0,
                "alias": " / ".join(s.get("alias") or s.get("alia") or []),
            })
        except Exception:
            continue
    return out


def netease_detail(song_id):
    """歌曲详情：专辑发布时间、曲目号等。"""
    try:
        data = http_json("https://music.163.com/api/song/detail?ids=[%s]" % song_id,
                         headers=_NETEASE_HEADERS)
        s = (data.get("songs") or [{}])[0]
        al = s.get("album") or {}
        ts = al.get("publishTime") or 0
        year = ""
        if ts and ts > 0:
            import datetime
            year = str(datetime.datetime.fromtimestamp(ts / 1000).year)
        return {
            "album": al.get("name", ""),
            "cover": al.get("picUrl", ""),
            "year": year,
            "track": s.get("no") or "",
            "track_total": (al.get("size") or "") if isinstance(al.get("size"), int) else "",
            "isrc": s.get("isrc") or "",
            "duration": int((s.get("duration") or 0) / 1000),
            "artists": " / ".join(a.get("name", "") for a in (s.get("artists") or [])),
            "composer": "",
        }
    except Exception:
        return {}


def netease_lyric(song_id, with_translation=True):
    """返回 (lrc, plain)。"""
    try:
        data = http_json(
            "https://music.163.com/api/song/lyric?id=%s&lv=-1&kv=-1&tv=%d"
            % (song_id, -1 if with_translation else 0),
            headers=_NETEASE_HEADERS,
        )
        lrc = ((data.get("lrc") or {}).get("lyric") or "").strip()
        tlrc = ((data.get("tlyric") or {}).get("lyric") or "").strip()
        if lrc and tlrc and with_translation:
            lrc = _merge_translation(lrc, tlrc)
        plain = _lrc_to_plain(lrc)
        return lrc, plain
    except Exception:
        return "", ""


_TIME_TAG = re.compile(r"\[(\d{1,2}):(\d{1,2}(?:[.:]\d{1,3})?)\]")


def _merge_translation(lrc, tlrc):
    """把翻译按时间戳插到原歌词行下方。"""
    tr = {}
    for line in tlrc.splitlines():
        m = _TIME_TAG.match(line)
        if m:
            key = _tag_key(m)
            text = _TIME_TAG.sub("", line).strip()
            if text:
                tr[key] = text
    out = []
    for line in lrc.splitlines():
        out.append(line)
        m = _TIME_TAG.match(line)
        if m:
            key = _tag_key(m)
            zh = tr.get(key)
            if zh:
                out.append(zh)
    return "\n".join(out)


def _tag_key(m):
    return "%d:%02d" % (int(m.group(1)), int(float(m.group(2).replace(":", "."))))


def _lrc_to_plain(lrc):
    if not lrc:
        return ""
    lines = []
    for line in lrc.splitlines():
        t = _TIME_TAG.sub("", line).strip()
        if not t or re.match(r"^(作词|作曲|编曲|制作|混音|母带|和声|监制|出品|发行|OP|SP|词|曲)\s*[:：]", t):
            if not lines:
                continue
        if t:
            lines.append(t)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# QQ 音乐（中文曲库补充，网易云缺版权的歌这里经常有）
# --------------------------------------------------------------------------
_QQ_HEADERS = {"Referer": "https://y.qq.com/", "User-Agent": UA}
QQ_COVER = "https://y.gtimg.cn/music/photo_new/T002R800x800M000%s.jpg"


def qq_search(keyword, limit=8):
    try:
        url = ("https://c.y.qq.com/soso/fcgi-bin/client_search_cp?p=1&n=%d&w=%s&format=json&t=0"
               % (limit, urllib.parse.quote(keyword)))
        data = http_json(url, headers=_QQ_HEADERS, timeout=12)
        out = []
        for s in ((data.get("data") or {}).get("song") or {}).get("list") or []:
            album_mid = s.get("albummid") or ""
            out.append({
                "source": "qq",
                "id": s.get("songmid") or "",
                "title": s.get("songname") or "",
                "artist": " / ".join(x.get("name", "") for x in (s.get("singer") or [])),
                "album": s.get("albumname") or "",
                "album_id": album_mid,
                "cover": QQ_COVER % album_mid if album_mid else "",
                "duration": int(s.get("interval") or 0),
                "year": "",
            })
        return out
    except Exception:
        return []


def qq_album_info(album_mid, song_mid):
    """专辑详情：发行日期、公司、风格、曲目号。"""
    if not album_mid:
        return {}
    try:
        data = http_json(
            "https://c.y.qq.com/v8/fcg-bin/fcg_v8_album_info_cp.fcg?albummid=%s&format=json"
            % album_mid, headers=_QQ_HEADERS, timeout=12)
        a = data.get("data") or {}
        songs = a.get("list") or []
        track = ""
        for i, s in enumerate(songs, 1):
            if s.get("songmid") == song_mid:
                track = i
                break
        date = a.get("aDate") or ""
        return {
            "album": a.get("name") or "",
            "year": date[:4],
            "date": date,
            "track": track,
            "track_total": len(songs),
            "genre": (a.get("genre") or "").replace("Pop 流行", "流行").strip(),
            "publisher": a.get("company") or "",
            "cover": QQ_COVER % album_mid,
        }
    except Exception:
        return {}


def qq_lyric(song_mid):
    if not song_mid:
        return "", ""
    try:
        txt = http_get(
            "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid=%s&format=json&nobase64=1"
            % song_mid, headers=_QQ_HEADERS, timeout=12)
        data = json.loads(txt)
        lrc = html.unescape(data.get("lyric") or "").strip()
        if not lrc:
            return "", ""
        return lrc, _lrc_to_plain(lrc)
    except Exception:
        return "", ""


# --------------------------------------------------------------------------
# iTunes Search API
# --------------------------------------------------------------------------
_COUNTRY_MAP = [(re.compile(r"[\u4e00-\u9fff]"), "cn")]


def itunes_search(term, limit=6, country=None):
    try:
        if country is None:
            country = "cn" if re.search(r"[\u4e00-\u9fff]", term) else "us"
        url = ("https://itunes.apple.com/search?term=%s&media=music&entity=song&limit=%d&country=%s"
               % (urllib.parse.quote(term), limit, country))
        data = http_json(url, timeout=15)
        out = []
        for r in data.get("results") or []:
            art = (r.get("artworkUrl100") or "").replace("100x100bb", "800x800bb")
            out.append({
                "source": "itunes",
                "id": r.get("trackId"),
                "title": r.get("trackName", ""),
                "artist": r.get("artistName", ""),
                "album": r.get("collectionName", ""),
                "album_id": r.get("collectionId"),
                "cover": art,
                "duration": int((r.get("trackTimeMillis") or 0) / 1000),
                "year": (r.get("releaseDate") or "")[:4],
                "track": r.get("trackNumber"),
                "track_total": r.get("trackCount"),
                "genre": r.get("primaryGenreName", ""),
                "composer": r.get("composerName", ""),
                "isrc": r.get("isrc") or "",
            })
        return out
    except Exception:
        return []


# --------------------------------------------------------------------------
# MusicBrainz + Cover Art Archive
# --------------------------------------------------------------------------
def musicbrainz_search(title, artist="", limit=5):
    try:
        q = 'recording:"%s"' % title.replace('"', "")
        if artist:
            q += ' AND artist:"%s"' % artist.replace('"', "")
        url = ("https://musicbrainz.org/ws/2/recording?query=%s&fmt=json&limit=%d"
               % (urllib.parse.quote(q), limit))
        data = http_json(url, headers={"User-Agent": "BiliMusicTagger/1.0 (local tool)"}, timeout=15)
        out = []
        for r in data.get("recordings") or []:
            ac = " / ".join(a.get("name", "") for a in (r.get("artist-credit") or [])
                            if isinstance(a, dict))
            rel = (r.get("releases") or [{}])[0]
            rg = (rel.get("release-group") or {})
            date = (rel.get("date") or rg.get("first-release-date") or "")
            track_no = ""
            total = ""
            for m in (rel.get("media") or []):
                for t in (m.get("tracks") or []):
                    track_no = t.get("number", "")
                    total = t.get("count", "")
                    break
                break
            out.append({
                "source": "musicbrainz",
                "id": r.get("id"),
                "title": r.get("title", ""),
                "artist": ac,
                "album": rel.get("title", ""),
                "album_id": rel.get("id"),
                "release_group": rg.get("id"),
                "cover": "",
                "duration": int((r.get("length") or 0) / 1000),
                "year": date[:4],
                "date": date,
                "track": track_no,
                "track_total": total,
                "genre": (rg.get("primary-type") or "").lower(),
                "isrc": ((r.get("isrcs") or [""])[0]) if r.get("isrcs") else "",
            })
        return out
    except Exception:
        return []


def coverart_from_mbid(release_id, rg_id=None):
    for mbid in [x for x in (release_id, rg_id) if x]:
        for url in ("https://coverartarchive.org/release/%s/front-500" % mbid,
                    "https://coverartarchive.org/release-group/%s/front-500" % mbid):
            try:
                body, ctype = http_bytes(url, timeout=15)
                if body and len(body) > 2000:
                    return url, ctype
            except Exception:
                continue
    return "", ""


# --------------------------------------------------------------------------
# LRCLIB 歌词兜底
# --------------------------------------------------------------------------
def lrclib_lyrics(title, artist="", album="", duration=0):
    try:
        params = {"track_name": title}
        if artist:
            params["artist_name"] = artist
        if album:
            params["album_name"] = album
        if duration:
            params["duration"] = int(duration)
        url = "https://lrclib.net/api/search?" + urllib.parse.urlencode(params)
        data = http_json(url, headers={"User-Agent": "BiliMusicTagger/1.0"})
        best = None
        for d in data or []:
            synced = d.get("syncedLyrics") or ""
            if synced:
                score = similarity(d.get("trackName", ""), title) + \
                        (similarity(d.get("artistName", ""), artist) if artist else 0)
                if best is None or score > best[0]:
                    best = (score, synced)
        if best and best[0] > 0.4:
            return best[1], lrclib_plain(best[1])
    except Exception:
        pass
    return "", ""


def lrclib_plain(lrc):
    return _lrc_to_plain(lrc)


# --------------------------------------------------------------------------
# 评分与主流程
# --------------------------------------------------------------------------
_COMPILATION_RE = re.compile(
    r"(精选|合辑|合集|金曲|珍藏|纪念|典藏|Playlist|Greatest|Hits|Collection|Anthology|Best\s*of|OST|原声)",
    re.I)


_BAD_VERSION_RE = re.compile(
    r"(伴奏|纯音乐|instrumental|karaoke|remix|dj版|慢摇|铃声|消音|demo|试听版|原唱|翻唱|翻自|cover|模仿|致敬|现场版|live版|\blive\b|演唱会|concert)",
    re.I)


def score_candidate(c, want_title, want_artist, want_duration=0):
    s = similarity(c.get("title"), want_title) * 0.62
    # 用户没要求伴奏/DJ版时，这类版本明显降权
    if _BAD_VERSION_RE.search(str(c.get("title") or "")) and not _BAD_VERSION_RE.search(str(want_title or "")):
        s -= 0.15
    if str(c.get("title") or "").strip().lower() == str(want_title or "").strip().lower():
        s += 0.05
    if want_artist:
        s += similarity(c.get("artist"), want_artist, keep_brackets=True) * 0.33
    else:
        s += 0.10
    # 精选集/合辑里的同名曲目通常不是原始版本，轻微降权
    if c.get("album") and _COMPILATION_RE.search(str(c["album"])):
        s -= 0.07
    if want_duration and c.get("duration"):
        diff = abs(int(c["duration"]) - int(want_duration))
        # 时长只作为辅助信号，避免因视频剪辑版/翻唱版把正确歌曲挤掉
        if diff <= 5:
            s += 0.06
        elif diff <= 15:
            s += 0.02
        elif diff > 45:
            s -= 0.08
    return round(max(0.0, min(1.0, s)), 3)


def scrape(title, artist="", duration=0, album_hint="", want_translation=True,
           sources=("netease", "qq", "itunes", "musicbrainz")):
    """主入口。返回 dict：字段 + cover + lyrics + candidates + source + confidence。"""
    want_title = strip_noise(title) or title
    want_artist = clean_uploader(artist)
    all_cands = []

    if "netease" in sources:
        for kw in _keywords(want_title, want_artist):
            cands = netease_search(kw)
            for c in cands:
                c["score"] = score_candidate(c, want_title, want_artist, duration)
            all_cands += cands
            if cands and max(c["score"] for c in cands) >= 0.72:
                break

    if "qq" in sources:
        for kw in _keywords(want_title, want_artist):
            cands = qq_search(kw)
            for c in cands:
                c["score"] = score_candidate(c, want_title, want_artist, duration)
            all_cands += cands
            if cands and max(c["score"] for c in cands) >= 0.72:
                break

    if "itunes" in sources:
        for kw in _keywords(want_title, want_artist):
            cands = itunes_search(kw)
            for c in cands:
                c["score"] = score_candidate(c, want_title, want_artist, duration)
            all_cands += cands
            if cands and max(c["score"] for c in cands) >= 0.72:
                break

    if "musicbrainz" in sources and (not all_cands or max(c["score"] for c in all_cands) < 0.80):
        cands = musicbrainz_search(want_title, want_artist)
        for c in cands:
            c["score"] = score_candidate(c, want_title, want_artist, duration)
        all_cands += cands

    all_cands.sort(key=lambda x: x.get("score", 0), reverse=True)
    top = all_cands[0] if all_cands else None
    conf = top["score"] if top else 0

    meta = {
        "title": want_title,
        "artist": want_artist,
        "album": album_hint,
        "album_artist": want_artist,
        "year": "",
        "date": "",
        "track": "",
        "track_total": "",
        "genre": "",
        "composer": "",
        "publisher": "",
        "isrc": "",
        "lyrics": "",
        "lyrics_plain": "",
        "cover_bytes": b"",
        "cover_mime": "image/jpeg",
        "cover_url": "",
        "source": "用户输入",
        "confidence": round(conf, 2),
        "candidates": [
            {k: v for k, v in c.items() if k != "score"} | {"score": c.get("score", 0)}
            for c in all_cands[:6]
        ],
    }

    # 采用最高分候选（分数过低时只保留用户输入信息）
    if top and conf >= 0.42:
        meta.update({
            "title": top.get("title") or want_title,
            "artist": top.get("artist") or want_artist,
            "album": top.get("album") or album_hint,
            "album_artist": top.get("artist") or want_artist,
            "year": top.get("year") or "",
            "date": top.get("date") or "",
            "track": str(top.get("track") or ""),
            "track_total": str(top.get("track_total") or ""),
            "genre": top.get("genre") or "",
            "composer": top.get("composer") or "",
            "isrc": top.get("isrc") or "",
            "cover_url": top.get("cover") or "",
            "source": {"netease": "网易云音乐", "qq": "QQ音乐", "itunes": "iTunes",
                       "musicbrainz": "MusicBrainz"}.get(top.get("source"), top.get("source", "")),
        })
        # 网易云补全专辑年份/曲序
        if top.get("source") == "netease" and top.get("id"):
            d = netease_detail(top["id"])
            meta["album"] = d.get("album") or meta["album"]
            meta["year"] = d.get("year") or meta["year"]
            meta["date"] = meta["date"] or meta["year"]
            meta["track"] = str(d.get("track") or meta["track"] or "")
            meta["track_total"] = str(d.get("track_total") or meta["track_total"] or "")
            meta["isrc"] = d.get("isrc") or meta["isrc"]
            # 详情接口的 picUrl 才带真实 hash 路径，优先使用
            meta["cover_url"] = d.get("cover") or meta["cover_url"]
        # QQ 音乐补全专辑年份/曲序/风格/发行公司
        if top.get("source") == "qq" and top.get("id"):
            d = qq_album_info(top.get("album_id"), top["id"])
            meta["album"] = d.get("album") or meta["album"]
            meta["year"] = d.get("year") or meta["year"]
            meta["date"] = d.get("date") or meta["year"]
            meta["track"] = str(d.get("track") or meta["track"] or "")
            meta["track_total"] = str(d.get("track_total") or meta["track_total"] or "")
            meta["genre"] = d.get("genre") or meta["genre"]
            meta["publisher"] = d.get("publisher") or meta["publisher"]
            meta["cover_url"] = d.get("cover") or meta["cover_url"]

    # 网易云不提供风格，用 iTunes 补一个
    if not meta["genre"] and meta["title"]:
        for kw in _keywords(meta["title"], meta["artist"]):
            for c in itunes_search(kw, limit=3):
                if score_candidate(c, meta["title"], meta["artist"]) >= 0.7 and c.get("genre"):
                    meta["genre"] = c["genre"]
                    if not meta["composer"] and c.get("composer"):
                        meta["composer"] = c["composer"]
                    break
            if meta["genre"]:
                break

    # 封面
    cover_url = meta["cover_url"]
    if cover_url:
        if "music.126.net" in cover_url and "param=" not in cover_url:
            cover_url = cover_url + "?param=800y800"
        try:
            hdr = {"Referer": "https://y.qq.com/"} if "gtimg" in cover_url else None
            body, ctype = http_bytes(cover_url, headers=hdr)
            if len(body) > 2000:
                meta["cover_bytes"] = body
                meta["cover_mime"] = _norm_mime(ctype)
        except Exception:
            pass
    if not meta["cover_bytes"] and top and top.get("source") == "musicbrainz":
        u, ct = coverart_from_mbid(top.get("album_id"), top.get("release_group"))
        if u:
            try:
                body, ctype = http_bytes(u)
                meta["cover_bytes"] = body
                meta["cover_mime"] = _norm_mime(ctype)
                meta["cover_url"] = u
            except Exception:
                pass

    # 歌词：网易云 / QQ 音乐 → LRCLIB
    if top and top.get("source") == "netease" and top.get("id"):
        lrc, plain = netease_lyric(top["id"], want_translation)
        if lrc:
            meta["lyrics"], meta["lyrics_plain"] = lrc, plain
    if not meta["lyrics"] and top and top.get("source") == "qq" and top.get("id"):
        lrc, plain = qq_lyric(top["id"])
        if lrc:
            meta["lyrics"], meta["lyrics_plain"] = lrc, plain
    if not meta["lyrics"]:
        lrc, plain = lrclib_lyrics(meta["title"], meta["artist"], meta.get("album", ""),
                                   duration or (top or {}).get("duration", 0))
        if lrc:
            meta["lyrics"], meta["lyrics_plain"] = lrc, plain

    if not meta["lyrics"] and not meta["cover_bytes"] and conf < 0.42:
        meta["source"] = "未匹配（仅用输入信息）"
    return meta


def _keywords(title, artist):
    kws = []
    if title and artist:
        kws.append("%s %s" % (title, artist))
        kws.append("%s %s" % (artist, title))
    if title:
        kws.append(title)
    if artist and not title:
        kws.append(artist)
    # 去重
    seen, out = set(), []
    for k in kws:
        k = re.sub(r"\s+", " ", k).strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out[:3]


def fetch_cover_bytes(url):
    if not url:
        return b"", "image/jpeg"
    if "music.126.net" in url and "param=" not in url:
        url += "?param=800y800"
    return http_bytes(url)
