# -*- coding: utf-8 -*-
"""用 mutagen 把元数据 / 封面 / 歌词写进音频标签。

支持 mp3 / wav（ID3v2.3）、flac / ogg / opus（Vorbis Comment）、m4a（MP4 原子）。
"""
import base64
import os
import re

from mutagen import File as MutagenFile
from mutagen.id3 import (
    ID3, ID3NoHeaderError, APIC, TIT2, TPE1, TPE2, TALB, TDRC, TRCK, TPOS,
    TCON, TCOM, TPUB, TCOP, TSSE, COMM, USLT, TXXX, PictureType,
)
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

SINGLE_FIELDS = {
    "title": TIT2,
    "artist": TPE1,
    "album": TALB,
    "year": TDRC,
    "track": TRCK,
    "genre": TCON,
    "composer": TCOM,
    "publisher": TPUB,
    "album_artist": TPE2,
}

# 导出格式：前端可选的全部格式 → (文件扩展名, 说明)
FORMATS = {
    "mp3": (".mp3", "MP3（兼容性最好）"),
    "m4a": (".m4a", "M4A / AAC（苹果设备友好）"),
    "wav": (".wav", "WAV（无损、体积大）"),
    "flac": (".flac", "FLAC（无损压缩）"),
    "ogg": (".ogg", "OGG / Vorbis（体积小）"),
}
DEFAULT_FORMAT = "mp3"

_LOSSY_QUALITY_FORMATS = ("mp3", "m4a", "ogg")


def format_ext(fmt):
    return FORMATS.get((fmt or DEFAULT_FORMAT).lower(), FORMATS[DEFAULT_FORMAT])[0]


def fmt_of_path(path):
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext in ("m4a", "mp4", "alac"):
        return "m4a"
    if ext == "opus":
        return "ogg"
    return ext if ext in FORMATS else DEFAULT_FORMAT


def _safe(text):
    if text is None:
        return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(text)).strip()


