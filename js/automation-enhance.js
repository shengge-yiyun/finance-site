/**
 * automation-enhance.js — 自动化引擎面板 + 投资组合增强
 * =========================================================
 * 在 Phase 1-8 基础上新增:
 *   1. 自动化状态监控 (脉动灯 + 终端日志 + 倒计时)
 *   2. 手动触发模拟 (演示完整 Agent 流程)
 *   3. 投资组合环形图 (Chart.js)
 *
 * 依赖: lib/chart.umd.min.js, data.js (window.__SITE_DATA__)
 */
(function() {
  'use strict';

  var D = null;
  var runInProgress = false;
  var countdownTimer = null;

  // ======================== 初始化 ========================

  function init() {
    D = window.__SITE_DATA__;
    if (!D) return;

    updateAutoStatus();
    renderPortfolio();
    bindRunButton();
    startCountdown();
    populateTerminal();
  }

  // ======================== 自动化状态 ========================

  function updateAutoStatus() {
    var dot = document.getElementById('autoDot');
    var label = document.getElementById('autoLabel');
    var lastEl = document.getElementById('lastRunTime');
    var totalEl = document.getElementById('totalRuns');

    if (!dot || !label) return;

    if (D.status === 'ok') {
      dot.className = 'auto-dot pulse';
      label.textContent = 'Agent Active';
    } else if (D.status === 'degraded') {
      dot.className = 'auto-dot warn';
      label.textContent = 'Agent Degraded';
    } else {
      dot.className = 'auto-dot off';
      label.textContent = 'Agent Error';
    }

    if (lastEl) lastEl.textContent = D.updated_at || '—';

    var stats = D.run_stats || {};
    if (totalEl) totalEl.textContent = (stats.total_days || 0) + ' 天';
  }

  function populateTerminal() {
    var body = document.getElementById('terminalBody');
    if (!body) return;

    var logs = D.logs || [];
    if (!logs.length) {
      body.innerHTML = '<span class="log-dim">暂无运行记录。点击「立即运行」触发首次采集。</span>';
      return;
    }

    // 取最近 10 条
    var recent = logs.slice(-10);
    var html = '';
    for (var i = 0; i < recent.length; i++) {
      var l = recent[i];
      var ts = (l.time || '').slice(-8);
      var lvlClass = 'log-info';
      var icon = '●';

      if (l.level === 'error') { lvlClass = 'log-err'; icon = '✗'; }
      else if (l.level === 'warn') { lvlClass = 'log-warn'; icon = '⚠'; }
      else if (l.event && l.event.indexOf('fetched') >= 0) { lvlClass = 'log-ok'; icon = '✓'; }

      html += '<span class="log-ts">[' + ts + ']</span> ';
      html += '<span class="' + lvlClass + '">' + icon + ' ' + (l.event || '') + '</span>';
      html += ' <span class="log-dim">' + (l.detail || '') + '</span>\n';
    }
    body.innerHTML = html || '<span class="log-dim">等待首次运行...</span>';
    body.scrollTop = body.scrollHeight;
  }

  // ======================== 倒计时 ========================

  function startCountdown() {
    if (countdownTimer) clearTimeout(countdownTimer);

    var nextEl = document.getElementById('nextRunTime');
    var cdEl = document.getElementById('countdown');

    function tick() {
      var now = new Date();
      var next = new Date(now);
      next.setHours(8, 0, 0, 0); // 每天 08:00

      if (next <= now) {
        next.setDate(next.getDate() + 1);
      }

      // 周末跳到周一
      if (next.getDay() === 6) next.setDate(next.getDate() + 2);
      if (next.getDay() === 0) next.setDate(next.getDate() + 1);

      if (nextEl) {
        nextEl.textContent = next.toLocaleDateString('zh-CN') + ' ' +
          next.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
      }

      var diff = next - now;
      if (diff <= 0) { tick(); return; }

      var h = Math.floor(diff / 3600000);
      var m = Math.floor((diff % 3600000) / 60000);
      var s = Math.floor((diff % 60000) / 1000);

      if (cdEl) {
        cdEl.textContent =
          String(h).padStart(2, '0') + ':' +
          String(m).padStart(2, '0') + ':' +
          String(s).padStart(2, '0');
      }
      countdownTimer = setTimeout(tick, 1000);
    }
    tick();
  }

  // ======================== 手动运行 ========================

  function bindRunButton() {
    var btn = document.getElementById('btnRunAgent');
    if (btn) btn.addEventListener('click', simulateRun);
  }

  function terminalLog(msg, type) {
    var body = document.getElementById('terminalBody');
    if (!body) return;
    type = type || 'info';
    var cssClass = 'log-' + type;
    var now = new Date();
    var ts = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    if (body.querySelector('.log-dim') && body.querySelector('.log-dim').textContent.indexOf('暂无') >= 0) {
      body.innerHTML = '';
    }

    body.innerHTML += '<span class="log-ts">[' + ts + ']</span> <span class="' + cssClass + '">' + msg + '</span>\n';
    body.scrollTop = body.scrollHeight;

    var lines = body.innerHTML.split('\n');
    if (lines.length > 30) {
      body.innerHTML = lines.slice(-30).join('\n');
    }
  }

  function simulateRun() {
    if (runInProgress) return;
    runInProgress = true;

    var btn = document.getElementById('btnRunAgent');
    var progress = document.getElementById('runProgress');
    var fill = document.getElementById('progressFill');
    var step = document.getElementById('progressStep');

    if (btn) { btn.disabled = true; btn.textContent = '运行中...'; }
    if (progress) progress.style.display = 'block';

    terminalLog('=== 手动触发数据采集 ===', 'info');

    var steps = [
      { pct: 12,  msg: '连接 AKShare 数据源...',           delay: 500 },
      { pct: 25,  msg: '采集 A 股三大指数...',              delay: 600 },
      { pct: 38,  msg: '抓取行业板块强弱...',              delay: 600 },
      { pct: 50,  msg: '计算市场宽度 + 个股动向...',        delay: 700 },
      { pct: 62,  msg: '获取外汇牌价...',                  delay: 500 },
      { pct: 75,  msg: '采集环球股指 + 基金排行...',        delay: 600 },
      { pct: 88,  msg: '生成盘面简评 + 去重新闻...',        delay: 700 },
      { pct: 100, msg: '写入 data.js + 更新日志...完成!',   delay: 500 }
    ];

    var i = 0;
    function nextStep() {
      if (i < steps.length) {
        var s = steps[i];
        if (fill) fill.style.width = s.pct + '%';
        if (step) step.textContent = '[' + s.pct + '%] ' + s.msg;
        terminalLog(s.msg, 'info');
        i++;
        setTimeout(nextStep, s.delay);
      } else {
        terminalLog('✓ 全部任务完成，数据已更新', 'ok');
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M4 2v12l10-6L4 2z" fill="currentColor"/></svg> 立即运行';
        }

        // 重置状态
        setTimeout(function() {
          var dot = document.getElementById('autoDot');
          var label = document.getElementById('autoLabel');
          if (dot) { dot.className = 'auto-dot pulse'; }
          if (label) { label.textContent = 'Agent Active'; }
          if (progress) {
            setTimeout(function() {
              progress.style.display = 'none';
              if (fill) fill.style.width = '0%';
            }, 1500);
          }
          runInProgress = false;
        }, 300);
      }
    }
    nextStep();
  }

  // ======================== 投资组合 ========================

  var _portfolioData = null; // 缓存，等视图可见时再画图

  function renderPortfolio() {
    var portfolio = D.portfolio;
    if (!portfolio || !portfolio.holdings) {
      loadPortfolioFromJSON();
      return;
    }
    _portfolioData = portfolio;
    drawPortfolioSummary(portfolio);
    // 图表延迟到视图激活时再画
    tryDrawPortfolioChart();
  }

  function loadPortfolioFromJSON() {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', 'data/portfolio.json', true);
    xhr.onload = function() {
      if (xhr.status === 200) {
        try {
          var p = JSON.parse(xhr.responseText);
          _portfolioData = p;
          drawPortfolioSummary(p);
          tryDrawPortfolioChart();
        } catch(e) {}
      } else {
        showEmptyPortfolio();
      }
    };
    xhr.onerror = function() { showEmptyPortfolio(); };
    xhr.send();
  }

  /** 只在视图可见时才画 Chart.js 图表 */
  function tryDrawPortfolioChart() {
    if (!_portfolioData) return;
    var viewEl = document.getElementById('sec-portfolio');
    if (!viewEl || !viewEl.classList.contains('active')) return;
    drawPortfolioChart(_portfolioData);
  }

  /** 暴露给 app.js 的 onViewActivate 调用 */
  window._drawPortfolioChart = function() {
    if (_portfolioData) {
      drawPortfolioChart(_portfolioData);
    }
  };

  function showEmptyPortfolio() {
    var summary = document.getElementById('portfolioSummary');
    if (summary) {
      summary.innerHTML = '<div class="placeholder">模拟持仓数据未加载。运行 <code>python agent/generate_demo_data.py</code> 生成。</div>';
    }
  }

  /** 只渲染摘要文字，不依赖视图可见性 */
  function drawPortfolioSummary(p) {
    var summary = document.getElementById('portfolioSummary');
    if (!summary) return;
    var tv = p.total_value || 0;
    var dc = p.day_change || 0;
    var dp = p.day_change_pct || 0;
    var clsD = dp >= 0 ? 'up' : 'down';
    var tr = p.total_return_pct || 0;
    var clsT = tr >= 0 ? 'up' : 'down';
    summary.innerHTML =
      '<div class="portfolio-stat"><div class="stat-label">总资产</div><div class="stat-value">¥' + tv.toLocaleString('zh-CN') + '</div></div>' +
      '<div class="portfolio-stat"><div class="stat-label">今日盈亏</div><div class="stat-value ' + clsD + '">' + (dp >= 0 ? '▲' : '▼') + ' ¥' + Math.abs(dc).toLocaleString('zh-CN') + '</div></div>' +
      '<div class="portfolio-stat"><div class="stat-label">累计收益</div><div class="stat-value ' + clsT + '">' + (tr >= 0 ? '+' : '') + tr.toFixed(2) + '%</div></div>';
  }

  /** 画 Chart.js 环形图 — 只在视图可见时调用 */
  function drawPortfolioChart(p) {
    drawPortfolioSummary(p);

    var canvas = document.getElementById('portfolioChart');
    if (!canvas || !window.Chart) return;
    var holdings = p.holdings || [];
    if (!holdings.length) return;

    // 销毁旧实例
    if (canvas._chartInstance) { canvas._chartInstance.destroy(); }

    var colors = ['#3b82f6', '#06b6d4', '#f04848', '#d4a853', '#8b5cf6', '#2ec27e', '#f97316', '#ec4899'];
    var labels = [], data = [], bgColors = [];
    for (var i = 0; i < holdings.length; i++) {
      labels.push(holdings[i].name || holdings[i].code || '—');
      data.push(holdings[i].market_value || holdings[i].weight_pct || 0);
      bgColors.push(colors[i % colors.length]);
    }

    canvas._chartInstance = new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{ data: data, backgroundColor: bgColors, borderColor: '#161b22', borderWidth: 2 }]
      },
      options: {
        responsive: true, maintainAspectRatio: true, cutout: '60%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: { color: '#8b949e', font: { family: "'PingFang SC','Microsoft YaHei',sans-serif", size: 10 }, padding: 12, usePointStyle: true, pointStyleWidth: 6 }
          },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                var total = ctx.dataset.data.reduce(function(a, b) { return a + b; }, 0);
                var pct = total > 0 ? (ctx.raw / total * 100).toFixed(1) : 0;
                return ' ' + ctx.label + ': ¥' + ctx.raw.toLocaleString('zh-CN') + ' (' + pct + '%)';
              }
            }
          }
        }
      }
    });
  }


  // ======================== 启动 ========================

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    // 稍等 app.js 完成初始化
    setTimeout(init, 200);
  }
})();
