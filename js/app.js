/**
 * app.js — 每日金融观察 · 前端渲染引擎 (Phase 1-8)
 * ==================================================
 * 读取 window.__SITE_DATA__（由 fetch_data.py 生成），
 * 渲染所有板块：指数、新闻、行业板块(ECharts/纯CSS降级)、
 * 市场宽度、个股动向、外汇、环球股指、基金排行、
 * 盘面简评、历史走势、自动化运行日志。
 *
 * 抽屉式导航：桌面端左侧固定，窄屏收起为汉堡菜单。
 */

(function() {
  'use strict';

  var D = null; // __SITE_DATA__ reference
  var chartInstances = {};   // { viewId: echartsInstance }
  var chartRendered = {};    // { viewId: true } — 是否已初始化过图表

  // ======================== 初始化 ========================

  function init() {
    D = window.__SITE_DATA__;
    if (!D) {
      document.getElementById('message').textContent = '数据加载失败 — 请确保 data.js 已生成';
      return;
    }

    renderAll();
    initDrawer();
    initHistoryChart();
    initSectorChart();
    initThemeToggle();
    initExportButtons();
    initKeyboardShortcuts();
    initKbdHint();
  }

  // ======================== 工具函数 ========================

  function fmtPct(v) {
    if (v == null || isNaN(v)) return '—';
    return (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%';
  }

  function upDown(v) {
    return v >= 0 ? 'up' : 'down';
  }

  function fmtNum(n, d) {
    if (n == null || isNaN(n)) return '—';
    d = d != null ? d : 2;
    return Number(n).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  function fmtTime(iso) {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleString('zh-CN'); } catch(e) { return iso; }
  }

  // ======================== 主渲染入口 ========================

  function renderAll() {
    renderHeader();
    renderOverview();
    renderCommentary();
    renderIndices();
    renderHistory();
    renderSectors();
    renderBreadth();
    renderMovers();
    renderFx();
    renderGlobal();
    renderFunds();
    renderNorthbound();
    renderTurnover();
    renderCommodities();
    renderDragonTiger();
    renderTreasury();
    renderCsi300Val();
    renderConvertibleBonds();
    renderLogs();
    renderSources();
  }

  // ======================== Header ========================

  function renderHeader() {
    var badge = document.getElementById('status-badge');
    var updated = document.getElementById('updated-at');
    var streakEl = document.getElementById('run-streak');
    var totalEl = document.getElementById('run-total');
    var drawerStreak = document.getElementById('drawer-streak');

    if (badge) {
      if (D.status === 'ok') {
        badge.textContent = 'OK';
        badge.className = 'badge ok';
      } else {
        badge.textContent = '降级';
        badge.className = 'badge degraded';
      }
    }

    if (updated) { updated.textContent = D.updated_at || '—'; }

    var stats = D.run_stats || {};
    if (streakEl) streakEl.textContent = stats.streak || 0;
    if (totalEl) totalEl.textContent = stats.total_days || 0;
    if (drawerStreak) drawerStreak.textContent = stats.streak || 0;
  }

  // ======================== 今日观察 (Overview) ========================

  function renderOverview() {
    var msgEl = document.getElementById('message');
    if (msgEl) {
      if (D.status === 'degraded') {
        msgEl.innerHTML = '<span style="color:#d29922">⚠ 部分数据源降级，以下数据可能不完整。</span>';
      } else {
        msgEl.textContent = D.message || '数据已加载';
      }
    }

    // 新闻内嵌到 overview
    renderNewsInline();
  }

  function renderNewsInline() {
    var container = document.getElementById('news-inline');
    if (!container) return;

    // 优先显示总结；没有总结时才退回到列表
    var summary = D.news_summary || '';
    var news = D.news || [];

    if (summary) {
      container.innerHTML = '<div class="news-briefing">' + summary + '</div>';
      return;
    }

    if (!news.length) {
      container.innerHTML = '<div class="placeholder">暂无资讯</div>';
      return;
    }

    // 退路：真实 RSS 新闻列表（fetch_data.py 产出）
    var html = '';
    for (var i = 0; i < news.length; i++) {
      var n = news[i];
      var link = n.link || '';
      var isRealLink = /^https?:\/\//.test(link) &&
                       !/example\.com|localhost|127\.0\.0\.1|test\.com|invalid/i.test(link);
      html += '<div class="news-item">';
      if (isRealLink) {
        html += '<a href="' + link + '" target="_blank" rel="noopener">' + n.title + '<span class="arrow"> ↗</span></a>';
      } else {
        html += '<span class="news-title-text">' + n.title + '</span>';
      }
      if (n.summary) {
        html += '<div class="news-summary">' + n.summary + '</div>';
      }
      html += '<div class="news-meta">';
      if (n.source) html += '<span class="tag">' + n.source + '</span>';
      html += (n.published || '') + '</div>';
      html += '</div>';
    }
    container.innerHTML = html;
  }

  // ======================== 盘面简评 ========================

  function renderCommentary() {
    var container = document.getElementById('commentary');
    if (!container) return;
    var items = D.commentary || [];
    if (!items.length) {
      container.innerHTML = '<div class="placeholder">暂无简评数据</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < items.length; i++) {
      var c = items[i];
      var toneClass = c.tone || 'neutral';
      html += '<div class="item">';
      html += '<div class="head"><span class="lab ' + toneClass + '">' + (c.label || '') + '</span></div>';
      html += '<div class="tx">' + (c.text || '') + '</div>';
      html += '</div>';
    }
    container.innerHTML = html;
  }

  // ======================== A股三大指数 ========================

  function renderIndices() {
    var container = document.getElementById('indices');
    if (!container) return;
    var indices = D.indices || [];
    if (!indices.length) {
      container.innerHTML = '<div class="placeholder">暂无指数数据（降级）</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < indices.length; i++) {
      var idx = indices[i];
      var cls = idx.up ? 'up' : 'down';
      html += '<div class="idx ' + cls + '">';
      html += '<div class="top"><span><span class="name">' + idx.name + '</span><span class="code">' + (idx.code || '') + '</span></span>';
      html += '<span><span class="price">' + fmtNum(idx.price, 2) + '</span>';
      html += '<span class="chg">' + fmtPct(idx.change_pct) + '</span></span></div>';
      html += '<div class="bar-wrap"><div class="bar" style="width:' + Math.min(Math.abs(idx.change_pct || 0) * 6, 100) + '%"></div></div>';
      html += '</div>';
    }
    container.innerHTML = html;
  }

  // ======================== 指数历史走势 ========================

  function renderHistory() {
    var fallback = document.getElementById('history-fallback');
    var history = D.history || [];
    if (!history.length) {
      if (fallback) { fallback.style.display = 'block'; fallback.innerHTML = '<div class="placeholder">暂无历史数据（需连续运行数日后自动累积）</div>'; }
      return;
    }
    // 检查视图是否可见，不可见则延迟到激活时再渲染
    var viewEl = document.getElementById('sec-history');
    if (viewEl && !viewEl.classList.contains('active')) {
      return; // 等 onViewActivate 触发
    }
    drawHistoryChartOrFallback();
  }

  function drawHistoryChartOrFallback() {
    var fallback = document.getElementById('history-fallback');
    var history = D.history || [];
    if (window.echarts && !window.__ECHARTS_FAILED__) {
      drawHistoryChart();
    } else {
      if (fallback) fallback.style.display = 'block';
      drawHistoryFallback();
    }
  }

  function drawHistoryFallback() {
    var fb = document.getElementById('history-fallback');
    if (!fb) return;
    var history = D.history || [];
    fb.style.display = 'block';
    var maxAbs = 0;
    for (var i = 0; i < history.length; i++) {
      maxAbs = Math.max(maxAbs, Math.abs(history[i].sh_pct || 0));
    }
    maxAbs = maxAbs || 5;
    var html = '';
    for (var j = 0; j < history.length; j++) {
      var h = history[j];
      var pct = h.sh_pct || 0;
      var cls = pct >= 0 ? 'up' : 'down';
      var w = Math.max(Math.abs(pct) / maxAbs * 100, 2);
      html += '<div class="hist-bar"><span class="d">' + (h.date || '').slice(5) + '</span>';
      html += '<div class="track"><div class="fill ' + cls + '" style="width:' + w + '%"></div></div>';
      html += '<span class="pc ' + cls + '">' + fmtPct(pct) + '</span></div>';
    }
    fb.innerHTML = html;
  }

  function drawHistoryChart() {
    var chartDom = document.getElementById('history-chart');
    if (!chartDom || !window.echarts) return;
    var history = D.history || [];
    var dates = [], pcts = [], colors = [];
    for (var i = 0; i < history.length; i++) {
      dates.push((history[i].date || '').slice(5));
      var v = history[i].sh_pct || 0;
      pcts.push(v);
      colors.push(v >= 0 ? '#f04848' : '#2ec27e');
    }
    // 销毁旧实例
    if (chartInstances['sec-history']) {
      chartInstances['sec-history'].dispose();
    }
    var chart = window.echarts.init(chartDom);
    chart.setOption({
      grid: { top: 8, right: 16, bottom: 24, left: 44 },
      xAxis: { type: 'category', data: dates, axisLabel: { color: '#8b949e', fontSize: 11 } },
      yAxis: { type: 'value', axisLabel: { color: '#8b949e', formatter: '{value}%' } },
      series: [{
        type: 'bar', data: pcts,
        itemStyle: { color: function(p) { return colors[p.dataIndex]; } }
      }]
    });
    chartInstances['sec-history'] = chart;
    chartRendered['sec-history'] = true;
    window.addEventListener('resize', function() { chart.resize(); });
  }

  function initHistoryChart() {
    // called on load; deferred to renderHistory
  }

  // ======================== 行业板块 ========================

  function renderSectors() {
    // Summary
    var summary = document.getElementById('sector-summary');
    if (summary) {
      var ss = D.sector_summary || {};
      if (ss.total) {
        summary.innerHTML =
          '<div class="stat"><div class="k">板块总数</div><div class="v">' + ss.total + '</div></div>' +
          '<div class="stat"><div class="k">上涨板块</div><div class="v up">' + (ss.up_count || 0) + '</div></div>' +
          '<div class="stat"><div class="k">下跌板块</div><div class="v down">' + (ss.down_count || 0) + '</div></div>' +
          '<div class="stat"><div class="k">领涨</div><div class="v up" style="font-size:13px">' + (ss.top_name || '—') + ' ' + fmtPct(ss.top_pct) + '</div></div>' +
          '<div class="stat"><div class="k">领跌</div><div class="v down" style="font-size:13px">' + (ss.bottom_name || '—') + ' ' + fmtPct(ss.bottom_pct) + '</div></div>';
      } else {
        summary.innerHTML = '<div class="placeholder">暂无板块统计</div>';
      }
    }

    // Chart or fallback — 不可见时延迟渲染
    var sectors = D.sectors || [];
    if (!sectors.length) {
      document.getElementById('sector-chart').innerHTML = '<div class="placeholder">暂无板块数据</div>';
      return;
    }
    var viewEl = document.getElementById('sec-sectors');
    if (viewEl && !viewEl.classList.contains('active')) {
      return; // 等 onViewActivate 触发
    }
    drawSectorChartOrFallback();
  }

  function drawSectorChartOrFallback() {
    if (window.echarts && !window.__ECHARTS_FAILED__) {
      drawSectorChart();
    } else {
      drawSectorFallback();
    }
  }

  function drawSectorFallback() {
    var fb = document.getElementById('sector-fallback');
    if (!fb) return;
    fb.style.display = 'block';
    var sectors = D.sectors || [];
    var maxAbs = 0;
    for (var i = 0; i < sectors.length; i++) {
      maxAbs = Math.max(maxAbs, Math.abs(sectors[i].change_pct || 0));
    }
    maxAbs = maxAbs || 5;
    var html = '';
    for (var j = 0; j < sectors.length; j++) {
      var s = sectors[j];
      var cls = s.up ? 'up' : 'down';
      var w = Math.max(Math.abs(s.change_pct || 0) / maxAbs * 100, 2);
      html += '<div class="sector-bar"><span class="nm">' + s.name + '</span>';
      html += '<div class="track"><div class="fill ' + cls + '" style="width:' + w + '%"></div></div>';
      html += '<span class="pc ' + cls + '">' + fmtPct(s.change_pct) + '</span></div>';
    }
    fb.innerHTML = html;
  }

  function drawSectorChart() {
    var chartDom = document.getElementById('sector-chart');
    if (!chartDom || !window.echarts) return;
    var sectors = D.sectors || [];
    var names = [], pcts = [], colors = [];
    for (var i = sectors.length - 1; i >= 0; i--) {
      names.push(sectors[i].name);
      pcts.push(sectors[i].change_pct);
      colors.push(sectors[i].up ? '#f04848' : '#2ec27e');
    }
    if (chartInstances['sec-sectors']) {
      chartInstances['sec-sectors'].dispose();
    }
    var chart = window.echarts.init(chartDom);
    chart.setOption({
      grid: { top: 4, right: 48, bottom: 20, left: 90 },
      xAxis: { type: 'value', axisLabel: { color: '#8b949e', formatter: '{value}%' } },
      yAxis: { type: 'category', data: names, axisLabel: { color: '#8b949e', fontSize: 12 } },
      series: [{
        type: 'bar', data: pcts,
        itemStyle: { color: function(p) { return colors[p.dataIndex]; } }
      }]
    });
    chartInstances['sec-sectors'] = chart;
    chartRendered['sec-sectors'] = true;
    window.addEventListener('resize', function() { chart.resize(); });
  }

  function initSectorChart() {
    // deferred
  }

  // ======================== 市场宽度 ========================

  function renderBreadth() {
    var statsEl = document.getElementById('breadth-stats');
    var barEl = document.getElementById('breadth-bar');
    var legendEl = document.getElementById('breadth-legend');

    var b = D.breadth || {};
    if (!b.total) {
      if (statsEl) statsEl.innerHTML = '<div class="placeholder">暂无宽度统计</div>';
      return;
    }

    var upPct = b.up_pct || 0;
    var downPct = 100 - upPct - ((b.flat || 0) / b.total * 100);

    if (statsEl) {
      statsEl.innerHTML =
        '<div class="stat"><div class="k">全市场</div><div class="v">' + b.total + '</div></div>' +
        '<div class="stat"><div class="k">上涨</div><div class="v up">' + (b.up || 0) + ' (' + (b.up_pct || 0).toFixed(1) + '%)</div></div>' +
        '<div class="stat"><div class="k">下跌</div><div class="v down">' + (b.down || 0) + '</div></div>' +
        '<div class="stat"><div class="k">涨停</div><div class="v up">' + (b.limit_up || 0) + '</div></div>' +
        '<div class="stat"><div class="k">跌停</div><div class="v down">' + (b.limit_down || 0) + '</div></div>';
    }

    if (barEl) {
      barEl.innerHTML =
        '<div class="up" style="width:' + upPct + '%"></div>' +
        '<div class="flat" style="width:' + ((b.flat || 0) / b.total * 100).toFixed(1) + '%"></div>' +
        '<div class="down" style="width:' + (100 - upPct - ((b.flat || 0) / b.total * 100)).toFixed(1) + '%"></div>';
    }

    if (legendEl) {
      legendEl.innerHTML = '<b class="up">上涨 ' + (b.up || 0) + ' 家 (' + (b.up_pct || 0).toFixed(1) + '%)</b> · ' +
        '<b class="down">下跌 ' + (b.down || 0) + ' 家</b> · 平盘 ' + (b.flat || 0) + ' 家 · ' +
        '涨停 ' + (b.limit_up || 0) + ' · 跌停 ' + (b.limit_down || 0);
    }
  }

  // ======================== 个股动向 ========================

  function renderMovers() {
    var container = document.getElementById('movers');
    if (!container) return;
    var movers = D.movers || { top_gainers: [], top_losers: [] };
    if (!movers.top_gainers.length && !movers.top_losers.length) {
      container.innerHTML = '<div class="placeholder">暂无个股数据</div>';
      return;
    }

    var html = '<div class="col"><h3>领涨 TOP10</h3>';
    for (var i = 0; i < movers.top_gainers.length; i++) {
      var g = movers.top_gainers[i];
      html += '<div class="mover"><span class="nm">' + g.name + '<span class="code">' + g.code + '</span></span>';
      html += '<span class="pc up">' + fmtPct(g.change_pct) + '</span></div>';
    }
    html += '</div>';

    html += '<div class="col"><h3>领跌 TOP10</h3>';
    for (var j = 0; j < movers.top_losers.length; j++) {
      var l = movers.top_losers[j];
      html += '<div class="mover"><span class="nm">' + l.name + '<span class="code">' + l.code + '</span></span>';
      html += '<span class="pc down">' + fmtPct(l.change_pct) + '</span></div>';
    }
    html += '</div>';

    container.innerHTML = html;
  }

  // ======================== 外汇牌价 ========================

  function renderFx() {
    var tbody = document.querySelector('#fx tbody');
    if (!tbody) return;
    var fx = D.fx || [];
    if (!fx.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="placeholder">暂无外汇数据</td></tr>';
      return;
    }
    var html = '';
    for (var i = 0; i < fx.length; i++) {
      var f = fx[i];
      html += '<tr><td>' + f.name + '</td>';
      html += '<td class="num">' + (f.buy != null ? f.buy.toFixed(4) : '—') + '</td>';
      html += '<td class="num">' + (f.sell != null ? f.sell.toFixed(4) : '—') + '</td></tr>';
    }
    tbody.innerHTML = html;
  }

  // ======================== 环球股指 ========================

  function renderGlobal() {
    var container = document.getElementById('global');
    if (!container) return;
    var gi = D.global_indices || [];
    if (!gi.length) {
      container.innerHTML = '<div class="placeholder">暂无环球股指数据</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < gi.length; i++) {
      var g = gi[i];
      var cls = g.up ? 'up' : 'down';
      html += '<div class="idx ' + cls + '">';
      html += '<div class="top"><span><span class="name">' + g.name + '</span><span class="code">' + (g.market || '') + '</span></span>';
      html += '<span>';
      if (g.price != null) html += '<span class="price" style="font-size:16px">' + fmtNum(g.price, 2) + '</span> ';
      html += '<span class="chg">' + fmtPct(g.change_pct) + '</span></span></div>';
      html += '<div class="bar-wrap"><div class="bar" style="width:' + Math.min(Math.abs(g.change_pct || 0) * 6, 100) + '%"></div></div>';
      html += '</div>';
    }
    container.innerHTML = html;
  }

  // ======================== 基金排行 ========================

  function renderFunds() {
    var tbody = document.querySelector('#funds tbody');
    if (!tbody) return;
    var funds = D.funds || [];
    if (!funds.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="placeholder">暂无基金数据</td></tr>';
      return;
    }
    var html = '';
    for (var i = 0; i < funds.length; i++) {
      var f = funds[i];
      var cls = f.up ? 'up' : 'down';
      html += '<tr><td>' + f.name + ' <span class="code">' + (f.code || '') + '</span></td>';
      html += '<td class="num">' + (f.nav != null ? f.nav.toFixed(4) : '—') + '</td>';
      html += '<td class="num ' + cls + '" style="font-weight:600">' + fmtPct(f.change_pct) + '</td></tr>';
    }
    tbody.innerHTML = html;
  }

  // ======================== 运行日志 ========================

  function renderLogs() {
    var container = document.getElementById('logs');
    if (!container) return;
    var logs = D.logs || [];
    if (!logs.length) {
      container.innerHTML = '<div class="placeholder">暂无日志</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < logs.length; i++) {
      var l = logs[i];
      var lvlClass = 'lv-info';
      if (l.level === 'error') lvlClass = 'lv-error';
      else if (l.level === 'warn') lvlClass = 'lv-warn';
      html += '<div class="row"><span class="t">[' + (l.time || '') + ']</span> ';
      html += '<span class="' + lvlClass + '">[' + (l.level || '').toUpperCase() + ']</span> ';
      html += (l.event || '') + ': ' + (l.detail || '') + '</div>';
    }
    container.innerHTML = html;
  }

  function renderSources() {
    var el = document.getElementById('source');
    if (!el) return;
    el.textContent = D.source || '—';
  }

  // ======================== 北向资金 (Phase 9) ========================

  function renderNorthbound() {
    var summary = document.getElementById('northbound-stats');
    var nb = D.northbound;
    if (!nb || !nb.daily || !nb.daily.length) {
      if (summary) summary.innerHTML = '<div class="placeholder">暂无北向资金数据</div>';
      return;
    }
    if (summary) {
      var cls20 = nb.total_net_20d >= 0 ? 'up' : 'down';
      var cls5 = nb.avg_net_5d >= 0 ? 'up' : 'down';
      summary.innerHTML =
        '<div class="stat"><div class="k">20日累计</div><div class="v ' + cls20 + '">' + (nb.total_net_20d >= 0 ? '+' : '') + (nb.total_net_20d || 0).toFixed(1) + ' 亿</div></div>' +
        '<div class="stat"><div class="k">5日均值</div><div class="v ' + cls5 + '">' + (nb.avg_net_5d >= 0 ? '+' : '') + (nb.avg_net_5d || 0).toFixed(1) + ' 亿</div></div>' +
        '<div class="stat"><div class="k">连续净流入</div><div class="v">' + (nb.inflow_streak || 0) + ' 天</div></div>';
    }
    var viewEl = document.getElementById('sec-northbound');
    if (viewEl && !viewEl.classList.contains('active')) return;
    drawNorthboundChart();
  }

  function drawNorthboundChart() {
    var chartDom = document.getElementById('northbound-chart');
    if (!chartDom || !window.echarts) return;
    var nb = D.northbound;
    if (!nb || !nb.daily) return;
    var dates = [], flows = [], colors = [];
    for (var i = 0; i < nb.daily.length; i++) {
      dates.push((nb.daily[i].date || '').slice(5));
      flows.push(nb.daily[i].net_flow);
      colors.push(nb.daily[i].up ? '#f04848' : '#2ec27e');
    }
    if (chartInstances['sec-northbound']) chartInstances['sec-northbound'].dispose();
    var chart = window.echarts.init(chartDom);
    chart.setOption({
      grid: { top: 8, right: 16, bottom: 24, left: 50 },
      xAxis: { type: 'category', data: dates, axisLabel: { color: '#8b949e', fontSize: 11 } },
      yAxis: { type: 'value', axisLabel: { color: '#8b949e', formatter: '{value}亿' } },
      series: [{
        type: 'bar', data: flows,
        itemStyle: { color: function(p) { return colors[p.dataIndex]; } }
      }]
    });
    chartInstances['sec-northbound'] = chart;
    chartRendered['sec-northbound'] = true;
    window.addEventListener('resize', function() { chart.resize(); });
  }

  // ======================== 两市成交额 (Phase 10) ========================

  function renderTurnover() {
    var container = document.getElementById('turnover-display');
    if (!container) return;
    var to = D.turnover;
    if (!to || !to.total_yi) {
      container.innerHTML = '<div class="placeholder">暂无成交额数据</div>';
      return;
    }
    var yi = to.total_yi;
    var level = yi >= 10000 ? '🔥 极度活跃' : yi >= 8000 ? '📈 较为活跃' : yi >= 5000 ? '😐 一般' : '🥶 清淡';
    var barPct = Math.min(yi / 15000 * 100, 100);
    container.innerHTML =
      '<div><span class="turnover-big">' + (yi / 10000).toFixed(2) + '</span><span class="turnover-unit">万亿</span></div>' +
      '<div class="turnover-meta">' + level + ' · ' + (to.stock_count || '') + ' 只个股</div>' +
      '<div class="turnover-bar-wrap"><div class="turnover-bar-fill" style="width:' + barPct + '%"></div></div>';
  }

  // ======================== 板块热力图 (Phase 11) ========================

  function drawHeatmapChart() {
    var chartDom = document.getElementById('heatmap-chart');
    if (!chartDom || !window.echarts) return;
    var sectors = D.sectors || [];
    if (!sectors.length) {
      chartDom.innerHTML = '<div class="placeholder">暂无板块数据</div>';
      return;
    }
    var data = [];
    var upCount = 0, downCount = 0;
    for (var i = 0; i < sectors.length; i++) {
      var s = sectors[i];
      var absPct = Math.abs(s.change_pct || 0);
      data.push({
        name: s.name,
        value: Math.max(absPct * 10, 2),
        change_pct: s.change_pct,
        up: s.up
      });
      if (s.up) upCount++; else downCount++;
    }
    if (chartInstances['sec-heatmap']) chartInstances['sec-heatmap'].dispose();
    var chart = window.echarts.init(chartDom);
    chart.setOption({
      tooltip: {
        formatter: function(p) {
          return p.name + '<br/>涨跌幅: ' + (p.data.change_pct >= 0 ? '+' : '') + p.data.change_pct.toFixed(2) + '%';
        }
      },
      series: [{
        type: 'treemap',
        data: data,
        width: '100%', height: '100%',
        roam: false, nodeClick: false,
        breadcrumb: { show: false },
        label: {
          show: true, fontSize: 13,
          formatter: function(p) { return p.name + '\n' + (p.data.change_pct >= 0 ? '+' : '') + p.data.change_pct.toFixed(2) + '%'; }
        },
        itemStyle: {
          borderColor: '#0d1117', borderWidth: 2,
          color: function(p) {
            var v = p.data.change_pct || 0;
            var intensity = Math.min(Math.abs(v) / 5, 1);
            if (v >= 0) {
              var r = 240, g = Math.round(72 - 40 * intensity), b = Math.round(72 - 40 * intensity);
            } else {
              var r = Math.round(46 - 20 * intensity), g = Math.round(194 - 40 * intensity), b = Math.round(126 - 30 * intensity);
            }
            return 'rgb(' + r + ',' + g + ',' + b + ')';
          }
        }
      }]
    });
    chartInstances['sec-heatmap'] = chart;
    chartRendered['sec-heatmap'] = true;
    window.addEventListener('resize', function() { chart.resize(); });
  }

  // ======================== 商品期货 (Phase 12) ========================

  function renderCommodities() {
    var tbody = document.querySelector('#commodities-tbl tbody');
    if (!tbody) return;
    var comm = D.commodities || [];
    if (!comm.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="placeholder">暂无商品期货数据</td></tr>';
      return;
    }
    var html = '';
    for (var i = 0; i < comm.length; i++) {
      var c = comm[i];
      var cls = c.up ? 'up' : 'down';
      html += '<tr><td>' + c.name + '</td>';
      html += '<td class="num">' + (c.price != null ? c.price.toLocaleString('zh-CN') : '—') + '</td>';
      html += '<td class="num ' + cls + '" style="font-weight:600">' + (c.change_pct >= 0 ? '+' : '') + (c.change_pct || 0).toFixed(2) + '%</td></tr>';
    }
    tbody.innerHTML = html;
  }

  // ======================== 龙虎榜 (Phase 13) ========================

  function renderDragonTiger() {
    var statsEl = document.getElementById('dragontiger-stats');
    var tbody = document.querySelector('#dragontiger-tbl tbody');
    var dt = D.dragon_tiger;
    if (!dt || !dt.list || !dt.list.length) {
      if (statsEl) statsEl.innerHTML = '<div class="placeholder">暂无龙虎榜数据（今日无上榜个股或非交易日）</div>';
      if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="placeholder">暂无数据</td></tr>';
      return;
    }
    if (statsEl) {
      statsEl.innerHTML =
        '<div class="stat"><div class="k">上榜总数</div><div class="v">' + dt.total + '</div></div>' +
        '<div class="stat"><div class="k">上涨</div><div class="v up">' + (dt.up_count || 0) + '</div></div>' +
        '<div class="stat"><div class="k">下跌</div><div class="v down">' + (dt.down_count || 0) + '</div></div>';
    }
    if (tbody) {
      var html = '';
      for (var i = 0; i < dt.list.length; i++) {
        var d = dt.list[i];
        var cls = d.up ? 'up' : 'down';
        html += '<tr>';
        html += '<td>' + d.name + ' <span class="code">' + (d.code || '') + '</span></td>';
        html += '<td class="num">' + (d.price != null ? d.price.toFixed(2) : '—') + '</td>';
        html += '<td class="num ' + cls + '" style="font-weight:600">' + (d.change_pct >= 0 ? '+' : '') + (d.change_pct || 0).toFixed(2) + '%</td>';
        html += '<td class="num ' + ((d.net_buy || 0) >= 0 ? 'up' : 'down') + '">' + (d.net_buy >= 0 ? '+' : '') + (d.net_buy || 0).toFixed(0) + '</td>';
        html += '<td style="font-size:12px;color:var(--muted)">' + (d.reason || '—') + '</td>';
        html += '</tr>';
      }
      tbody.innerHTML = html;
    }
  }

  // ======================== 国债收益率 (Phase 14) ========================

  function renderTreasury() {
    var viewEl = document.getElementById('sec-treasury');
    if (viewEl && !viewEl.classList.contains('active')) return;
    drawTreasuryChart();
  }

  function drawTreasuryChart() {
    var chartDom = document.getElementById('treasury-chart');
    if (!chartDom || !window.echarts) return;
    var tr = D.treasury;
    if (!tr || !tr.yields || !Object.keys(tr.yields).length) {
      chartDom.innerHTML = '<div class="placeholder">暂无国债收益率数据</div>';
      return;
    }
    var yields = tr.yields;
    var order = ['3M', '6M', '1Y', '2Y', '5Y', '10Y', '30Y'];
    var tenors = [], values = [];
    for (var i = 0; i < order.length; i++) {
      if (yields[order[i]] != null) {
        tenors.push(order[i]);
        values.push(yields[order[i]]);
      }
    }
    if (chartInstances['sec-treasury']) chartInstances['sec-treasury'].dispose();
    var chart = window.echarts.init(chartDom);
    chart.setOption({
      grid: { top: 8, right: 16, bottom: 24, left: 48 },
      xAxis: { type: 'category', data: tenors, axisLabel: { color: '#8b949e', fontSize: 12 } },
      yAxis: { type: 'value', axisLabel: { color: '#8b949e', formatter: '{value}%' }, min: function(v) { return v.min - 0.3; } },
      series: [{
        type: 'line', data: values, smooth: true,
        lineStyle: { color: '#58a6ff', width: 3 },
        itemStyle: { color: '#58a6ff' },
        symbol: 'circle', symbolSize: 8,
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(88,166,255,0.25)' }, { offset: 1, color: 'rgba(88,166,255,0)' }
        ])},
        markLine: tr.curve_inverted ? { silent: true, symbol: 'none', lineStyle: { color: '#f04848', type: 'dashed' }, label: { formatter: '⚠ 曲线倒挂', color: '#f04848', fontSize: 11 }, data: [{ yAxis: values[values.length-1] }] } : undefined
      }]
    });
    chartInstances['sec-treasury'] = chart;
    chartRendered['sec-treasury'] = true;
    window.addEventListener('resize', function() { chart.resize(); });
  }

  // ======================== 沪深300估值 (Phase 15) ========================

  function renderCsi300Val() {
    var container = document.getElementById('csi300val-display');
    if (!container) return;
    var cv = D.csi300_val;
    if (!cv || cv.pe == null) {
      container.innerHTML = '<div class="placeholder">暂无估值数据</div>';
      return;
    }
    // PE 分位
    var peLvl = (cv.pe_percentile || 0) >= 70 ? 'high' : (cv.pe_percentile || 0) <= 30 ? 'low' : 'mid';
    var peLabel = (cv.pe_percentile || 0) >= 70 ? '偏高' : (cv.pe_percentile || 0) <= 30 ? '偏低' : '适中';
    // PB 分位
    var pbLvl = (cv.pb_percentile || 0) >= 70 ? 'high' : (cv.pb_percentile || 0) <= 30 ? 'low' : 'mid';
    var pbLabel = (cv.pb_percentile || 0) >= 70 ? '偏高' : (cv.pb_percentile || 0) <= 30 ? '偏低' : '适中';

    container.innerHTML =
      '<div class="csi300-card">' +
        '<div class="metric-name">市盈率 PE</div>' +
        '<div class="metric-val">' + cv.pe.toFixed(2) + '</div>' +
        '<div class="metric-pct ' + peLvl + '">历史分位 ' + (cv.pe_percentile || '—') + '% <span>(' + peLabel + ')</span></div>' +
        '<div class="csi300-gauge"><div class="fill" style="width:' + (cv.pe_percentile || 50) + '%"></div></div>' +
      '</div>' +
      '<div class="csi300-card">' +
        '<div class="metric-name">市净率 PB</div>' +
        '<div class="metric-val">' + cv.pb.toFixed(2) + '</div>' +
        '<div class="metric-pct ' + pbLvl + '">历史分位 ' + (cv.pb_percentile || '—') + '% <span>(' + pbLabel + ')</span></div>' +
        '<div class="csi300-gauge"><div class="fill" style="width:' + (cv.pb_percentile || 50) + '%"></div></div>' +
      '</div>';
  }

  // ======================== 可转债 (Phase 16) ========================

  function renderConvertibleBonds() {
    var statsEl = document.getElementById('cb-stats');
    var tbody = document.querySelector('#cb-tbl tbody');
    var cb = D.convertible_bonds;
    if (!cb || !cb.list || !cb.list.length) {
      if (statsEl) statsEl.innerHTML = '<div class="placeholder">暂无可转债数据</div>';
      if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="placeholder">暂无数据</td></tr>';
      return;
    }
    if (statsEl) {
      statsEl.innerHTML =
        '<div class="stat"><div class="k">转债数量</div><div class="v">' + cb.total_count + '</div></div>' +
        '<div class="stat"><div class="k">上涨</div><div class="v up">' + (cb.up_count || 0) + '</div></div>' +
        '<div class="stat"><div class="k">下跌</div><div class="v down">' + (cb.down_count || 0) + '</div></div>' +
        '<div class="stat"><div class="k">均价</div><div class="v">¥' + (cb.avg_price || 0).toFixed(1) + '</div></div>';
    }
    if (tbody) {
      var html = '';
      for (var i = 0; i < cb.list.length; i++) {
        var c = cb.list[i];
        var cls = c.up ? 'up' : 'down';
        html += '<tr>';
        html += '<td>' + c.name + '</td>';
        html += '<td class="num" style="font-weight:600">' + (c.price != null ? c.price.toFixed(2) : '—') + '</td>';
        html += '<td class="num">' + (c.premium_rt != null ? (c.premium_rt >= 0 ? '+' : '') + c.premium_rt.toFixed(1) + '%' : '—') + '</td>';
        html += '<td class="num" style="color:var(--accent);font-weight:600">' + (c.double_low != null ? c.double_low.toFixed(1) : '—') + '</td>';
        html += '<td class="num ' + cls + '" style="font-weight:600">' + (c.change_pct != null ? (c.change_pct >= 0 ? '+' : '') + c.change_pct.toFixed(2) + '%' : '—') + '</td>';
        html += '</tr>';
      }
      tbody.innerHTML = html;
    }
  }

  // ======================== 图表懒激活 ========================

  function onViewActivate(viewId) {
    // 历史走势图
    if (viewId === 'sec-history' && !chartRendered['sec-history']) {
      var history = D.history || [];
      if (history.length) { drawHistoryChartOrFallback(); }
    }
    // 行业板块图
    if (viewId === 'sec-sectors' && !chartRendered['sec-sectors']) {
      var sectors = D.sectors || [];
      if (sectors.length) { drawSectorChartOrFallback(); }
    }
    // 北向资金图
    if (viewId === 'sec-northbound' && !chartRendered['sec-northbound']) {
      var nb = D.northbound;
      if (nb && nb.daily && nb.daily.length) { drawNorthboundChart(); }
    }
    // 热力图
    if (viewId === 'sec-heatmap' && !chartRendered['sec-heatmap']) {
      var sectors2 = D.sectors || [];
      if (sectors2.length) { drawHeatmapChart(); }
    }
    // 国债收益率图
    if (viewId === 'sec-treasury' && !chartRendered['sec-treasury']) {
      var tr = D.treasury;
      if (tr && tr.yields && Object.keys(tr.yields).length) { drawTreasuryChart(); }
    }
    // 已渲染过的图表: resize
    if (chartInstances[viewId]) {
      setTimeout(function() { chartInstances[viewId].resize(); }, 50);
    }
    // 投资组合 Chart.js — 懒初始化（由 automation-enhance.js 管理）
    if (viewId === 'sec-portfolio') {
      setTimeout(function() {
        if (window._drawPortfolioChart) { window._drawPortfolioChart(); }
      }, 100);
    }
  }

  // ======================== 抽屉导航 ========================

  function initDrawer() {
    var drawer = document.getElementById('drawer');
    var menuBtn = document.getElementById('menuBtn');
    var overlay = document.getElementById('overlay');
    var links = drawer ? drawer.querySelectorAll('a[data-target]') : [];
    var views = document.querySelectorAll('.view');

    function closeDrawer() {
      if (drawer) drawer.classList.remove('open');
      if (overlay) overlay.classList.remove('show');
    }

    function openDrawer() {
      if (drawer) drawer.classList.add('open');
      if (overlay) overlay.classList.add('show');
    }

    if (menuBtn) {
      menuBtn.addEventListener('click', function() {
        if (drawer && drawer.classList.contains('open')) closeDrawer();
        else openDrawer();
      });
    }

    if (overlay) {
      overlay.addEventListener('click', closeDrawer);
    }

    // 点击导航项
    for (var i = 0; i < links.length; i++) {
      links[i].addEventListener('click', function(e) {
        e.preventDefault();
        var targetId = this.getAttribute('data-target');
        // 显示目标视图
        for (var j = 0; j < views.length; j++) {
          views[j].classList.remove('active');
        }
        var target = document.getElementById(targetId);
        if (target) target.classList.add('active');
        // 高亮导航
        for (var k = 0; k < links.length; k++) {
          links[k].classList.remove('active');
        }
        this.classList.add('active');
        // 窄屏关抽屉
        closeDrawer();
        // 懒加载/重绘该视图的图表
        onViewActivate(targetId);
        // 滚动到视图
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        // 更新 hash
        window.location.hash = targetId;
      });
    }

    // 初始 hash
    var hash = window.location.hash;
    if (hash) {
      var activeLink = drawer ? drawer.querySelector('a[data-target="' + hash.slice(1) + '"]') : null;
      if (activeLink) activeLink.click();
    } else {
      // 默认显示 overview
      var firstLink = drawer ? drawer.querySelector('a[data-target]') : null;
      if (firstLink) firstLink.click();
    }
  }

  // ======================== 主题切换 ========================

  function initThemeToggle() {
    var btn = document.getElementById('themeToggle');
    if (!btn) return;
    // 从 localStorage 读取之前保存的主题
    var saved = localStorage.getItem('finance-site-theme');
    if (saved === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
      btn.textContent = '☀️';
    }
    btn.addEventListener('click', function() {
      var current = document.documentElement.getAttribute('data-theme');
      if (current === 'light') {
        document.documentElement.removeAttribute('data-theme');
        btn.textContent = '🌙';
        localStorage.setItem('finance-site-theme', 'dark');
      } else {
        document.documentElement.setAttribute('data-theme', 'light');
        btn.textContent = '☀️';
        localStorage.setItem('finance-site-theme', 'light');
      }
      // 重绘 ECharts 图表以适配新主题
      setTimeout(function() {
        Object.keys(chartInstances).forEach(function(key) {
          if (chartInstances[key] && !chartInstances[key].isDisposed()) {
            chartInstances[key].resize();
          }
        });
      }, 100);
    });
  }

  // ======================== CSV 导出 ========================

  function csvEscape(val) {
    if (val == null) return '';
    var s = String(val);
    if (s.includes(',') || s.includes('"') || s.includes('\n')) {
      return '"' + s.replace(/"/g, '""') + '"';
    }
    return s;
  }

  function downloadCSV(filename, headers, rows) {
    var csv = headers.map(csvEscape).join(',') + '\n';
    for (var i = 0; i < rows.length; i++) {
      csv += rows[i].map(csvEscape).join(',') + '\n';
    }
    var blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
  }

  function initExportButtons() {
    // 为每个数据板块自动添加导出按钮
    var exportTargets = [
      { sectionId: 'sec-commodities', tableQuery: '#commodities-tbl', filename: 'commodities.csv', headers: ['品种', '最新价', '涨跌幅'] },
      { sectionId: 'sec-dragontiger', tableQuery: '#dragontiger-tbl', filename: 'dragontiger.csv', headers: ['股票', '代码', '收盘价', '涨跌幅', '净买入(万)', '上榜原因'] },
      { sectionId: 'sec-cb', tableQuery: '#cb-tbl', filename: 'convertible_bonds.csv', headers: ['转债名称', '价格', '溢价率', '双低值', '涨跌幅'] },
      { sectionId: 'sec-funds', tableQuery: '#funds', filename: 'funds.csv', headers: ['基金', '代码', '单位净值', '日增长率'] },
      { sectionId: 'sec-fx', tableQuery: '#fx', filename: 'fx.csv', headers: ['货币', '现汇买入价', '现汇卖出价'] }
    ];

    for (var i = 0; i < exportTargets.length; i++) {
      var t = exportTargets[i];
      var section = document.getElementById(t.sectionId);
      if (!section) continue;
      var h2 = section.querySelector('h2');
      if (!h2) continue;
      // 避免重复添加
      if (h2.querySelector('.btn-export')) continue;
      var btn = document.createElement('button');
      btn.className = 'btn-export';
      btn.textContent = '📥 CSV';
      btn.title = '导出为 CSV 文件';
      btn.addEventListener('click', function(target) {
        return function(e) {
          e.stopPropagation();
          var table = document.querySelector(target.tableQuery);
          if (!table) return;
          var rows = [];
          var tbody = table.querySelector('tbody');
          var trs = tbody ? tbody.querySelectorAll('tr') : table.querySelectorAll('tr');
          for (var j = 0; j < trs.length; j++) {
            var cells = trs[j].querySelectorAll('td, th');
            var row = [];
            for (var k = 0; k < cells.length; k++) {
              row.push((cells[k].textContent || '').replace(/\s+/g, ' ').trim());
            }
            if (row.length > 0 && row[0] !== '暂无数据') rows.push(row.slice(0, target.headers.length));
          }
          if (rows.length) downloadCSV(target.filename, target.headers, rows);
        };
      }(t));
      h2.appendChild(btn);
    }
  }

  // ======================== 键盘快捷键 ========================

  function initKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
      // 如果焦点在输入框内，不触发快捷键
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;

      var sectionMap = {
        '1': 'sec-overview',
        '2': 'sec-commentary',
        '3': 'sec-indices',
        '4': 'sec-history',
        '5': 'sec-sectors',
        '6': 'sec-breadth',
        '7': 'sec-movers',
        '8': 'sec-fx',
        '9': 'sec-global',
        '0': 'sec-funds',
        'q': 'sec-northbound',
        'w': 'sec-turnover',
        'e': 'sec-heatmap',
        'r': 'sec-commodities',
        't': 'sec-dragontiger',
        'y': 'sec-treasury',
        'u': 'sec-csi300val',
        'i': 'sec-cb',
        'o': 'sec-portfolio',
        'p': 'sec-automation',
        'l': 'sec-logs'
      };

      var targetId = sectionMap[e.key.toLowerCase()];
      if (!targetId) return;

      e.preventDefault();
      var link = document.querySelector('a[data-target="' + targetId + '"]');
      if (link) link.click();
    });
  }

  function initKbdHint() {
    var hint = document.createElement('div');
    hint.className = 'kbd-hint';
    hint.id = 'kbdHint';
    hint.innerHTML = '⌨ <kbd>1-9</kbd><kbd>0</kbd><kbd>q</kbd>-<kbd>p</kbd> 快速跳转';
    document.body.appendChild(hint);
    // 5 秒后渐隐（但仍可交互）
    setTimeout(function() { hint.style.opacity = '0.25'; }, 8000);
  }

  // ======================== 启动 ========================

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