def sanitize_filename(name, maxlen=120):
    name = (name or "").replace("/", ", ").replace("\\", ", ")
    name = re.sub(r'[:*?"<>|\r\n\t]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "未命名"
    if len(name) > maxlen:
        stem, ext = os.path.splitext(name)
        name = stem[:maxlen - len(ext)] + ext
    return name


def build_filename(meta, template="{artist} - {title}", fmt=DEFAULT_FORMAT):
    fields = {
        "artist": _safe(meta.get("artist")) or "未知歌手",
        "title": _safe(meta.get("title")) or "未知歌曲",
        "album": _safe(meta.get("album")) or "",
        "year": _safe(meta.get("year")) or "",
        "track": _safe(meta.get("track")) or "",
        "source": _safe(meta.get("source")) or "",
    }
    try:
        out = template.format(**fields)
    except Exception:
        out = "%s - %s" % (fields["artist"], fields["title"])
    out = re.sub(r"\s*-\s*-\s*", " - ", out)
    out = out.strip(" -_.")
    return sanitize_filename(out) + format_ext(fmt)


# ---------------------------------------------------------------- 共用
def _note(meta):
    note = "由 BiliMusic 从 B 站视频提取音频并自动刮削元数据"
    if meta.get("source"):
        note += "；元数据来源：%s" % meta["source"]
    return note


def _lyric_text(meta):
    text = meta.get("lyrics") or meta.get("lyrics_plain") or ""
    return text.replace("\r\n", "\n").replace("\r", "\n") if text else ""


def _cover_mime(meta):
    mime = meta.get("cover_mime") or "image/jpeg"
    return "image/png" if "png" in mime else "image/jpeg"


def _track_str(meta):
    track = _safe(meta.get("track"))
    total = _safe(meta.get("track_total"))
    if not track.isdigit():
        return ""
    return "%s/%s" % (track, total) if total.isdigit() else track


def _vorbis_fields(meta, embed_lyrics, note):
    fields = {
        "title": _safe(meta.get("title")),
        "artist": _safe(meta.get("artist")),
        "album": _safe(meta.get("album")),
        "albumartist": _safe(meta.get("album_artist") or meta.get("artist")),
        "genre": _safe(meta.get("genre")),
        "composer": _safe(meta.get("composer")),
        "publisher": _safe(meta.get("publisher")),
        "date": _safe(meta.get("date")) if re.match(
            r"^\d{4}-\d{2}-\d{2}$", _safe(meta.get("date")) or "") else _safe(meta.get("year")),
        "tracknumber": _track_str(meta),
        "tracktotal": _safe(meta.get("track_total")),
        "comment": note,
        "encoder": "BiliMusic Tagger (yt-dlp + mutagen + FFmpeg)",
    }
    if meta.get("isrc"):
        fields["isrc"] = _safe(meta["isrc"])
    if meta.get("source"):
        fields["tag_source"] = _safe(meta["source"])
    if meta.get("confidence") is not None:
        fields["match_confidence"] = str(meta.get("confidence"))
    if meta.get("video_url"):
        fields["source_url"] = _safe(meta["video_url"])
    if embed_lyrics:
        ly = _lyric_text(meta)
        if ly:
            fields["lyrics"] = ly
    return {k: v for k, v in fields.items() if v}


# ---------------------------------------------------------------- ID3（mp3 / wav）
_ID3_CLEAR_PREFIX = ("TIT2", "TPE1", "TPE2", "TALB", "TDRC", "TRCK", "TPOS",
                     "TCON", "TCOM", "TPUB", "TCOP", "USLT", "APIC", "COMM",
                     "TXXX:", "TDES", "TOAL", "TOPE")


def _fill_id3(tags, meta, embed_lyrics=True, embed_cover=True, lyric_lang="chi"):
    for key in list(tags.keys()):
        if key.startswith(_ID3_CLEAR_PREFIX):
            try:
                del tags[key]
            except Exception:
                pass

    def add_text(frame_cls, value):
        v = _safe(value)
        if v:
            tags.add(frame_cls(encoding=3, text=[v]))

    add_text(TIT2, meta.get("title"))
    add_text(TPE1, meta.get("artist"))
    add_text(TALB, meta.get("album"))
    add_text(TCON, meta.get("genre"))
    add_text(TCOM, meta.get("composer"))
    add_text(TPUB, meta.get("publisher"))
    add_text(TPE2, meta.get("album_artist") or meta.get("artist"))
    add_text(TSSE, "BiliMusic Tagger (yt-dlp + mutagen + FFmpeg)")

    year = _safe(meta.get("year"))
    date = _safe(meta.get("date"))
    if date and re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        tags.add(TDRC(encoding=3, text=[date]))
    elif year:
        tags.add(TDRC(encoding=3, text=[year]))

    trk = _track_str(meta)
    if trk:
        tags.add(TRCK(encoding=3, text=[trk]))
    if _safe(meta.get("album")):
        tags.add(TPOS(encoding=3, text=["1/1"]))

    if meta.get("isrc"):
        tags.add(TXXX(encoding=3, desc="ISRC", text=[_safe(meta["isrc"])]))
    if meta.get("source"):
        tags.add(TXXX(encoding=3, desc="TAG_SOURCE", text=[_safe(meta["source"])]))
    if meta.get("confidence") is not None:
        tags.add(TXXX(encoding=3, desc="MATCH_CONFIDENCE",
                      text=[str(meta.get("confidence"))]))
    if meta.get("video_url"):
        tags.add(TXXX(encoding=3, desc="SOURCE_URL", text=[_safe(meta["video_url"])]))

    tags.add(COMM(encoding=3, lang="chi", desc="", text=[_note(meta)]))

    if embed_cover and meta.get("cover_bytes"):
        tags.add(APIC(encoding=3, mime=_cover_mime(meta), type=PictureType.COVER_FRONT,
                      desc="Cover", data=meta["cover_bytes"]))
    if embed_lyrics:
        ly = _lyric_text(meta)
        if ly:
            tags.add(USLT(encoding=3, lang=lyric_lang, desc="", text=ly))
    return tags


def _write_id3(path, meta, embed_lyrics, embed_cover, lyric_lang):
    fmt = fmt_of_path(path)
    if fmt == "wav":
        audio = WAVE(path)
        if audio.tags is None:
            audio.add_tags()
        _fill_id3(audio.tags, meta, embed_lyrics, embed_cover, lyric_lang)
        audio.save()
    else:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        _fill_id3(tags, meta, embed_lyrics, embed_cover, lyric_lang)
        tags.update_to_v23()
        tags.save(path, v2_version=3)


# ---------------------------------------------------------------- Vorbis（flac / ogg / opus）
def _write_vorbis(path, meta, embed_lyrics, embed_cover):
    fmt = fmt_of_path(path)
    if fmt == "flac":
        audio = FLAC(path)
    elif path.lower().endswith(".opus"):
        audio = OggOpus(path)
    else:
        audio = OggVorbis(path)
    if audio.tags is None:
        audio.add_tags()
    for key in list(audio.tags.keys()):
        try:
            del audio.tags[key]
        except Exception:
            pass
    for k, v in _vorbis_fields(meta, embed_lyrics, _note(meta)).items():
        audio[k] = [v]

    if embed_cover and meta.get("cover_bytes"):
        pic = Picture()
        pic.type = 3  # front cover
        pic.mime = _cover_mime(meta)
        pic.desc = "Cover"
        pic.data = meta["cover_bytes"]
        if fmt == "flac":
            audio.clear_pictures()
            audio.add_picture(pic)
        else:
            audio["metadata_block_picture"] = [
                base64.b64encode(pic.write()).decode("ascii")]
    audio.save()


# ---------------------------------------------------------------- MP4（m4a）
_MP4_MAP = {
    "title": "\u00a9nam",
    "artist": "\u00a9ART",
    "album": "\u00a9alb",
    "year": "\u00a9day",
    "genre": "\u00a9gen",
    "composer": "\u00a9wrt",
    "album_artist": "aART",
    "encoder": "\u00a9too",
    "comment": "\u00a9cmt",
    "lyrics": "\u00a9lyr",
}


def _write_mp4(path, meta, embed_lyrics, embed_cover):
    audio = MP4(path)
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    for key in list(tags.keys()):
        if key in _MP4_MAP.values() or key in ("trkn", "covr", "disk") or key.startswith("----:"):
            del tags[key]

    def put(name, value):
        v = _safe(value)
        if v:
            tags[_MP4_MAP[name]] = [v]

    put("title", meta.get("title"))
    put("artist", meta.get("artist"))
    put("album", meta.get("album"))
    put("genre", meta.get("genre"))
    put("composer", meta.get("composer"))
    put("album_artist", meta.get("album_artist") or meta.get("artist"))
    put("encoder", "BiliMusic Tagger (yt-dlp + mutagen + FFmpeg)")
    put("comment", _note(meta))
    date = _safe(meta.get("date"))
    put("year", date if re.match(r"^\d{4}-\d{2}-\d{2}$", date or "") else _safe(meta.get("year")))

    track = _safe(meta.get("track"))
    total = _safe(meta.get("track_total"))
    if track.isdigit():
        tags["trkn"] = [(int(track), int(total) if total.isdigit() else 0)]
        tags["disk"] = [(1, 1)]

    for atom_name, meta_key in (("ISRC", "isrc"), ("TAG_SOURCE", "source"),
                                ("MATCH_CONFIDENCE", "confidence"),
                                ("SOURCE_URL", "video_url")):
        val = meta.get(meta_key)
        if val:
            tags["----:com.apple.iTunes:" + atom_name] = [str(val).encode("utf-8")]

    if embed_cover and meta.get("cover_bytes"):
        fmt_flag = (MP4Cover.FORMAT_PNG if _cover_mime(meta) == "image/png"
                    else MP4Cover.FORMAT_JPEG)
        tags["covr"] = [MP4Cover(meta["cover_bytes"], imageformat=fmt_flag)]
    if embed_lyrics:
        ly = _lyric_text(meta)
        if ly:
            tags["\u00a9lyr"] = [ly]
    audio.save()


# ---------------------------------------------------------------- 对外接口
def write_tags(path, meta, embed_lyrics=True, embed_cover=True, lyric_lang="chi"):
    """把 meta 写进音频文件（按扩展名自动选标签格式）。返回写入结果统计。"""
    fmt = fmt_of_path(path)
    if fmt in ("mp3", "wav"):
        _write_id3(path, meta, embed_lyrics, embed_cover, lyric_lang)
    elif fmt in ("flac", "ogg"):
        _write_vorbis(path, meta, embed_lyrics, embed_cover)
    elif fmt == "m4a":
        _write_mp4(path, meta, embed_lyrics, embed_cover)
    else:
        raise RuntimeError("不支持的音频格式：%s" % os.path.splitext(path)[1])

    audio = MutagenFile(path)
    info = getattr(audio, "info", None)
    duration = round(float(getattr(info, "length", 0) or 0), 2)
    bitrate = int(getattr(info, "bitrate", 0) or 0)
    tags = read_tags(path)
    return {
        "size": os.path.getsize(path),
        "duration": duration,
        "bitrate": bitrate,
        "has_cover": bool(tags.get("cover_bytes")),
        "has_lyrics": bool(tags.get("lyrics_text")),
        "format": fmt,
    }


def read_tags(path):
    """按格式读取标签，返回统一结构（含 cover_bytes / lyrics_text）。"""
    out = {
        "title": "", "artist": "", "album": "", "year": "", "track": "",
        "genre": "", "duration": 0, "bitrate": 0, "cover": False, "lyrics": False,
    }
    if not path or not os.path.isfile(path):
        return out
    fmt = fmt_of_path(path)
    try:
        if fmt == "mp3":
            audio = MP3(path)
            tags = audio.tags
            info = audio.info
            if tags is not None:
                for k, field in (("TIT2", "title"), ("TPE1", "artist"),
                                 ("TALB", "album"), ("TDRC", "year"),
                                 ("TRCK", "track"), ("TCON", "genre")):
                    out[field] = str(tags.get(k, "") or "")
                apic = tags.getall("APIC")
                if apic:
                    out["cover_bytes"] = apic[0].data
                    out["cover_mime"] = apic[0].mime
                uslt = tags.getall("USLT")
                if uslt:
                    out["lyrics_text"] = uslt[0].text
        elif fmt == "wav":
            audio = WAVE(path)
            tags = audio.tags
            info = audio.info
            if tags is not None:
                for k, field in (("TIT2", "title"), ("TPE1", "artist"),
                                 ("TALB", "album"), ("TDRC", "year"),
                                 ("TRCK", "track"), ("TCON", "genre")):
                    out[field] = str(tags.get(k, "") or "")
                apic = tags.getall("APIC")
                if apic:
                    out["cover_bytes"] = apic[0].data
                    out["cover_mime"] = apic[0].mime
                uslt = tags.getall("USLT")
                if uslt:
                    out["lyrics_text"] = uslt[0].text
        elif fmt in ("flac", "ogg"):
            if path.lower().endswith(".opus"):
                audio = OggOpus(path)
            elif path.lower().endswith(".flac"):
                audio = FLAC(path)
            else:
                audio = OggVorbis(path)
            info = audio.info
            tags = audio.tags or {}
            for key, field in (("title", "title"), ("artist", "artist"),
                               ("album", "album"), ("date", "year"),
                               ("tracknumber", "track"), ("genre", "genre")):
                v = tags.get(key)
                out[field] = str(v[0]) if v else ""
            if fmt == "flac" and audio.pictures:
                pic = audio.pictures[0]
                out["cover_bytes"] = pic.data
                out["cover_mime"] = pic.mime
            else:
                b64 = tags.get("metadata_block_picture")
                if b64:
                    try:
                        pic = Picture(base64.b64decode(b64[0]))
                        out["cover_bytes"] = pic.data
                        out["cover_mime"] = pic.mime
                    except Exception:
                        pass
            ly = tags.get("lyrics")
            if ly:
                out["lyrics_text"] = "\n".join(ly)
        elif fmt == "m4a":
            audio = MP4(path)
            info = audio.info
            tags = audio.tags or {}
            for key, field in (("\u00a9nam", "title"), ("\u00a9ART", "artist"),
                               ("\u00a9alb", "album"), ("\u00a9day", "year"),
                               ("\u00a9gen", "genre")):
                v = tags.get(key)
                out[field] = str(v[0]) if v else ""
            trk = tags.get("trkn")
            if trk:
                out["track"] = str(trk[0][0]) if trk[0][0] else ""
            covr = tags.get("covr")
            if covr:
                out["cover_bytes"] = bytes(covr[0])
                out["cover_mime"] = ("image/png" if covr[0].imageformat == MP4Cover.FORMAT_PNG
                                     else "image/jpeg")
            ly = tags.get("\u00a9lyr")
            if ly:
                out["lyrics_text"] = str(ly[0])
    except Exception:
        return out
    out["duration"] = round(float(getattr(info, "length", 0) or 0), 2)
    out["bitrate"] = int(getattr(info, "bitrate", 0) or 0)
    out["cover"] = bool(out.get("cover_bytes"))
    out["lyrics"] = bool(out.get("lyrics_text"))
    return out
