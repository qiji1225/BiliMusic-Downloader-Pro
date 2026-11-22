/* BiliMusic 前端逻辑（纯原生 JS，无外部依赖） */
(function () {
  "use strict";

  // 把脚本异常显示在页面上，避免只留下白屏
  window.addEventListener("error", function (e) {
    var box = document.getElementById("toasts");
    if (!box) return;
    var d = document.createElement("div");
    d.className = "toast err";
    d.textContent = "脚本错误：" + (e.message || e.error) + " (行 " + (e.lineno || "?") + ")";
    box.appendChild(d);
  });

  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));

  let uidSeq = 0;

  const state = {
    rows: [],
    jobRows: [],
    jobId: null,
    timer: null,
    jobStatus: null,
    editingIdx: -1,
    cfg: {},
    bili: null,
    lastSnapshot: null,
    fav: { folders: [], mediaId: null, title: "", items: [], page: 1, hasMore: false, sel: new Set() },
  };

  const LS_ROWS = "bilimusic_rows_v1";
  const LS_FAV_MEDIA = "bilimusic_fav_media_v1";

  /* ----------------------------- 工具 ----------------------------- */
  function toast(msg, type) {
    const box = $("#toasts");
    const el = document.createElement("div");
    el.className = "toast " + (type || "");
    el.textContent = msg;
    box.appendChild(el);
    setTimeout(() => {
      el.style.transition = "opacity .3s";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 320);
    }, type === "err" ? 5200 : 2800);
  }

  function fmtSize(bytes) {
    if (!bytes) return "";
    if (bytes > 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
    return Math.round(bytes / 1024) + " KB";
  }

  function fmtDuration(sec) {
    if (!sec) return "";
    const m = Math.floor(sec / 60);
    const s = Math.round(sec % 60);
    return m + ":" + String(s).padStart(2, "0");
  }

  async function api(path, body) {    const opt = body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    };
    const res = await fetch(path, opt);
    const ct = res.headers.get("content-type") || "";
    const data = ct.includes("json") ? await res.json() : await res.text();
    if (!res.ok) throw new Error((data && data.error) || ("HTTP " + res.status));
    return data;
  }

  function debounce(fn, wait) {
    let t = null;
    return function () {
      const args = arguments;
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), wait || 400);
    };
  }

  // 歌曲列表草稿：刷新页面后自动恢复
  const saveDraft = debounce(function () {
    try {
      const keep = state.rows.filter((r) => (r.url || "").trim() || (r.title || "").trim());
      localStorage.setItem(LS_ROWS, JSON.stringify(keep.slice(0, 500)));
    } catch (e) { /* 隐私模式下忽略 */ }
  }, 500);

  function loadDraft() {
    try {
      const raw = localStorage.getItem(LS_ROWS);
      if (!raw) return [];
      const arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr.filter((r) => r && (r.url || r.title)) : [];
    } catch (e) { return []; }
  }

  /* ----------------------------- 主题切换 ----------------------------- */
  const THEME_ORDER = ["auto", "light", "dark"];
  const THEME_ICONS = {
    auto: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="2.5" y="4" width="19" height="13" rx="2.5"/><path d="M8.5 20.5h7" stroke-linecap="round"/><path d="M12 17v3.5" stroke-linecap="round"/></svg>',
    light: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.6v2.4M12 19v2.4M2.6 12h2.4M19 12h2.4M5.4 5.4l1.7 1.7M16.9 16.9l1.7 1.7M18.6 5.4l-1.7 1.7M7.1 16.9l-1.7 1.7" stroke-linecap="round"/></svg>',
    dark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M20 14.4A8.2 8.2 0 1 1 9.6 4a6.5 6.5 0 0 0 10.4 10.4z" stroke-linecap="round"/></svg>',
  };
  const THEME_TIPS = {
    auto: "主题：跟随系统（点一次切到亮色）",
    light: "主题：亮色（点一次切到暗色）",
    dark: "主题：暗色（点一次切回跟随系统）",
  };

  function currentThemeMode() {
    return document.documentElement.getAttribute("data-theme-mode") || "auto";
  }

  function resolveTheme(mode) {
    if (mode === "light" || mode === "dark") return mode;
    const light = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
    return light ? "light" : "dark";
  }

  function paintThemeIcon(mode) {
    const el = $("#themeIcon");
    if (!el) return;
    el.innerHTML = THEME_ICONS[mode] || THEME_ICONS.auto;
    const btn = $("#btnTheme");
    if (btn) btn.title = THEME_TIPS[mode] || THEME_TIPS.auto;
  }

  function applyTheme(mode, save) {
    const m = THEME_ORDER.indexOf(mode) >= 0 ? mode : "auto";
    document.documentElement.setAttribute("data-theme-mode", m);
    document.documentElement.setAttribute("data-theme", resolveTheme(m));
    paintThemeIcon(m);
    if (save) {
      try { localStorage.setItem("bilimusic_theme", m); } catch (e) { /* ignore */ }
    }
  }

  function cycleTheme() {
    const cur = currentThemeMode();
    const next = THEME_ORDER[(THEME_ORDER.indexOf(cur) + 1) % THEME_ORDER.length];
    applyTheme(next, true);
    toast("主题：" + { auto: "跟随系统", light: "亮色", dark: "暗色" }[next]);
  }

  /* ----------------------------- 行渲染 ----------------------------- */
  function mkRow(data) {
    return {
      uid: ++uidSeq,
      url: (data && data.url) || "",
      title: (data && data.title) || "",
      artist: (data && data.artist) || "",
      result: null,
    };
  }

  function addRow(data) {
    state.rows.push(mkRow(data));
    renderRows();
    saveDraft();
    return state.rows.length - 1;
  }

  function renderRows() {
    const wrap = $("#rows");
    wrap.innerHTML = "";
    state.rows.forEach((r, i) => {
      const el = document.createElement("div");
      el.className = "row";
      el.dataset.i = i;
      el.dataset.uid = r.uid;
      el.innerHTML = `
        <div class="idx">${i + 1}</div>
        <input type="text" class="url" spellcheck="false" placeholder="https://www.bilibili.com/video/BV..." value="${esc(r.url)}">
        <input type="text" class="title" placeholder="留空自动识别" value="${esc(r.title)}">
        <input type="text" class="artist" placeholder="留空自动识别" value="${esc(r.artist)}">
        <div class="status-cell"><span class="badge-status">待处理</span></div>
        <button class="row-del" title="删除这一行">×</button>
        <div class="row-extra"></div>`;
      wrap.appendChild(el);

      el.querySelector(".url").addEventListener("input", (e) => { state.rows[i].url = e.target.value; saveDraft(); });
      el.querySelector(".title").addEventListener("input", (e) => { state.rows[i].title = e.target.value; saveDraft(); });
      el.querySelector(".artist").addEventListener("input", (e) => { state.rows[i].artist = e.target.value; saveDraft(); });
      el.querySelector(".row-del").addEventListener("click", () => {
        if (state.jobId && state.jobStatus === "running") return toast("任务运行中，暂不能删除", "err");
        state.rows.splice(i, 1);
        renderRows();
        saveDraft();
      });
      el.querySelector(".url").addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          if (i === state.rows.length - 1) addRow({});
          else el.parentElement.children[i + 1].querySelector(".url").focus();
        }
      });

      // 这一行自己有结果就画出来；没有就保持「待处理」，并挂上悬停即可点「立即处理」
      paintItemRow(el, r.result, r.uid);
    });
    updateCount();
  }

  function updateCount() {
    const n = state.rows.length;
    $("#rowCount").textContent = n + " 条";
    $("#emptyState").classList.toggle("hide", n > 0);
  }

  function rowEl(i) {
    return $('#rows .row[data-i="' + i + '"]');
  }

  /* ----------------------------- 任务渲染 ----------------------------- */
  // 画一行的状态 + 结果。it 为 null 表示这条还没处理过
  function paintItemRow(el, it, uid) {
    const cell = el.querySelector(".status-cell");
    const extra = el.querySelector(".row-extra");
    if (!cell || !extra) return;

    if (!it) {
      cell.innerHTML = '<span class="badge-status">待处理</span>' +
        '<button class="row-go" type="button" title="只处理这一条">▶ 立即处理</button>';
      const go = cell.querySelector(".row-go");
      if (go) {
        go.addEventListener("click", () => runOne(uid));
        // 鼠标移入/移出切换 class（不依赖纯 CSS :hover，触屏和自动化都更稳）
        cell.addEventListener("mouseenter", () => cell.classList.add("show-go"));
        cell.addEventListener("mouseleave", () => cell.classList.remove("show-go"));
      }
      extra.innerHTML = "";
      extra.dataset.for = "";
      return;
    }

    const st = it.status;
    const label = { pending: "排队中", running: "处理中", done: "完成", error: "失败", skipped: "已取消" }[st] || st;
    const cls = st === "done" ? "done" : st === "error" ? "error" : st === "running" ? "running spin" : "";
    cell.innerHTML = '<span class="badge-status ' + cls + '">' + label + "</span>";

    if (st === "running" || st === "pending") {
      extra.innerHTML = `
        <div class="row-progress">
          <div class="bar"><i style="width:${it.percent || 0}%"></i></div>
          <div class="meta-line">
            <span>${esc(it.stage || "准备中")}</span>
            <span>${it.percent ? it.percent + "%" : ""}</span>
            <span>${esc(it.speed || "")}</span>
          </div>
        </div>`;
      return;
    }
    if (st === "error") {
      extra.innerHTML = `<div class="error-box">⚠ ${esc(it.error || "未知错误")}</div>`;
      return;
    }
    if (st !== "done") { extra.innerHTML = ""; return; }

    const m = it.meta || {};
    const key = state.jobId + "/" + it.idx;
    if (extra.dataset.for !== key) {
      extra.dataset.for = key;
      const tags = [];
      if (m.album) tags.push(`<span class="tag">专辑 ${esc(m.album)}</span>`);
      if (m.year) tags.push(`<span class="tag">${esc(m.year)}</span>`);
      if (m.genre) tags.push(`<span class="tag">${esc(m.genre)}</span>`);
      if (m.has_cover) tags.push(`<span class="tag ok">封面已写入</span>`);
      if (m.has_lyrics) tags.push(`<span class="tag ok">歌词已内嵌</span>`);
      else tags.push(`<span class="tag warn">无歌词</span>`);
      tags.push(`<span class="tag">${esc(m.source || "")} · ${(m.confidence || 0).toFixed ? (m.confidence || 0).toFixed(2) : m.confidence}</span>`);
      extra.innerHTML = `
        <div class="result">
          <img class="cover" src="${it.cover}?t=${Date.now()}" alt="封面" onerror="this.style.display='none'">
          <div class="info">
            <div class="t">${esc(m.title || it.title_in)}</div>
            <div class="a">${esc(m.artist || "")} · ${esc(it.filename)} · ${fmtSize(it.filesize)} · ${fmtDuration(it.duration)}${it.bitrate ? " · " + Math.round(it.bitrate / 1000) + "kbps" : ""}</div>
            <div class="tags">${tags.join("")}</div>
          </div>
          <div class="acts">
            <a class="btn sm primary" href="/api/file/${state.jobId}/${it.idx}" download>下载</a>
            <button class="btn sm ghost" data-edit="${it.idx}">编辑标签</button>
            <a class="link" href="${esc(it.url)}" target="_blank" rel="noreferrer">查看原视频</a>
          </div>
        </div>`;
      const editBtn = extra.querySelector("[data-edit]");
      if (editBtn) editBtn.addEventListener("click", () => openEdit(it.idx));
      const img = extra.querySelector(".cover");
      if (img) img.addEventListener("error", () => { img.remove(); });
    }
  }

  function paint(snap) {
    state.lastSnapshot = snap;
    state.jobStatus = snap.status;
    const overallWrap = $("#overallWrap");
    if (snap.status === "running" || snap.finished > 0) {
      overallWrap.hidden = false;
      $("#overallBar").style.width = snap.overall + "%";
      $("#overallText").textContent = snap.finished + " / " + snap.total + " · " + snap.overall + "%";
    }
    const running = snap.status === "running";
    $("#btnStart").disabled = running;
    $("#btnStart").style.display = running ? "none" : "";
    $("#btnCancel").hidden = !running;
    $("#runHint").textContent = running
      ? "正在处理…（" + (snap.elapsed || 0) + "s）"
      : (snap.status === "cancelled" ? "已停止" : "处理完成");

    let okCount = 0;
    snap.items.forEach((it) => {
      if (it.status === "done") okCount++;
      // 用 uid 反查当前行号：即使中途删过行，也不会把结果画到别的行上
      const uid = state.jobRows[it.idx];
      let rowIdx = uid ? state.rows.findIndex((r) => r.uid === uid) : -1;
      if (rowIdx < 0 && !uid) rowIdx = state.rows[it.idx] ? it.idx : -1;
      if (rowIdx < 0) return;
      const row = state.rows[rowIdx];
      row.result = it;
      const el = rowEl(rowIdx);
      if (!el) return;
      paintItemRow(el, it, row.uid);
    });

    if (snap.status === "done") {
      overallWrap.hidden = false;
      $("#btnZip").hidden = okCount === 0;
      $("#btnCancel").hidden = true;
      $("#runHint").textContent = "完成：成功 " + okCount + " 条 / 共 " + snap.total + " 条";
    }
    renderLogs(snap.logs || []);
  }

  function renderLogs(logs) {
    if (!logs.length) return;
    $("#logPanel").hidden = false;
    const box = $("#logBox");
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box.innerHTML = logs.map((l) =>
      `<div class="l ${l.level}"><span class="t">${l.t.toFixed(1)}s</span><span class="m">${esc(l.msg)}</span></div>`
    ).join("");
    if (atBottom) box.scrollTop = box.scrollHeight;
  }

  /* ----------------------------- 开始 / 轮询 ----------------------------- */
  function collectOptions() {
    return {
      format: $("#cfgFormat").value || "mp3",
      quality: $("#cfgQuality").value,
      filename_template: $("#cfgTemplate").value || "{artist} - {title}",
      out_dir: $("#cfgOutDir").value || "",
      concurrency: parseInt($("#cfgConcurrency").value, 10) || 1,
      embed_cover: $("#cfgCover").checked,
      embed_lyrics: $("#cfgLyrics").checked,
      translate_lyrics: $("#cfgTranslate").checked,
      sources: [
        $("#srcNetease").checked ? "netease" : null,
        $("#srcQQ").checked ? "qq" : null,
        $("#srcItunes").checked ? "itunes" : null,
        $("#srcMb").checked ? "musicbrainz" : null,
      ].filter(Boolean),
    };
  }

  async function start() {
    const rows = state.rows
      .map((r, i) => ({ idx: i, url: (r.url || "").trim(), title: (r.title || "").trim(), artist: (r.artist || "").trim() }))
      .filter((r) => r.url);
    if (!rows.length) return toast("请先填写至少一条 B 站链接", "err");
    if (!state.rows.some((r) => (r.url || "").trim())) return toast("链接不能为空", "err");

    $("#btnStart").disabled = true;
    $("#logPanel").hidden = true;
    $("#logBox").innerHTML = "";
    $("#overallWrap").hidden = false;
    $("#overallBar").style.width = "0%";
    $("#overallText").textContent = "0 / " + rows.length;
    $("#runHint").textContent = "正在提交任务…";

    try {
      const res = await api("/api/start", { rows, options: collectOptions() });
      state.jobId = res.job_id;
      state.lastSnapshot = null;
      // 服务端按「提交顺序」重新编号 idx，这里记下参与本次任务的每一行 uid
      state.jobRows = rows.map((r) => state.rows[r.idx].uid);
      rows.forEach((r) => { state.rows[r.idx].result = null; });
      poll();
      state.timer = setInterval(poll, 850);
      toast("任务已开始，共 " + rows.length + " 条");
    } catch (e) {
      $("#btnStart").disabled = false;
      toast("启动失败：" + e.message, "err");
    }
  }

  // 只处理某一行（状态「待处理」上的「立即处理」）
  async function runOne(uid) {
    if (state.jobStatus === "running") return toast("还有任务在跑，等它结束再点", "err");
    const row = state.rows.find((r) => r.uid === uid);
    if (!row) return;
    const url = (row.url || "").trim();
    if (!url) {
      toast("这一行还没填链接", "err");
      const el = rowEl(state.rows.indexOf(row));
      if (el) el.querySelector(".url").focus();
      return;
    }
    row.result = null;
    const el = rowEl(state.rows.indexOf(row));
    if (el) paintItemRow(el, null, row.uid);
    $("#logPanel").hidden = true;
    $("#logBox").innerHTML = "";
    $("#overallWrap").hidden = false;
    $("#overallBar").style.width = "0%";
    $("#overallText").textContent = "0 / 1";
    $("#runHint").textContent = "正在提交这一条…";
    try {
      const res = await api("/api/start", {
        rows: [{ idx: 0, url, title: (row.title || "").trim(), artist: (row.artist || "").trim() }],
        options: collectOptions(),
      });
      state.jobId = res.job_id;
      state.lastSnapshot = null;
      state.jobRows = [uid];      toast("已开始处理这一条");
      poll();
      if (state.timer) clearInterval(state.timer);
      state.timer = setInterval(poll, 850);
    } catch (e) {
      toast("启动失败：" + e.message, "err");
    }
  }

  async function poll() {
    if (!state.jobId) return;
    try {
      const snap = await api("/api/job?id=" + state.jobId);
      paint(snap);
      if (snap.status !== "running") {
        clearInterval(state.timer);
        state.timer = null;
        $("#btnStart").disabled = false;
        $("#btnStart").style.display = "";
        $("#btnCancel").hidden = true;
      }
    } catch (e) {
      clearInterval(state.timer);
      state.timer = null;
      $("#btnStart").disabled = false;
      toast("任务状态获取失败：" + e.message, "err");
    }
  }

  /* ----------------------------- 编辑弹窗 ----------------------------- */
  function openEdit(idx) {
    const it = (state.lastSnapshot.items || []).find((x) => x.idx === idx);
    if (!it) return;
    state.editingIdx = idx;
    const m = it.meta || {};
    $("#edTitle").value = m.title || it.title_in || "";
    $("#edArtist").value = m.artist || it.artist_in || "";
    $("#edAlbum").value = m.album || "";
    $("#edYear").value = m.year || "";
    $("#edTrack").value = m.track || "";
    $("#edGenre").value = m.genre || "";
    $("#edLyrics").value = m.lyrics_preview || "";
    $("#editSource").textContent = "来源：" + (m.source || "-") + " · 置信度 " + (m.confidence || 0);
    $("#editCover").innerHTML = `<img src="${it.cover}?t=${Date.now()}" onerror="this.parentNode.textContent='无封面'">`;
    renderCandidates(m.candidates || [], it);
    openModal("editModal");
    // 预览接口里歌词是截断的，这里补取完整歌词，避免保存时把歌词截短
    if (state.jobId) {
      api("/api/lyrics/" + state.jobId + "/" + idx).then((r) => {
        if (r && r.lyrics && state.editingIdx === idx) $("#edLyrics").value = r.lyrics;
      }).catch(() => {});
    }
  }

  function renderCandidates(cands, it) {
    const box = $("#editCandidates");
    if (!cands.length) { box.innerHTML = '<p class="hint">没有候选，可点「重新刮削」再试。</p>'; return; }
    box.innerHTML = cands.slice(0, 5).map((c, i) =>
      `<div class="cand" data-c="${i}"><span class="sc">${(c.score || 0).toFixed(2)}</span><b>${esc(c.title)}</b><br>${esc(c.artist)} · ${esc(c.album || "无专辑")} ${c.year ? "· " + esc(c.year) : ""}</div>`
    ).join("");
    $$(".cand", box).forEach((el) => {
      el.addEventListener("click", () => {
        const c = cands[parseInt(el.dataset.c, 10)];
        $("#edTitle").value = c.title || "";
        $("#edArtist").value = c.artist || "";
        $("#edAlbum").value = c.album || "";
        $("#edYear").value = c.year || "";
        $("#edTrack").value = c.track || "";
        $("#edGenre").value = c.genre || "";
      });
    });
  }

  async function rescrape() {
    const title = $("#edTitle").value.trim();
    if (!title) return toast("先填歌名再刮削", "err");
    const btn = $("#btnRescrape");
    btn.disabled = true; btn.textContent = "刮削中…";
    try {
      const it = (state.lastSnapshot.items || []).find((x) => x.idx === state.editingIdx);
      const r = await api("/api/rescrape", {
        title, artist: $("#edArtist").value.trim(),
        duration: (state.lastSnapshot.items || [])[state.editingIdx].duration || 0,
        translate_lyrics: $("#cfgTranslate").checked,
      });
      $("#edTitle").value = r.title || title;
      $("#edArtist").value = r.artist || "";
      $("#edAlbum").value = r.album || "";
      $("#edYear").value = r.year || "";
      $("#edTrack").value = r.track || "";
      $("#edGenre").value = r.genre || "";
      if (r.lyrics) $("#edLyrics").value = r.lyrics;
      $("#editSource").textContent = "来源：" + r.source + " · 置信度 " + r.confidence;
      if (r.cover) $("#editCover").innerHTML = `<img src="${r.cover}">`;
      renderCandidates(r.candidates || [], it || {});
      toast("刮削完成：" + r.source);
    } catch (e) {
      toast("刮削失败：" + e.message, "err");
    } finally {
      btn.disabled = false; btn.textContent = "🔄 重新刮削";
    }
  }

  async function saveEdit() {
    const btn = $("#btnEditSave");
    btn.disabled = true;
    try {
      const fields = {
        title: $("#edTitle").value.trim(),
        artist: $("#edArtist").value.trim(),
        album: $("#edAlbum").value.trim(),
        year: $("#edYear").value.trim(),
        track: $("#edTrack").value.trim(),
        genre: $("#edGenre").value.trim(),
        lyrics: $("#edLyrics").value,
      };
      const r = await api("/api/retag", {
        job_id: state.jobId, idx: state.editingIdx, fields, rename: true,
      });
      toast("标签已重写" + (r.filename ? "：" + r.filename : ""));
      closeModal("editModal");
      poll();
    } catch (e) {
      toast("保存失败：" + e.message, "err");
    } finally {
      btn.disabled = false;
    }
  }

  /* ----------------------------- 弹窗控制 ----------------------------- */
  function openModal(id) { $("#" + id).classList.add("open"); }
  function closeModal(id) { $("#" + id).classList.remove("open"); }
  document.addEventListener("click", (e) => {
    const c = e.target.closest("[data-close]");
    if (c) closeModal(c.dataset.close);
    if (e.target.classList.contains("modal")) e.target.classList.remove("open");
  });

  /* ----------------------------- 批量粘贴 ----------------------------- */
  const URL_RE = /(https?:\/\/[^\s|｜]+|BV[0-9A-Za-z]{8,}|av\d{5,}|[bB][vV][0-9A-Za-z]+)/;

  function parseLine(line) {
    const raw = line.trim();
    if (!raw) return null;
    // 统一分隔符
    let parts = raw.split(/[|｜\t]+/).map((s) => s.trim()).filter(Boolean);
    if (parts.length === 1) {
      // 允许 "歌名 - 歌手 https://..." 这种空格分隔
      const sp = raw.split(/\s+/);
      if (sp.length > 1 && sp.some((x) => URL_RE.test(x))) parts = sp;
    }
    let url = "", title = "", artist = "";
    const urlIdx = parts.findIndex((p) => URL_RE.test(p));
    if (urlIdx >= 0) {
      url = parts[urlIdx];
      const rest = parts.filter((_, i) => i !== urlIdx);
      title = rest[0] || "";
      artist = rest[1] || "";
    } else if (parts.length >= 2) {
      title = parts[0]; artist = parts[1];
    } else {
      title = parts[0];
    }
    // "歌名 - 歌手" 拆分
    if (title && !artist) {
      const m = title.match(/^(.+?)\s*[-–—]\s*(.+)$/);
      if (m) { title = m[1].trim(); artist = m[2].trim(); }
    }
    return { url, title, artist };
  }

  function importPaste() {
    const lines = $("#pasteArea").value.split(/\r?\n/);
    let added = 0, skipped = 0;
    lines.forEach((line) => {
      const r = parseLine(line);
      if (!r) return;
      if (!r.url && !r.title) { skipped++; return; }
      if (!r.url) { skipped++; return; }   // 没有链接的条目忽略
      state.rows.push(mkRow(r));
      added++;
    });
    renderRows();
    closeModal("pasteModal");
    $("#pasteArea").value = "";
    $("#pasteCount").textContent = "0 行";
    saveDraft();
    toast(added ? "已导入 " + added + " 条" + (skipped ? "，忽略 " + skipped + " 行" : "") : "没有解析到有效条目",
      added ? "" : "err");
  }

  /* ----------------------------- 设置 ----------------------------- */
  /* ------------------------ 导出格式 / 码率 ------------------------ */
  const QUALITY_SETS = {
    mp3: [["320", "320 kbps（推荐）"], ["256", "256 kbps"], ["192", "192 kbps"],
          ["128", "128 kbps"], ["0", "VBR 最高质量"]],
    m4a: [["256", "256 kbps（推荐）"], ["192", "192 kbps"], ["128", "128 kbps"]],
    ogg: [["192", "192 kbps（推荐）"], ["128", "128 kbps"], ["96", "96 kbps"]],
    wav: [["0", "无损（不可调）"]],
    flac: [["0", "无损（不可调）"]],
  };
  const FORMAT_TIP = {
    mp3: "最通用的格式，车载、手机、老播放器都认；标签用 ID3v2.3。",
    m4a: "AAC 编码，同码率下体积更小；标签用 MP4 原子（Apple 全系友好）。",
    wav: "未压缩 PCM 无损，体积最大（约 10MB/分钟）；标签用 ID3。",
    flac: "无损压缩，体积约为 WAV 的 60%；标签用 Vorbis Comment。",
    ogg: "Vorbis 编码，体积最小，部分老设备不支持；标签用 Vorbis Comment。",
  };

  function applyFormat(fmt, quality) {
    fmt = QUALITY_SETS[fmt] ? fmt : "mp3";
    $("#cfgFormat").value = fmt;
    const sel = $("#cfgQuality");
    const set = QUALITY_SETS[fmt];
    sel.innerHTML = set.map(([v, label]) => `<option value="${v}">${esc(label)}</option>`).join("");
    const want = String(quality == null ? "" : quality);
    sel.value = set.some(([v]) => v === want) ? want : set[0][0];
    const lossless = fmt === "wav" || fmt === "flac";
    sel.disabled = lossless;
    $("#cfgQualityLabel").textContent = lossless ? "音频质量" : "音频码率";
    $("#qualityHint").textContent = FORMAT_TIP[fmt] || "";
  }

  function fillConfig(cfg) {
    state.cfg = cfg;
    applyFormat(cfg.format || "mp3", cfg.quality);
    $("#cfgTemplate").value = cfg.filename_template || "{artist} - {title}";
    $("#cfgOutDir").value = cfg.out_dir || "";
    $("#cfgConcurrency").value = String(cfg.concurrency || 1);
    $("#cfgCover").checked = cfg.embed_cover !== false;
    $("#cfgLyrics").checked = cfg.embed_lyrics !== false;
    $("#cfgTranslate").checked = cfg.translate_lyrics !== false;
    const src = cfg.sources || ["netease", "qq", "itunes", "musicbrainz"];
    $("#srcNetease").checked = src.indexOf("netease") >= 0;
    $("#srcQQ").checked = src.indexOf("qq") >= 0;
    $("#srcItunes").checked = src.indexOf("itunes") >= 0;
    $("#srcMb").checked = src.indexOf("musicbrainz") >= 0;
  }

  /* ------------------------ 设置自动保存 ------------------------ */
  function setAutosaveTip(text, mode) {
    const el = $("#autosaveTip");
    if (!el) return;
    el.textContent = text;
    el.className = "autosave " + (mode || "");
  }

  let autosaveBusy = false;
  const autosaveConfig = debounce(async function () {
    if (autosaveBusy) return;
    autosaveBusy = true;
    setAutosaveTip("保存中…", "saving");
    try {
      const cfg = await api("/api/config", collectOptions());
      state.cfg = cfg;
      setAutosaveTip("已自动保存", "saved");
      setTimeout(() => { if (!autosaveBusy) setAutosaveTip("自动保存"); }, 2200);
    } catch (e) {
      setAutosaveTip("保存失败", "");
      toast("设置保存失败：" + e.message, "err");
    } finally {
      autosaveBusy = false;
    }
  }, 500);

  async function saveConfig() {
    try {
      const cfg = await api("/api/config", collectOptions());
      fillConfig(cfg);
      setAutosaveTip("已自动保存", "saved");
      toast("设置已保存");
    } catch (e) { toast("保存失败：" + e.message, "err"); }
  }

  /* ------------------------ B 站账号 ------------------------ */
  function renderBili(b) {
    state.bili = b || null;
    const logged = !!(b && b.logged_in);
    $("#biliLogin").hidden = logged;
    $("#biliUser").hidden = !logged;
    $("#biliFavRow").hidden = !logged;
    $("#biliState").textContent = logged ? "已登录" : "未登录";
    $("#biliState").className = "chip " + (logged ? "live" : "subtle");
    if (logged) {
      $("#biliName").textContent = b.uname || "B 站用户";
      $("#biliMeta").textContent = (b.vip ? "大会员 · " : "") + (b.cookie_hint || "已登录");
      if (b.face) {
        $("#biliAvatar").src = b.face;
        $("#biliAvatar").hidden = false;
      } else {
        $("#biliAvatar").hidden = true;
      }
    } else {
      $("#biliCookie").value = "";
    }
  }

  async function biliLogin() {
    const raw = $("#biliCookie").value.trim();
    if (!raw) return toast("请先粘贴 SESSDATA", "err");
    const btn = $("#btnBiliLogin");
    btn.disabled = true;
    btn.textContent = "登录中…";
    try {
      const r = await api("/api/bili/login", { cookie: raw });
      renderBili(r.bili);
      toast("登录成功：" + (r.bili.uname || ""));
    } catch (e) {
      toast("登录失败：" + e.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "登录 B 站";
    }
  }

  async function biliLogout() {
    try {
      const r = await api("/api/bili/logout", {});
      renderBili(r.bili);
      toast("已退出登录");
    } catch (e) { toast(e.message, "err"); }
  }

  /* ------------------------ 收藏夹导入 ------------------------ */
  async function openFav() {
    if (!state.bili || !state.bili.logged_in) return toast("请先登录 B 站账号", "err");
    openModal("favModal");
    $("#favFolders").innerHTML = "";
    $("#favList").innerHTML = "";
    $("#favStatus").textContent = "正在读取收藏夹…";
    $("#btnFavImport").disabled = true;
    $("#btnFavMore").hidden = true;
    try {
      const r = await api("/api/bili/folders");
      state.fav.folders = r.folders || [];
      if (!state.fav.folders.length) {
        $("#favStatus").textContent = "没有找到收藏夹（可能是私密收藏夹或账号无收藏）。";
        return;
      }
      renderFavFolders();
      let saved = 0;
      try { saved = parseInt(localStorage.getItem(LS_FAV_MEDIA) || "0", 10) || 0; } catch (e) { saved = 0; }
      const pick = state.fav.folders.find((f) => f.id === saved) || state.fav.folders[0];
      await selectFolder(pick.id, true);
    } catch (e) {
      $("#favStatus").textContent = "读取失败：" + e.message;
      toast("收藏夹读取失败：" + e.message, "err");
    }
  }

  function renderFavFolders() {
    $("#favFolders").innerHTML = state.fav.folders.map((f) =>
      `<div class="fav-folder${f.id === state.fav.mediaId ? " on" : ""}" data-f="${f.id}">${esc(f.title)} <span class="muted">${f.count}</span></div>`
    ).join("");
    $$("#favFolders .fav-folder").forEach((el) => {
      el.addEventListener("click", () => {
        const id = parseInt(el.dataset.f, 10);
        if (id === state.fav.mediaId) return;
        selectFolder(id, true);
      });
    });
  }

  async function selectFolder(id, reset) {
    state.fav.mediaId = id;
    if (reset) {
      state.fav.items = [];
      state.fav.page = 1;
      state.fav.hasMore = false;
      state.fav.sel = new Set();
      state.fav.title = "";
    }
    renderFavFolders();
    $("#favList").innerHTML = "";
    $("#favStatus").textContent = "正在加载…";
    try { localStorage.setItem(LS_FAV_MEDIA, String(id)); } catch (e) { /* ignore */ }
    await loadFavPage();
  }

  async function loadFavPage() {
    const page = state.fav.page;
    try {
      const r = await api("/api/bili/fav?media_id=" + encodeURIComponent(state.fav.mediaId) +
        "&page=" + page + "&size=20");
      state.fav.title = r.title || state.fav.title;
      state.fav.items = state.fav.items.concat(r.items || []);
      state.fav.hasMore = !!r.has_more;
      state.fav.page = page + 1;
      renderFavList();
      $("#favStatus").textContent = (state.fav.title || "收藏夹") + " · 共 " + (r.total || 0) + " 个视频";
      $("#btnFavMore").hidden = !state.fav.hasMore;
    } catch (e) {
      $("#favStatus").textContent = "加载失败：" + e.message;
    }
  }

  function renderFavList() {
    const box = $("#favList");
    if (!state.fav.items.length) {
      box.innerHTML = '<p class="hint">这个收藏夹里没有可下载的视频。</p>';
      return;
    }
    box.innerHTML = state.fav.items.map((it, i) => `
      <label class="fav-item${state.fav.sel.has(it.bvid) ? " on" : ""}" data-i="${i}">
        <input type="checkbox" ${state.fav.sel.has(it.bvid) ? "checked" : ""}>
        <img src="${esc(it.cover)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
        <div class="fav-text">
          <div class="fav-title">${esc(it.title)}</div>
          <div class="fav-sub">${esc(it.upper)} · ${fmtDuration(it.duration)} · ${esc(it.bvid)}</div>
        </div>
      </label>`).join("");
    $$("#favList .fav-item").forEach((el) => {
      const it = state.fav.items[parseInt(el.dataset.i, 10)];
      const cb = el.querySelector("input");
      const toggle = () => {
        if (state.fav.sel.has(it.bvid)) state.fav.sel.delete(it.bvid);
        else state.fav.sel.add(it.bvid);
        el.classList.toggle("on", state.fav.sel.has(it.bvid));
        cb.checked = state.fav.sel.has(it.bvid);
        updateFavCount();
      };
      // 复选框只做展示，点击统一走 label，避免原生 toggle 与状态双重翻转
      el.addEventListener("click", (e) => {
        e.preventDefault();
        toggle();
      });
    });
    updateFavCount();
  }

  function updateFavCount() {
    const n = state.fav.sel.size;
    $("#favCount").textContent = "已选 " + n + " 条";
    $("#btnFavImport").disabled = n === 0;
  }

  function importFav() {
    const picked = state.fav.items.filter((it) => state.fav.sel.has(it.bvid));
    if (!picked.length) return toast("先勾选要导入的视频", "err");
    const exist = new Set(state.rows.map((r) => (r.url || "").trim()));
    // 去掉末尾的空行，避免和导入内容混在一起
    state.rows = state.rows.filter((r) => (r.url || "").trim() || (r.title || "").trim());
    let added = 0, dup = 0;
    picked.forEach((it) => {
      if (exist.has(it.url)) { dup++; return; }
      exist.add(it.url);
      state.rows.push(mkRow({ url: it.url, title: "", artist: "" }));
      added++;
    });
    if (!state.rows.length) state.rows.push(mkRow({}));
    renderRows();
    saveDraft();
    closeModal("favModal");
    toast("已导入 " + added + " 条" + (dup ? "，跳过重复 " + dup + " 条" : ""));
  }

  /* ----------------------------- 初始化 ----------------------------- */
  async function boot() {
    $("#envBadges").innerHTML = '<span class="env-badge">加载中…</span>';
    try {
      const h = await api("/api/health");
      fillConfig(h.config || {});
      renderBili(h.bili);
      const ffOk = h.ffmpeg && h.ffmpeg !== "未找到";
      $("#envBadges").innerHTML = `
        <span class="env-badge"><span class="dot"></span>Python <b>${esc(h.python)}</b></span>
        <span class="env-badge"><span class="dot"></span>yt-dlp <b>${esc(h.ytdlp)}</b></span>
        <span class="env-badge"><span class="dot ${ffOk ? "" : "bad"}"></span>FFmpeg <b>${esc(h.ffmpeg)}</b></span>`;
      if (!ffOk) toast("未找到 FFmpeg，无法转换 MP3。请检查项目 bin 目录。", "err");
    } catch (e) {
      toast("无法连接本地服务：" + e.message, "err");
      renderBili(null);
    }
    const draft = loadDraft();
    if (draft.length) {
      state.rows = draft.map((r) => mkRow(r));
      renderRows();
      toast("已恢复上次的 " + draft.length + " 条链接");
    } else if (!state.rows.length) {
      addRow({});
    }
  }

  $("#btnAdd").addEventListener("click", () => {
    const i = addRow({});
    const el = rowEl(i);
    if (el) el.querySelector(".url").focus();
  });
  $("#btnClear").addEventListener("click", () => {
    if (state.jobStatus === "running") return toast("任务运行中，无法清空", "err");
    if (!state.rows.length) return;
    state.rows = [];
    state.jobId = null; state.lastSnapshot = null;
    $("#logPanel").hidden = true;
    $("#overallWrap").hidden = true;
    $("#runHint").textContent = "准备就绪";
    $("#btnZip").hidden = true;
    try { localStorage.removeItem(LS_ROWS); } catch (e) { /* ignore */ }
    renderRows();
    addRow({});
  });
  $("#btnSample").addEventListener("click", () => {
    state.rows = [
      mkRow({ url: "https://www.bilibili.com/video/BV1GJ411x7h7", title: "", artist: "" }),
      mkRow({ url: "", title: "起风了", artist: "买辣椒也用券" }),
    ];
    renderRows();
    saveDraft();
    toast("已填入示例，请替换成你的链接");
  });
  $("#btnStart").addEventListener("click", start);
  $("#btnCancel").addEventListener("click", async () => {
    if (!state.jobId) return;
    try { await api("/api/cancel/" + state.jobId, {}); toast("已停止"); } catch (e) { toast(e.message, "err"); }
  });
  $("#btnZip").addEventListener("click", () => {
    if (state.jobId) window.location.href = "/api/zip/" + state.jobId;
  });
  $("#btnFolder").addEventListener("click", async () => {
    try { await api("/api/open-folder", {}); } catch (e) { toast(e.message, "err"); }
  });
  $("#btnPickDir").addEventListener("click", async () => {
    try { await api("/api/open-folder", {}); } catch (e) { toast(e.message, "err"); }
  });
  const saveBtn = $("#btnSaveCfg");
  if (saveBtn) saveBtn.addEventListener("click", saveConfig);
  $("#btnClearLog").addEventListener("click", () => { $("#logBox").innerHTML = ""; $("#logPanel").hidden = true; });

  $("#btnPaste").addEventListener("click", () => {
    openModal("pasteModal");
    $("#pasteArea").focus();
  });
  $("#pasteArea").addEventListener("input", () => {
    const n = $("#pasteArea").value.split(/\r?\n/).filter((x) => x.trim()).length;
    $("#pasteCount").textContent = n + " 行";
  });
  $("#btnPasteOk").addEventListener("click", importPaste);

  $("#btnRescrape").addEventListener("click", rescrape);
  $("#btnEditSave").addEventListener("click", saveEdit);

  /* ---------------- 设置自动保存 / B 站账号 / 收藏夹 ---------------- */
  ["#cfgFormat", "#cfgQuality", "#cfgTemplate", "#cfgOutDir", "#cfgConcurrency", "#cfgCover",
   "#cfgLyrics", "#cfgTranslate", "#srcNetease", "#srcQQ", "#srcItunes", "#srcMb"]
    .forEach((sel) => {
      const el = $(sel);
      if (!el) return;
      el.addEventListener("change", autosaveConfig);
      if (el.tagName === "INPUT" && el.type === "text") el.addEventListener("input", autosaveConfig);
    });
  if ($("#cfgFormat")) {
    $("#cfgFormat").addEventListener("change", () => {
      applyFormat($("#cfgFormat").value, $("#cfgQuality").value);
    });
  }

  if ($("#btnTheme")) {
    paintThemeIcon(currentThemeMode());
    $("#btnTheme").addEventListener("click", cycleTheme);
    if (window.matchMedia) {
      const mq = window.matchMedia("(prefers-color-scheme: light)");
      const onChange = () => {
        if (currentThemeMode() === "auto") {
          document.documentElement.setAttribute("data-theme", resolveTheme("auto"));
        }
      };
      if (mq.addEventListener) mq.addEventListener("change", onChange);
      else if (mq.addListener) mq.addListener(onChange);
    }
  }

  if ($("#btnBiliLogin")) $("#btnBiliLogin").addEventListener("click", biliLogin);
  if ($("#btnBiliLogout")) $("#btnBiliLogout").addEventListener("click", biliLogout);
  if ($("#btnBiliHelp")) {
    $("#btnBiliHelp").addEventListener("click", () => {
      const box = $("#biliHelp");
      box.hidden = !box.hidden;
    });
  }
  if ($("#biliCookie")) {
    $("#biliCookie").addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") biliLogin();
    });
  }
  if ($("#btnFav")) $("#btnFav").addEventListener("click", openFav);
  if ($("#btnFavMore")) $("#btnFavMore").addEventListener("click", loadFavPage);
  if ($("#btnFavImport")) $("#btnFavImport").addEventListener("click", importFav);
  if ($("#btnFavAll")) {
    $("#btnFavAll").addEventListener("click", () => {
      const allOn = state.fav.items.length > 0 &&
        state.fav.items.every((it) => state.fav.sel.has(it.bvid));
      if (allOn) state.fav.sel.clear();
      else state.fav.items.forEach((it) => state.fav.sel.add(it.bvid));
      renderFavList();
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") $$(".modal.open").forEach((m) => m.classList.remove("open"));
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !state.timer) start();
  });

  boot();
})();
