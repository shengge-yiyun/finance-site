# 每日金融观察 · 自动化金融情报中心（Phase 1–8）

一个**完全自动化**的个人金融信息聚合站：由 Python 智能体每交易日自动从网络抓取金融数据，前端静态页面展示，无需后端服务器。

网站只是自动化流水线的展示窗口，**真正的考点是「无人值守 + 容错 + 专业解读」**。

> Phase 1–8 全部完成：AKShare 三大指数 + 多源 RSS 资讯 + 行业板块(ECharts/纯CSS降级) + 市场宽度 + 个股动向 + 外汇牌价 + 环球股指 + 基金排行 + 历史沉淀 + 自动化盘面简评 + 自动化引擎面板 + 模拟持仓。
>
> **界面采用「左侧抽屉式导航」**，桌面端左侧固定目录、点击平滑跳转；窄屏收起为汉堡菜单。

## 目录结构

```
finance-agent-homepage/
├── index.html                        # 前端页面（单页应用，12 个板块）
├── data.js                           # 由 fetch_data.py 自动生成的数据
├── css/style.css                     # 全站样式（深色终端美学）
├── js/
│   ├── app.js                        # 前端渲染引擎（Phase 1–8）
│   └── automation-enhance.js         # 自动化引擎面板 + 持仓环形图
├── lib/chart.umd.min.js              # Chart.js（离线可用）
├── assets/favicon.svg                # 网站图标
├── agent/
│   ├── fetch_data.py                 # ★ 核心采集脚本（Phase 1–8 + 容错降级）
│   ├── generate_demo_data.py         # 离线演示数据生成器
│   └── requirements.txt              # Python 依赖
├── data/
│   └── portfolio.json                # 模拟持仓数据
├── .github/workflows/update.yml      # GitHub Actions 定时任务 + 告警
├── .gitignore
└── README.md
```

## 本地验证

```bash
# 方法 1：直接浏览器打开（数据已预置在 data.js 中）
start index.html

# 方法 2：重新生成演示数据
python agent/generate_demo_data.py

# 方法 3：运行真实采集（需网络 + akshare）
python -m pip install -r agent/requirements.txt
python agent/fetch_data.py

# 方法 4：本地 HTTP 服务器预览
python -m http.server 8000
# 浏览器打开 http://localhost:8000
```

## 推送到 GitHub 并跑起来

1. 在 GitHub 上 **New repository**
2. 推送代码：
   ```bash
   cd finance-agent-homepage
   git init && git add -A && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<用户名>/<仓库名>.git
   git push -u origin main
   ```
3. **开启 Pages**：仓库 `Settings → Pages → Source` 选 **Deploy from a branch**，Branch 选 **main**，目录选 **/ (root)**，保存
4. **开启写权限**：`Settings → Actions → General → Workflow permissions` 选 **Read and write permissions**
5. 立即验证：`Actions` → `Daily Finance Update` → **Run workflow** 手动跑一次

## 定时说明

- `cron: '0 8 * * 1-5'` 是 **UTC** 时间，对应**北京时间周一至周五 16:00**
- 别写成 `0 16 * * *`，那是北京凌晨 0 点

## 板块清单

| # | 板块 | 内容 | 数据源 |
|---|------|------|--------|
| 1 | 今日观察 | 运行状态 + 财经快讯（多源 RSS 去重） | RSS + AKShare |
| 2 | 今日盘面简评 | 自动推导的结构化市场解读 | 算法推导 |
| 3 | A股三大指数 | 上证/深证/创业板（红涨绿跌） | AKShare |
| 4 | 指数历史走势 | 上证每日涨跌幅柱状图 | 历史累积 |
| 5 | 行业板块强弱 | ECharts 横向柱状图（纯CSS降级） | AKShare |
| 6 | 市场宽度 | 涨跌家数 + 涨停跌停（多空温度计） | AKShare |
| 7 | 个股动向 | 领涨/领跌 TOP10 | AKShare |
| 8 | 外汇牌价 | 中国银行实时牌价 | AKShare |
| 9 | 环球股指 | 港股/美股/日股 | AKShare |
| 10 | 基金净值排行 | 开放式基金 TOP10 | AKShare |
| 11 | 🤖 自动化引擎 | 状态灯 + 终端日志 + 倒计时 + 手动触发 | — |
| 12 | 自动化运行日志 | 历次运行详情 | 采集脚本 |

## 容错设计（核心得分点）

- 采集脚本核心逻辑**纯标准库**；真实行情经 AKShare 接入，装不上/接口挂都自动降级
- 任何一步失败 → `status: degraded` 而非进程崩溃，**页面永远有内容、绝不白屏**
- 脚本退出码恒为 0，真正的失败通过 `status` 字段体现
- ECharts CDN 加载失败 → 自动降级为纯 CSS 柱状图
- RSS 多源并联抓取，单源失败只记 warn 日志，不影响其他源
- **失败自动告警**：`degraded` 自动开 Issue，`ok` 自动关闭告警（自愈）

> 自动化的本质不是让程序跑起来，而是让程序在你不在场时也能正确地失败。
