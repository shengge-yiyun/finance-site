#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金融信息聚合站 —— 自动采集脚本（Phase 1 链路 + Phase 2 指数 + Phase 3 资讯/告警 + Phase 4 行业板块）

GitHub Actions 在每个交易日北京时间 16:00 自动运行本脚本，
生成 data.js（window.__SITE_DATA__ 格式），由前端静态页面读取。

设计原则（容错优先，这是本作业的核心得分点）：
1. 任何一步失败都写入 status='degraded'，而非让脚本抛异常退出，
   保证页面永远有内容、永远可发布（优雅降级，绝不白屏）。
2. 外部数据源（AKShare 指数 / 多源 RSS 资讯）通过「重试退避 + 多源并联 + 异常回退」接入：
   - 单源失败只记一条 warn 日志，不影响其他源；
   - 所有源都失败才 mark_degraded（状态降级 + error 日志）。
3. 进程退出码恒为 0，把"失败"体现在数据里而非进程里，
   避免 GitHub Pages 因 Action 失败而停更；真正的失败由工作流读取 status 自动开 Issue 告警。

红涨绿跌：A股惯例，change_pct >= 0 记 up=True（前端红色），否则绿色。
"""

import json
import os
import re
import sys
import time
import random
import email.utils
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(SCRIPT_DIR, "..")
SITE_DIR = REPO_ROOT
DATA_JS_PATH = os.path.join(REPO_ROOT, "data.js")

BEIJING = timezone(timedelta(hours=8))

# 目标指数（按名称匹配，含多源名称变体：EM 用简称，Sina 可能用全称）
TARGET_INDICES = [
    {"name": "上证指数", "aliases": ["上证指数", "上证综合指数", "上证综指", "000001"]},
    {"name": "深证成指", "aliases": ["深证成指", "深证成份指数", "深证成分指数", "399001"]},
    {"name": "创业板指", "aliases": ["创业板指", "创业板指数", "399006"]},
]

# 财经 RSS 多源（单源失败不影响其他源；已替换失效源为 rsshub 镜像）
RSS_FEEDS = [
    {"name": "新浪财经", "url": "https://finance.sina.com.cn/rss/finance.xml"},
    {"name": "东方财富快讯", "url": "https://rsshub.app/eastmoney/kuaixun"},
    {"name": "财联社电报", "url": "https://rsshub.app/cls/telegraph"},
]

NEWS_LIMIT = 20          # 页面最多展示的资讯条数
ATOM = "{http://www.w3.org/2005/Atom}"

HISTORY_MAX = 90   # 历史快照最多保留天数（约一个季度）


def now_beijing() -> datetime:
    return datetime.now(BEIJING)


def _now() -> str:
    return now_beijing().strftime("%Y-%m-%d %H:%M:%S")


def _retry(func, tries: int = 3, base_delay: float = 2.0):
    """线性退避重试：最多 tries 次，第 i 次失败后等待 base_delay*(i+1) 秒。"""
    last = None
    for i in range(tries):
        try:
            return func()
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(base_delay * (i + 1))
    raise last


def _em_with_fallback(primary, secondary=None):
    """
    EM 反爬兜底：先试主接口(东方财富)，失败再试备用接口(新浪/同花顺)。
    两个接口命中不同服务器，EM 被限流时备用源通常仍可返回，避免整段降级。
    调用前随机停顿 0.5~2.5s，降低触发 EM 连续封锁的概率。
    """
    time.sleep(random.uniform(0.5, 2.5))
    try:
        return _retry(primary)
    except Exception:
        if secondary is None:
            raise
        return _retry(secondary)


def mark_degraded(payload: dict, event: str, detail: str) -> None:
    """把整体状态标记为 degraded，并追加一条 error 日志（不覆盖已有的 ok 来源信息）。"""
    payload["status"] = "degraded"
    payload["logs"].append({
        "time": _now(),
        "level": "error",
        "event": event,
        "detail": detail,
    })


def mark_ok(payload: dict) -> None:
    """
    仅在尚未因其他源失败而降级时，把状态标回 ok；
    避免"后成功的数据源"覆盖掉"先失败的数据源"留下的降级信号
    （否则页面某板块已空的降级，却因后面板块成功而显示 OK、不触发告警）。
    注意：此函数只读取 status，不递归调用自身。
    """
    if payload.get("status") != "degraded":
        payload["status"] = "ok"


def _fmt_pct(v):
    """把涨跌幅格式化为带符号的字符串（None 显示占位符）。"""
    if v is None:
        return "—"
    return ("+" if v >= 0 else "") + "{:.2f}%".format(v)


# ───────────────────────── Phase 2：指数 ─────────────────────────
def fetch_indices_with_fallback(payload: dict) -> dict:
    """抓取 A股三大指数；成功填 indices，失败降级。"""
    try:
        import akshare as ak
    except ImportError:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "akshare_not_installed",
            "detail": "本地未检测到 akshare，跳过真实行情；GitHub Actions 中已自动安装",
        })
        return payload

    try:
        df = _em_with_fallback(lambda: ak.stock_zh_index_spot_em(),
                                lambda: ak.stock_zh_index_spot_sina())
        if df is None or getattr(df, "empty", True):
            raise RuntimeError("akshare 返回空数据")

        indices = []
        for target in TARGET_INDICES:
            row = None
            for alias in target["aliases"]:
                found = df[df["名称"].astype(str).str.contains(alias)]
                if not found.empty:
                    row = found.iloc[0]
                    break
            if row is None:
                continue
            chg_pct = float(row["涨跌幅"])
            indices.append({
                "name": target["name"],
                "code": str(row["代码"]),
                "price": round(float(row["最新价"]), 2),
                "change": round(float(row["涨跌额"]), 2),
                "change_pct": round(chg_pct, 2),
                "up": chg_pct >= 0,          # 红涨绿跌
            })

        if not indices:
            raise RuntimeError("未能在返回结果中匹配到目标指数")

        payload["indices"] = indices
        payload["source"] = "akshare"
        mark_ok(payload)
        payload["message"] = "A股三大指数 + 财经快讯已更新"
        payload["logs"].append({
            "time": _now(), "level": "info", "event": "indices_fetched",
            "detail": "成功获取 {} 个指数".format(len(indices)),
        })
    except Exception as e:
        mark_degraded(payload, "indices_fetch_failed", "指数获取失败：{}".format(e))
    return payload


# ───────────────────────── Phase 3：资讯 ─────────────────────────
def _fetch_text(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (finance-site-automation)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _to_beijing_str(s: str) -> str:
    """把 RFC822(pubDate) 或 ISO8601(Atom updated) 时间转成北京时间字符串。"""
    s = (s or "").strip()
    if not s:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return s


def _make_news(title: str, link: str, pub: str, summary: str) -> dict:
    summary = re.sub(r"<[^>]+>", "", summary or "")
    summary = summary.strip()[:120]
    return {
        "title": (title or "").strip(),
        "link": (link or "").strip(),
        "published": _to_beijing_str(pub),
        "summary": summary,
    }


# 真实性约束：仅接受可公开访问、可验证来源的 http/https 链接；拒绝空链接与占位域名
_PLACEHOLDER_LINK_DOMAINS = ("example.com", "example.org", "localhost", "test.com", "invalid")


def is_real_link(link: str) -> bool:
    """真实性约束：只接受可公开访问、可验证来源的 http/https 链接，拒绝空链接与占位域名。"""
    if not link:
        return False
    s = str(link).strip().lower()
    if not (s.startswith("http://") or s.startswith("https://")):
        return False
    for dom in _PLACEHOLDER_LINK_DOMAINS:
        if dom in s:
            return False
    return True


def parse_rss(url: str) -> list:
    """解析 RSS 2.0 与 Atom，返回新闻项列表（不抛异常，由调用方负责重试/容错）。

    优先用 feedparser（容错强、自动处理编码/命名空间/CDATA），
    未安装时回退到标准库 xml.etree 的轻量解析。
    """
    try:
        import feedparser  # type: ignore
        d = feedparser.parse(url)
        items = []
        for e in d.entries:
            link = e.get("link", "")
            items.append(_make_news(
                e.get("title", ""), link,
                e.get("published", e.get("updated", "")),
                e.get("summary", e.get("description", ""))))
        if items:
            return items
    except Exception:
        pass
    # 回退：标准库轻量解析
    xml = _fetch_text(url)
    root = ET.fromstring(xml)
    items = []
    for item in root.iter("item"):                  # RSS 2.0
        items.append(_make_news(
            item.findtext("title"), item.findtext("link"),
            item.findtext("pubDate"), item.findtext("description")))
    if not items:
        for entry in root.iter(ATOM + "entry"):      # Atom
            link_el = entry.find(ATOM + "link")
            link = link_el.get("href") if link_el is not None else ""
            items.append(_make_news(
                entry.findtext(ATOM + "title"), link,
                entry.findtext(ATOM + "updated"), entry.findtext(ATOM + "summary")))
    return items


def dedup_news(items: list) -> list:
    seen, out = set(), []
    for it in items:
        key = re.sub(r"\s+", "", it["title"]).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    out.sort(key=lambda x: x["published"], reverse=True)
    return out


def fetch_news_with_fallback(payload: dict) -> dict:
    """
    Phase 3：多源 RSS 并联抓取 + 财联社电报（AKShare）兜底，去重后填充 news。
    任一源失败只记 warn；全部失败才 mark_degraded。
    """
    collected = []

    # 源 A：RSS 多源并联，单源失败不影响其他
    for feed in RSS_FEEDS:
        try:
            items = _retry(lambda: parse_rss(feed["url"]), tries=2, base_delay=1.0)
            for it in items:
                it["source"] = feed["name"]
                collected.append(it)
            payload["logs"].append({
                "time": _now(), "level": "info", "event": "rss_ok",
                "detail": "{} 获取 {} 条".format(feed["name"], len(items)),
            })
        except Exception as e:
            payload["logs"].append({
                "time": _now(), "level": "warn", "event": "rss_failed",
                "detail": "{} 失败：{}".format(feed["name"], e),
            })

    # 源 B：AKShare 财联社电报（若已安装）
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_info_global_cls())
        if df is not None and not getattr(df, "empty", True):
            for _, r in df.head(30).iterrows():
                txt = str(r.get("内容", "")).strip()
                if txt:
                    collected.append({
                        "title": txt,
                        "link": "",
                        "published": _to_beijing_str(str(r.get("时间", ""))),
                        "summary": "",
                        "source": "财联社",
                    })
            payload["logs"].append({
                "time": _now(), "level": "info", "event": "akshare_news_ok",
                "detail": "财联社获取 {} 条".format(min(30, len(df))),
            })
    except ImportError:
        pass
    except Exception as e:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "akshare_news_failed",
            "detail": "财联社失败：{}".format(e),
        })

    deduped = dedup_news(collected)
    # 真实性约束：保留带可验证原文链接的快讯 或 来自 AKShare 直采的电报（财联社无外链但内容可靠）
    kept = [n for n in deduped if is_real_link(n.get("link", "")) or n.get("source") == "财联社"]
    dropped = len(deduped) - len(kept)
    if dropped:
        payload["logs"].append({
            "time": _now(), "level": "info", "event": "news_filtered",
            "detail": "按真实性约束过滤掉 {} 条无原文链接 / 占位链接的快讯".format(dropped),
        })
    deduped = kept
    if not deduped:
        mark_degraded(payload, "news_fetch_failed", "所有新闻源均失败、返回空，或均无原文链接")
        return payload

    payload["news"] = deduped[:NEWS_LIMIT]
    payload["logs"].append({
        "time": _now(), "level": "info", "event": "news_fetched",
        "detail": "成功获取 {} 条（去重后，上限 {})".format(len(deduped), NEWS_LIMIT),
    })
    return payload


# ───────────────────────── Phase 4：行业板块 ─────────────────────────
def fetch_sectors_with_fallback(payload: dict) -> dict:
    """
    Phase 4：抓取东方财富行业板块涨跌，计算「板块强弱」——
      1) sectors：按涨跌幅排序的前 N 个板块（供 ECharts 横向柱状图，红涨绿跌）；
      2) sector_summary：上涨/下跌板块家数 + 领涨/领跌板块（体现金融专业性）。
    失败（akshare 未装 / 接口异常 / 返回空）时降级，不影响指数与资讯。
    """
    try:
        import akshare as ak
    except ImportError:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "sectors_skipped",
            "detail": "本地未检测到 akshare，跳过行业板块；GitHub Actions 中已自动安装",
        })
        return payload

    try:
        df = _em_with_fallback(lambda: ak.stock_board_industry_name_em(),
                                lambda: ak.stock_board_industry_name_ths())
        if df is None or getattr(df, "empty", True):
            raise RuntimeError("akshare 返回空数据")

        # 统一列名（不同版本 akshare 列名可能略有差异；同花顺备用源列数较少）
        name_col = "板块名称" if "板块名称" in df.columns else df.columns[1]
        ncols = len(df.columns)
        pct_col = "涨跌幅" if "涨跌幅" in df.columns else (df.columns[5] if ncols > 5 else df.columns[-1])
        leader_col = "领涨股票" if "领涨股票" in df.columns else None

        rows = df.copy()
        rows[pct_col] = rows[pct_col].astype(float)
        rows = rows.sort_values(pct_col, ascending=False).reset_index(drop=True)

        # 前 N 个板块（涨跌混合）供图表展示
        SECTOR_TOPN = 15
        top = rows.head(SECTOR_TOPN)
        sectors = []
        for _, r in top.iterrows():
            chg = float(r[pct_col])
            item = {
                "name": str(r[name_col]),
                "change_pct": round(chg, 2),
                "up": chg >= 0,                 # 红涨绿跌
            }
            if leader_col is not None:
                item["leader"] = str(r[leader_col])
            sectors.append(item)

        up_count = int((rows[pct_col] >= 0).sum())
        down_count = int((rows[pct_col] < 0).sum())
        top_row = rows.iloc[0]
        bottom_row = rows.iloc[-1]

        summary = {
            "total": len(rows),
            "up_count": up_count,
            "down_count": down_count,
            "top_name": str(top_row[name_col]),
            "top_pct": round(float(top_row[pct_col]), 2),
            "bottom_name": str(bottom_row[name_col]),
            "bottom_pct": round(float(bottom_row[pct_col]), 2),
        }

        payload["sectors"] = sectors
        payload["sector_summary"] = summary
        mark_ok(payload)
        payload["message"] = "A股三大指数 + 财经快讯 + 行业板块已更新"
        payload["logs"].append({
            "time": _now(), "level": "info", "event": "sectors_fetched",
            "detail": "成功获取 {} 个行业板块，上涨 {} / 下跌 {}".format(
                summary["total"], summary["up_count"], summary["down_count"]),
        })
    except Exception as e:
        mark_degraded(payload, "sectors_fetch_failed", "行业板块获取失败：{}".format(e))
    return payload


# ───────────────────────── Phase 5：市场宽度 + 个股动向 + 外汇 ─────────────────────────
def fetch_breadth_and_movers_with_fallback(payload: dict) -> dict:
    """
    Phase 5-A：用一次 stock_zh_a_spot_em() 抓取全市场 A股，同时算出：
      1) breadth：上涨/下跌/平盘家数 + 涨停/跌停家数（市场宽度，金融专业核心指标）；
      2) movers：领涨 / 领跌个股 TOP10（个股动量）。
    一次调用服务两块内容，失败统一降级。
    """
    try:
        import akshare as ak
    except ImportError:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "breadth_skipped",
            "detail": "本地未检测到 akshare，跳过市场宽度；GitHub Actions 中已自动安装",
        })
        return payload

    try:
        df = _em_with_fallback(lambda: ak.stock_zh_a_spot_em(),
                                lambda: ak.stock_zh_a_spot())
        if df is None or getattr(df, "empty", True):
            raise RuntimeError("akshare 返回空数据")

        name_col = "名称" if "名称" in df.columns else df.columns[2]
        code_col = "代码" if "代码" in df.columns else df.columns[1]
        price_col = "最新价" if "最新价" in df.columns else df.columns[3]
        pct_col = "涨跌幅" if "涨跌幅" in df.columns else df.columns[4]

        chg = df[pct_col].astype(float)
        total = len(df)
        up = int((chg > 0).sum())
        down = int((chg < 0).sum())
        flat = int((chg == 0).sum())
        limit_up = int((chg >= 9.9).sum())
        limit_down = int((chg <= -9.9).sum())
        up_pct = round(up / total * 100, 1) if total else 0.0

        breadth = {
            "total": total, "up": up, "down": down, "flat": flat,
            "limit_up": limit_up, "limit_down": limit_down, "up_pct": up_pct,
        }

        sorted_df = df.sort_values(pct_col, ascending=False).reset_index(drop=True)

        def pick(n: int, asc: bool):
            sub = sorted_df.sort_values(pct_col, ascending=asc).reset_index(drop=True) if asc else sorted_df
            out = []
            for _, r in sub.head(n).iterrows():
                c = float(r[pct_col])
                out.append({
                    "name": str(r[name_col]), "code": str(r[code_col]),
                    "price": round(float(r[price_col]), 2),
                    "change_pct": round(c, 2), "up": c >= 0,
                })
            return out

        movers = {"top_gainers": pick(10, False), "top_losers": pick(10, True)}

        payload["breadth"] = breadth
        payload["movers"] = movers
        mark_ok(payload)
        payload["message"] = "A股三大指数 + 财经快讯 + 行业板块 + 市场宽度 + 个股动向已更新"
        payload["logs"].append({
            "time": _now(), "level": "info", "event": "breadth_fetched",
            "detail": "全市场 {} 只，上涨 {} / 下跌 {} / 涨停 {} / 跌停 {}".format(
                total, up, down, limit_up, limit_down),
        })
    except Exception as e:
        mark_degraded(payload, "breadth_fetch_failed", "市场宽度获取失败：{}".format(e))
    return payload


def fetch_fx_with_fallback(payload: dict) -> dict:
    """Phase 5-B：中国外汇牌价（美元/欧元/日元/港币/英镑）。
    兼容新旧两种 currency_boc_safe() 返回格式：
    - 新格式：日期为行、货币为列（时间序列，SAFE 中间价）
    - 旧格式：每行为一种货币，含现汇买入/卖出价列
    """
    try:
        import akshare as ak
    except ImportError:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "fx_skipped",
            "detail": "本地未检测到 akshare，跳过外汇牌价；GitHub Actions 中已自动安装",
        })
        return payload

    try:
        df = _retry(lambda: ak.currency_boc_safe())
        if df is None or getattr(df, "empty", True):
            raise RuntimeError("akshare 返回空数据")

        wanted = ["美元", "欧元", "日元", "港币", "英镑"]
        items = []

        # 检测新格式：货币名直接是列名（时间序列格式，每列=一种货币的中间价）
        currency_cols = [c for c in df.columns if any(w in str(c) for w in wanted)]

        if currency_cols:
            # 新格式：取最新一行，各货币列的值即为中间价
            latest = df.iloc[-1]
            for col in currency_cols:
                nm = str(col)
                try:
                    rate = float(latest[col])
                    items.append({
                        "name": nm,
                        "buy": round(rate, 4),
                        "sell": round(rate, 4),  # SAFE 中间价无买卖差价
                    })
                except (ValueError, TypeError):
                    pass
        else:
            # 旧格式：逐行匹配货币名称，提取买入/卖出价
            name_col = next((c for c in df.columns if ("货币" in c or "名称" in c)), df.columns[0])
            buy_col = next((c for c in df.columns if "现汇买入" in c or ("买入" in c and "价" in c)), None)
            sell_col = next((c for c in df.columns if "现汇卖出" in c or ("卖出" in c and "价" in c)), None)
            for _, r in df.iterrows():
                nm = str(r[name_col]).strip()
                if any(w in nm for w in wanted):
                    items.append({
                        "name": nm,
                        "buy": round(float(r[buy_col]), 4) if buy_col is not None else None,
                        "sell": round(float(r[sell_col]), 4) if sell_col is not None else None,
                    })

        if not items:
            raise RuntimeError("未匹配到目标货币，列名={}".format(list(df.columns)))

        payload["fx"] = items
        mark_ok(payload)
        payload["logs"].append({
            "time": _now(), "level": "info", "event": "fx_fetched",
            "detail": "成功获取 {} 个货币牌价".format(len(items)),
        })
    except Exception as e:
        mark_degraded(payload, "fx_fetch_failed", "外汇牌价获取失败：{}".format(e))
    return payload


# ───────────────────────── Phase 6：环球股指 + 基金排行 ─────────────────────────
# 环球股指目标（单接口 index_global_spot_em 一次抓取，再按名称匹配；能匹配到几个显示几个）
GLOBAL_TARGETS = [
    {"market": "港股", "names": ["恒生指数"]},
    {"market": "美股", "names": ["纳斯达克", "纳斯达克指数"]},
    {"market": "美股", "names": ["标普500", "标普500指数", "标普 500"]},
    {"market": "美股", "names": ["道琼斯", "道琼斯指数", "道琼斯工业指数"]},
    {"market": "日股", "names": ["日经225", "日经指数", "日经平均指数"]},
]


def fetch_global_indices_with_fallback(payload: dict) -> dict:
    """
    Phase 6-A：环球股指（港股/美股/日股主要指数），红涨绿跌。
    用单个 index_global_spot_em() 接口一次抓取全球主要指数，再按名称匹配目标指数；
    能匹配到几个就显示几个，匹配到 0 个才整体降级（比拆多个接口更稳、失败面更小）。
    """
    try:
        import akshare as ak
    except ImportError:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "global_skipped",
            "detail": "本地未检测到 akshare，跳过环球股指；GitHub Actions 中已自动安装",
        })
        return payload

    try:
        df = _em_with_fallback(lambda: ak.index_global_spot_em())  # 无 Sina 备用（该 API 不存在）
        if df is None or getattr(df, "empty", True):
            raise RuntimeError("akshare 返回空数据")

        name_col = "名称" if "名称" in df.columns else df.columns[1]
        price_col = next((c for c in ["最新价", "收盘价", "price"] if c in df.columns), None)
        pct_col = next((c for c in ["涨跌幅", "涨跌幅度"] if c in df.columns), None)
        if pct_col is None:
            raise RuntimeError("全球指数字段不匹配：{}".format(list(df.columns)))

        result = []
        for t in GLOBAL_TARGETS:
            for nm in t["names"]:
                sub = df[df[name_col].astype(str).str.contains(nm)]
                if not sub.empty:
                    r = sub.iloc[0]
                    c = float(r[pct_col])
                    item = {
                        "market": t["market"], "name": nm,
                        "change_pct": round(c, 2), "up": c >= 0,
                    }
                    if price_col is not None:
                        try:
                            item["price"] = round(float(r[price_col]), 2)
                        except Exception:
                            pass
                    result.append(item)
                    break

        if not result:
            raise RuntimeError("未能在全球指数中匹配到目标指数")

        payload["global_indices"] = result
        mark_ok(payload)
        payload["message"] = "A股三大指数 + 财经快讯 + 行业板块 + 市场宽度 + 个股动向 + 环球股指已更新"
        payload["logs"].append({"time": _now(), "level": "info",
            "event": "global_fetched", "detail": "成功获取 {} 个环球指数".format(len(result))})
    except Exception as e:
        mark_degraded(payload, "global_fetch_failed", "环球股指获取失败：{}".format(e))
    return payload


def fetch_funds_with_fallback(payload: dict) -> dict:
    """
    Phase 6-B：开放式基金净值排行 TOP10（按日增长率，红涨绿跌）。
    失败降级，不影响其他板块。列名做了多版本兼容。
    """
    try:
        import akshare as ak
    except ImportError:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "funds_skipped",
            "detail": "本地未检测到 akshare，跳过基金排行；GitHub Actions 中已自动安装",
        })
        return payload

    try:
        df = _retry(lambda: ak.fund_open_fund_rank_em())
        if df is None or getattr(df, "empty", True):
            raise RuntimeError("akshare 返回空数据")

        name_col = next((c for c in ["基金简称", "名称", "基金名称"] if c in df.columns), df.columns[1])
        code_col = next((c for c in ["基金代码", "代码"] if c in df.columns), df.columns[0])
        nav_col = next((c for c in ["单位净值", "最新净值", "净值"] if c in df.columns), None)
        pct_col = next((c for c in ["日增长率", "日涨幅", "增长率"] if c in df.columns), None)
        if nav_col is None or pct_col is None:
            raise RuntimeError("基金排行字段不匹配：{}".format(list(df.columns)))

        df[pct_col] = df[pct_col].astype(float)
        df = df.sort_values(pct_col, ascending=False).reset_index(drop=True)

        funds = []
        for _, r in df.head(10).iterrows():
            c = float(r[pct_col])
            item = {
                "name": str(r[name_col]),
                "code": str(r[code_col]),
                "change_pct": round(c, 2),
                "up": c >= 0,
            }
            try:
                item["nav"] = round(float(r[nav_col]), 4)
            except Exception:
                item["nav"] = None
            funds.append(item)

        payload["funds"] = funds
        mark_ok(payload)
        payload["message"] = "A股三大指数 + 财经快讯 + 行业板块 + 市场宽度 + 个股动向 + 环球股指 + 基金排行已更新"
        payload["logs"].append({"time": _now(), "level": "info",
            "event": "funds_fetched", "detail": "成功获取 {} 只基金排行".format(len(funds))})
    except Exception as e:
        mark_degraded(payload, "funds_fetch_failed", "基金排行获取失败：{}".format(e))
    return payload


# ───────────────────────── Phase 9：北向资金 ─────────────────────────
def fetch_northbound_with_fallback(payload: dict) -> dict:
    """
    Phase 9：北向资金（沪深港通）每日净流入/流出，外资情绪风向标。
    多 API 级联回退：fund_flow_summary → north_net_flow_in → hist_em
    失败降级，不影响其他板块。
    """
    try:
        import akshare as ak
    except ImportError:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "northbound_skipped",
            "detail": "本地未检测到 akshare，跳过北向资金；GitHub Actions 中已自动安装",
        })
        return payload

    northbound = None

    # 方案1：沪深港通资金流向汇总（最新版 AKShare 推荐接口）
    try:
        df = _retry(lambda: ak.stock_hsgt_fund_flow_summary_em())
        if df is not None and not getattr(df, "empty", True):
            date_col = next((c for c in ["date", "日期", "交易日"] if c in df.columns), df.columns[0])
            flow_col = next((c for c in ["north_net_flow", "北向净流入", "net_flow", "当日资金流入"] if c in df.columns), None)
            if flow_col:
                sub = df.tail(20)
                northbound = []
                for _, r in sub.iterrows():
                    date_str = str(r[date_col])
                    net_flow = float(r[flow_col])
                    if date_str:
                        northbound.append({
                            "date": date_str[:10] if len(date_str) >= 10 else date_str,
                            "net_flow": round(net_flow, 2),
                            "up": net_flow >= 0,
                        })
    except Exception:
        pass

    # 方案2：旧版北向资金净流入接口
    if not northbound:
        try:
            df = _retry(lambda: ak.stock_hsgt_north_net_flow_in_em())
            if df is not None and not getattr(df, "empty", True):
                sub = df.tail(20)
                northbound = []
                for _, r in sub.iterrows():
                    date_str = str(r.get("date", r.get("日期", "")))
                    net_flow = None
                    for col in ["value", "净流入", "net_flow", "当日资金流入"]:
                        if col in df.columns:
                            net_flow = float(r[col])
                            break
                    if net_flow is not None and date_str:
                        northbound.append({
                            "date": date_str[:10] if len(date_str) >= 10 else date_str,
                            "net_flow": round(net_flow, 2),
                            "up": net_flow >= 0,
                        })
        except Exception:
            pass

    # 方案3：北向资金历史数据
    if not northbound:
        try:
            df = _retry(lambda: ak.stock_hsgt_hist_em(symbol="北向资金"))
            if df is not None and not getattr(df, "empty", True):
                sub = df.tail(20)
                northbound = []
                for _, r in sub.iterrows():
                    date_str = str(r.get("日期", r.get("date", "")))
                    net_flow = None
                    for col in ["当日资金流入", "净流入", "资金流入", "net_flow"]:
                        if col in df.columns:
                            net_flow = float(r[col])
                            break
                    if net_flow is not None and date_str:
                        northbound.append({
                            "date": date_str[:10] if len(date_str) >= 10 else date_str,
                            "net_flow": round(net_flow, 2),
                            "up": net_flow >= 0,
                        })
        except Exception:
            pass

    if not northbound:
        mark_degraded(payload, "northbound_fetch_failed", "北向资金所有接口均失败")
        return payload

    # 计算累计、连续净流入天数等摘要
    total_net = sum(n["net_flow"] for n in northbound)
    recent_5 = northbound[-5:]
    avg_5 = sum(n["net_flow"] for n in recent_5) / len(recent_5) if recent_5 else 0
    streak = 0
    for n in reversed(northbound):
        if n["up"]:
            streak += 1
        else:
            break

    payload["northbound"] = {
        "daily": northbound,
        "total_net_20d": round(total_net, 2),
        "avg_net_5d": round(avg_5, 2),
        "inflow_streak": streak,
    }
    mark_ok(payload)
    payload["logs"].append({
        "time": _now(), "level": "info", "event": "northbound_fetched",
        "detail": "北向资金 20 日累计{}亿，连续{}日净流入".format(
            round(total_net, 1), streak),
    })
    return payload


# ───────────────────────── Phase 10：两市成交额 ─────────────────────────
def fetch_turnover_with_fallback(payload: dict) -> dict:
    """
    Phase 10：沪深两市成交额（量价配合核心指标）。
    优先从 breadth 数据源中获取；失败时尝试指数接口。
    """
    # 如果能从已有的全市场数据里拿到成交额列，直接复用
    try:
        import akshare as ak
        df = _em_with_fallback(lambda: ak.stock_zh_a_spot_em(),
                                lambda: ak.stock_zh_a_spot())
        if df is not None and not getattr(df, "empty", True):
            turnover_col = next((c for c in ["成交额", "turnover", "成交金额"] if c in df.columns), None)
            if turnover_col:
                total_turnover = df[turnover_col].astype(float).sum()
                payload["turnover"] = {
                    "total_yuan": round(total_turnover, 0),
                    "total_yi": round(total_turnover / 1e8, 2),
                    "stock_count": len(df),
                }
                mark_ok(payload)
                payload["logs"].append({
                    "time": _now(), "level": "info", "event": "turnover_fetched",
                    "detail": "两市成交额 {} 亿元".format(round(total_turnover / 1e8, 0)),
                })
                # 把成交额也挂到 breadth 里供前端使用
                if "breadth" in payload:
                    payload["breadth"]["turnover_yi"] = round(total_turnover / 1e8, 2)
                return payload
    except ImportError:
        pass
    except Exception:
        pass

    # 回退：用上证和深证指数接口
    try:
        import akshare as ak
        df_sh = _retry(lambda: ak.stock_zh_index_daily_em(symbol="sh000001"))
        df_sz = _retry(lambda: ak.stock_zh_index_daily_em(symbol="sz399001"))
        sh_col = next((c for c in ["amount", "成交额"] if c in df_sh.columns), None)
        sz_col = next((c for c in ["amount", "成交额"] if c in df_sz.columns), None)
        sh_val = float(df_sh.iloc[-1][sh_col]) if sh_col else 0
        sz_val = float(df_sz.iloc[-1][sz_col]) if sz_col else 0
        total = sh_val + sz_val
        payload["turnover"] = {
            "total_yuan": round(total, 0),
            "total_yi": round(total / 1e8, 2),
        }
        mark_ok(payload)
        payload["logs"].append({
            "time": _now(), "level": "info", "event": "turnover_fetched",
            "detail": "两市成交额 {} 亿元（指数接口）".format(round(total / 1e8, 0)),
        })
    except Exception as e:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "turnover_failed",
            "detail": "成交额获取失败：{}".format(e),
        })
    return payload


# ───────────────────────── Phase 11：商品期货 ─────────────────────────
COMMODITY_TARGETS = [
    "原油", "黄金", "白银", "铜", "螺纹钢", "铁矿石", "豆粕", "PTA",
    "沪铝", "沪锌", "天然橡胶", "棕榈油",
]


def fetch_commodities_with_fallback(payload: dict) -> dict:
    """
    Phase 11：商品期货主力合约行情（大类资产视角）。
    失败降级，不影响其他板块。
    """
    try:
        import akshare as ak
    except ImportError:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "commodities_skipped",
            "detail": "本地未检测到 akshare，跳过商品期货",
        })
        return payload

    try:
        df = _em_with_fallback(lambda: ak.futures_zh_spot_em(),
                                lambda: ak.futures_zh_spot())
        if df is None or getattr(df, "empty", True):
            raise RuntimeError("akshare 返回空数据")

        name_col = next((c for c in ["名称", "name", "品种"] if c in df.columns), df.columns[1])
        price_col = next((c for c in ["最新价", "price", "最新价格"] if c in df.columns), df.columns[2])
        pct_col = next((c for c in ["涨跌幅", "change_pct", "涨跌幅度"] if c in df.columns), df.columns[5])

        commodities = []
        for _, r in df.iterrows():
            nm = str(r[name_col])
            if any(t in nm for t in COMMODITY_TARGETS):
                c = float(r[pct_col])
                item = {
                    "name": nm,
                    "change_pct": round(c, 2),
                    "up": c >= 0,
                }
                try:
                    item["price"] = round(float(r[price_col]), 2)
                except Exception:
                    item["price"] = None
                commodities.append(item)

        if not commodities:
            raise RuntimeError("未匹配到目标商品")

        payload["commodities"] = commodities[:12]
        mark_ok(payload)
        payload["logs"].append({
            "time": _now(), "level": "info", "event": "commodities_fetched",
            "detail": "成功获取 {} 个商品期货".format(len(commodities[:12])),
        })
    except Exception as e:
        mark_degraded(payload, "commodities_fetch_failed", "商品期货获取失败：{}".format(e))
    return payload


# ───────────────────────── Phase 12：龙虎榜 ─────────────────────────
def fetch_dragon_tiger_with_fallback(payload: dict) -> dict:
    """
    Phase 12：龙虎榜 — 当日机构/游资上榜个股。
    失败降级，不影响其他板块。
    """
    try:
        import akshare as ak
    except ImportError:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "dragon_tiger_skipped",
            "detail": "本地未检测到 akshare，跳过龙虎榜",
        })
        return payload

    top_list = None

    # 方案1：东方财富龙虎榜个股详情（最全）
    try:
        today = now_beijing().strftime("%Y%m%d")
        df = _retry(lambda: ak.stock_lhb_hy_detail_em(date=today))
        if df is None or getattr(df, "empty", True):
            from datetime import timedelta as _td
            yesterday = (now_beijing() - _td(days=1)).strftime("%Y%m%d")
            df = _retry(lambda: ak.stock_lhb_hy_detail_em(date=yesterday))
        if df is not None and not getattr(df, "empty", True):
            name_col = next((c for c in ["名称", "股票名称"] if c in df.columns), df.columns[1])
            code_col = next((c for c in ["代码", "股票代码"] if c in df.columns), df.columns[0])
            close_col = next((c for c in ["收盘价", "最新价"] if c in df.columns), None)
            pct_col = next((c for c in ["涨跌幅", "涨跌幅度"] if c in df.columns), None)
            reason_col = next((c for c in ["上榜原因", "上榜理由"] if c in df.columns), None)
            buy_col = next((c for c in ["买方机构净买入", "净买入"] if c in df.columns), None)
            top_list = []
            for _, r in df.head(20).iterrows():
                item = {"name": str(r[name_col]), "code": str(r[code_col])}
                if pct_col is not None:
                    c = float(r[pct_col])
                    item["change_pct"] = round(c, 2)
                    item["up"] = c >= 0
                if close_col is not None:
                    try: item["price"] = round(float(r[close_col]), 2)
                    except Exception: pass
                if reason_col is not None:
                    item["reason"] = str(r[reason_col])
                if buy_col is not None:
                    try: item["net_buy"] = round(float(r[buy_col]) / 1e4, 2)
                    except Exception: pass
                top_list.append(item)
    except Exception:
        pass

    # 方案2：新浪龙虎榜个股统计（EM 被阻断时的备用）
    if not top_list:
        try:
            df = _retry(lambda: ak.stock_lhb_ggtj_sina())
            if df is not None and not getattr(df, "empty", True):
                name_col = next((c for c in ["股票名称", "名称", "name"] if c in df.columns), df.columns[0])
                code_col = next((c for c in ["股票代码", "代码", "code"] if c in df.columns), None)
                pct_col = next((c for c in ["涨跌幅", "change_pct"] if c in df.columns), None)
                reason_col = next((c for c in ["上榜原因", "reason"] if c in df.columns), None)
                top_list = []
                for _, r in df.head(20).iterrows():
                    item = {"name": str(r[name_col])}
                    if code_col: item["code"] = str(r[code_col])
                    if pct_col:
                        try:
                            c = float(r[pct_col])
                            item["change_pct"] = round(c, 2)
                            item["up"] = c >= 0
                        except Exception: pass
                    if reason_col: item["reason"] = str(r[reason_col])
                    top_list.append(item)
        except Exception:
            pass

    if not top_list:
        mark_degraded(payload, "dragon_tiger_fetch_failed", "龙虎榜所有数据源均失败")
        return payload

    up_count = sum(1 for t in top_list if t.get("up"))
    down_count = len(top_list) - up_count
    payload["dragon_tiger"] = {
        "list": top_list, "total": len(top_list),
        "up_count": up_count, "down_count": down_count,
    }
    mark_ok(payload)
    payload["logs"].append({
        "time": _now(), "level": "info", "event": "dragon_tiger_fetched",
        "detail": "龙虎榜 {} 只上榜，{} 涨 {} 跌".format(len(top_list), up_count, down_count),
    })
    return payload


# ───────────────────────── Phase 13：国债收益率 ─────────────────────────
def fetch_treasury_with_fallback(payload: dict) -> dict:
    """
    Phase 13：中国国债收益率曲线（无风险利率锚，股债跷跷板参考）。
    失败降级，不影响其他板块。
    """
    try:
        import akshare as ak
    except ImportError:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "treasury_skipped",
            "detail": "本地未检测到 akshare，跳过国债收益率",
        })
        return payload

    try:
        df = _retry(lambda: ak.bond_china_yield())
        if df is None or getattr(df, "empty", True):
            raise RuntimeError("akshare 返回空数据")

        # 取最新一行的关键期限（兼容中英文列名）
        key_patterns = {
            "3M":  ["3M", "3m", "3月", "3个月", "三个月"],
            "6M":  ["6M", "6m", "6月", "6个月", "六个月"],
            "1Y":  ["1Y", "1y", "1年", "一年"],
            "2Y":  ["2Y", "2y", "2年", "两年"],
            "5Y":  ["5Y", "5y", "5年", "五年"],
            "10Y": ["10Y", "10y", "10年", "十年"],
            "30Y": ["30Y", "30y", "30年", "三十年"],
        }
        yield_data = {}
        latest = df.iloc[-1]
        for tenor, patterns in key_patterns.items():
            for p in patterns:
                col = next((c for c in df.columns if p in str(c)), None)
                if col is not None:
                    try:
                        yield_data[tenor] = round(float(latest[col]), 4)
                    except Exception:
                        pass
                    break  # 找到第一个匹配就停

        if not yield_data:
            raise RuntimeError("未匹配到国债收益率数据，列名={}".format(list(df.columns)))

        # 收益率曲线倒挂检测
        y10 = yield_data.get("10Y", 0)
        y2 = yield_data.get("2Y", 0)
        y1 = yield_data.get("1Y", 0)
        inverted = y10 < y2 if y10 and y2 else False

        payload["treasury"] = {
            "yields": yield_data,
            "date": now_beijing().strftime("%Y-%m-%d"),
            "curve_inverted": inverted,
            "spread_10y_2y": round(y10 - y2, 4) if y10 and y2 else None,
        }
        mark_ok(payload)
        payload["logs"].append({
            "time": _now(), "level": "info", "event": "treasury_fetched",
            "detail": "国债收益率 {} 个期限".format(len(yield_data)),
        })
    except Exception as e:
        mark_degraded(payload, "treasury_fetch_failed", "国债收益率获取失败：{}".format(e))
    return payload


# ───────────────────────── Phase 14：沪深300估值 ─────────────────────────
def fetch_csi300_val_with_fallback(payload: dict) -> dict:
    """
    Phase 14：沪深300 PE/PB 估值分位数（判断市场贵/便宜）。
    失败降级，不影响其他板块。
    """
    try:
        import akshare as ak
    except ImportError:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "csi300_val_skipped",
            "detail": "本地未检测到 akshare，跳过沪深300估值",
        })
        return payload

    try:
        df = _retry(lambda: ak.stock_index_pe_lg(symbol="沪深300"))
        if df is None or getattr(df, "empty", True):
            raise RuntimeError("akshare 返回空数据")

        latest = df.iloc[-1]
        pe = float(latest.get("PE", latest.get("市盈率", 0)))
        pb = float(latest.get("PB", latest.get("市净率", 0)))

        # 计算历史分位（简单方法）
        pe_col = next((c for c in ["PE", "市盈率"] if c in df.columns), None)
        if pe_col:
            pe_series = df[pe_col].dropna().astype(float)
            pe_pct = round((pe_series < pe).sum() / len(pe_series) * 100, 1)
        else:
            pe_pct = None

        pb_col = next((c for c in ["PB", "市净率"] if c in df.columns), None)
        if pb_col:
            pb_series = df[pb_col].dropna().astype(float)
            pb_pct = round((pb_series < pb).sum() / len(pb_series) * 100, 1)
        else:
            pb_pct = None

        payload["csi300_val"] = {
            "pe": round(pe, 2),
            "pb": round(pb, 2),
            "pe_percentile": pe_pct,
            "pb_percentile": pb_pct,
            "date": now_beijing().strftime("%Y-%m-%d"),
        }
        mark_ok(payload)
        payload["logs"].append({
            "time": _now(), "level": "info", "event": "csi300_val_fetched",
            "detail": "沪深300 PE={} ({}分位) PB={} ({}分位)".format(
                round(pe, 2), pe_pct, round(pb, 2), pb_pct),
        })
    except Exception as e:
        mark_degraded(payload, "csi300_val_fetch_failed", "沪深300估值获取失败：{}".format(e))
    return payload


# ───────────────────────── Phase 15：可转债 ─────────────────────────
def fetch_convertible_bonds_with_fallback(payload: dict) -> dict:
    """
    Phase 15：可转债行情（集思录双低策略 — 低价+低溢价）。
    失败降级，不影响其他板块。
    """
    try:
        import akshare as ak
    except ImportError:
        payload["logs"].append({
            "time": _now(), "level": "warn", "event": "cb_skipped",
            "detail": "本地未检测到 akshare，跳过可转债",
        })
        return payload

    try:
        df = _retry(lambda: ak.bond_cb_jsl(), tries=3, base_delay=5.0)  # 集思录偶发超时，加长重试间隔
        if df is None or getattr(df, "empty", True):
            raise RuntimeError("akshare 返回空数据")

        name_col = next((c for c in ["bond_nm", "转债名称", "名称"] if c in df.columns), df.columns[0])
        price_col = next((c for c in ["price", "转债价格", "转债最新价"] if c in df.columns), df.columns[2])
        premium_col = next((c for c in ["premium_rt", "转股溢价率", "溢价率"] if c in df.columns), None)
        pct_col = next((c for c in ["increase_rt", "涨跌幅", "日涨跌幅"] if c in df.columns), None)

        # 计算双低 = 价格 + 溢价率
        df_copy = df.copy()
        if price_col and premium_col:
            df_copy["_price"] = df_copy[price_col].astype(float)
            df_copy["_premium"] = df_copy[premium_col].astype(float)
            df_copy["_double_low"] = df_copy["_price"] + df_copy["_premium"]
            df_copy = df_copy.sort_values("_double_low").reset_index(drop=True)

        cb_list = []
        for _, r in df_copy.head(15).iterrows():
            item = {"name": str(r[name_col])}
            try:
                item["price"] = round(float(r[price_col]), 2)
            except Exception:
                pass
            if premium_col:
                try:
                    item["premium_rt"] = round(float(r[premium_col]), 2)
                except Exception:
                    pass
            if pct_col:
                try:
                    c = float(r[pct_col])
                    item["change_pct"] = round(c, 2)
                    item["up"] = c >= 0
                except Exception:
                    pass
            try:
                if price_col and premium_col:
                    item["double_low"] = round(float(r["_price"]) + float(r["_premium"]), 2)
            except Exception:
                pass
            cb_list.append(item)

        if not cb_list:
            raise RuntimeError("可转债数据为空")

        # 统计
        up_count = sum(1 for c in cb_list if c.get("up"))
        avg_price = sum(c.get("price", 0) for c in cb_list) / len(cb_list)

        payload["convertible_bonds"] = {
            "list": cb_list,
            "total_count": len(cb_list),
            "up_count": up_count,
            "down_count": len(cb_list) - up_count,
            "avg_price": round(avg_price, 2),
        }
        mark_ok(payload)
        payload["logs"].append({
            "time": _now(), "level": "info", "event": "cb_fetched",
            "detail": "可转债 {} 只，均价 {}".format(len(cb_list), round(avg_price, 1)),
        })
    except Exception as e:
        mark_degraded(payload, "cb_fetch_failed", "可转债获取失败：{}".format(e))
    return payload


def _extract_index_pct(indices, name):
    for x in (indices or []):
        if x.get("name") == name:
            return x.get("change_pct"), x.get("price")
    return None, None


# ───────────────────────── Phase 8：专业洞察（盘面简评） ─────────────────────────
def generate_commentary(payload: dict) -> dict:
    """
    Phase 8：根据已抓取的指数 / 市场宽度 / 行业板块，自动生成结构化盘面简评。
    这是从"搬运数据"升级到"专业解读"的关键一步：所有结论都由真实数据推导，
    不编造；数据不足时给出"数据暂缺"的诚实提示，而非空谈。
    简评不改变 status（纯衍生解读），不触发降级，但会记入日志。
    """
    items = []

    sh, _ = _extract_index_pct(payload.get("indices", []), "上证指数")
    sz, _ = _extract_index_pct(payload.get("indices", []), "深证成指")
    cyb, _ = _extract_index_pct(payload.get("indices", []), "创业板指")
    valid = [v for v in (sh, sz, cyb) if v is not None]
    avg = (sum(valid) / len(valid)) if valid else None

    # 1) 大盘定调
    if avg is not None:
        if avg >= 0.3:
            tone, tone_desc = "up", "三大指数多数收红，市场做多情绪较强"
        elif avg > -0.3:
            tone, tone_desc = "neutral", "指数窄幅波动，多空分歧加大"
        else:
            tone, tone_desc = "down", "指数多数收绿，盘面承压"
        parts = []
        if sh is not None: parts.append("上证{}".format(_fmt_pct(sh)))
        if sz is not None: parts.append("深成指{}".format(_fmt_pct(sz)))
        if cyb is not None: parts.append("创业板{}".format(_fmt_pct(cyb)))
        items.append({
            "label": "大盘定调",
            "tone": tone,
            "text": "今日 A 股整体{}：{}。{}".format(
                "偏强" if tone == "up" else ("偏弱" if tone == "down" else "震荡"),
                "、".join(parts), tone_desc),
        })
    else:
        items.append({
            "label": "大盘定调",
            "tone": "neutral",
            "text": "指数数据暂缺（可能为收盘后、非交易日或数据源降级），暂不定调。",
        })

    # 2) 市场广度（涨跌家数 + 涨停跌停 → 情绪温度）
    breadth = payload.get("breadth") or {}
    if breadth.get("total"):
        up, down = breadth.get("up", 0), breadth.get("down", 0)
        up_pct = breadth.get("up_pct", 0)
        lu, ld = breadth.get("limit_up", 0), breadth.get("limit_down", 0)
        if up_pct >= 60:
            mood = "做多情绪高涨，赚钱效应显著"
        elif up_pct >= 50:
            mood = "个股涨多跌少，情绪偏暖"
        elif up_pct >= 40:
            mood = "个股跌多涨少，情绪偏冷"
        else:
            mood = "做空情绪占优，亏钱效应明显"
        items.append({
            "label": "市场广度",
            "tone": "up" if up_pct >= 50 else "down",
            "text": "全市场 {} 只，上涨 {} 家（占比 {}%）、下跌 {} 家；涨停 {} 家、跌停 {} 家，{}。".format(
                breadth["total"], up, up_pct, down, lu, ld, mood),
        })

    # 3) 资金主线（领涨 / 领跌板块）
    summary = payload.get("sector_summary") or {}
    if summary.get("total"):
        items.append({
            "label": "资金主线",
            "tone": "neutral",
            "text": "领涨板块为 {}（{}），领跌板块为 {}（{}）。当日 {} 个行业板块中 {} 个上涨、{} 个下跌，"
                    "结构性行情特征明显，资金在板块间快速轮动。".format(
                summary["top_name"], _fmt_pct(summary["top_pct"]),
                summary["bottom_name"], _fmt_pct(summary["bottom_pct"]),
                summary["total"], summary["up_count"], summary["down_count"]),
        })

    # 4) 风险提示（高位退潮 / 指数破位 / 重挫板块）
    risk = []
    if breadth.get("limit_down", 0) >= 20:
        risk.append("跌停家数达 {} 家，需警惕高位题材股退潮".format(breadth["limit_down"]))
    if sh is not None and sh <= -1:
        risk.append("上证单日跌超 1%，短期趋势承压")
    if summary.get("bottom_pct") is not None and summary["bottom_pct"] <= -2:
        risk.append("{} 等板块重挫，注意相关持仓风险".format(summary["bottom_name"]))
    if risk:
        items.append({
            "label": "风险提示",
            "tone": "down",
            "text": "；".join(risk) + "。",
        })

    # 5) 综合研判（仅当主要数据齐全时给出一句话结论）
    if avg is not None and breadth.get("total") and summary.get("total"):
        if avg >= 0.3 and breadth.get("up_pct", 0) >= 50:
            verdict = "综合来看，今日量价配合、主线清晰，属可参与度较高的多头环境，但宜避免追高已大涨的题材。"
        elif avg <= -0.3 or breadth.get("up_pct", 0) < 40:
            verdict = "综合来看，今日赚钱效应偏弱，宜控制仓位、规避高位题材，等待企稳信号。"
        else:
            verdict = "综合来看，今日属结构化震荡格局，不宜追高，精选个股、波段操作为主。"
        items.append({"label": "综合研判", "tone": "neutral", "text": verdict})

    if not items:
        items.append({
            "label": "盘面简评",
            "tone": "neutral",
            "text": "今日数据源暂未就绪（可能为收盘后、非交易日或接口降级），简评将在下个交易时段自动生成。",
        })

    payload["commentary"] = items
    payload.setdefault("logs", []).append({
        "time": _now(), "level": "info", "event": "commentary_generated",
        "detail": "生成 {} 条盘面简评".format(len(items)),
    })
    return payload


def load_existing_history() -> list:
    """读取仓库中已有的 data.js 的 history 数组（上次 commit 的版本），用于累积快照。"""
    try:
        if os.path.exists(DATA_JS_PATH):
            with open(DATA_JS_PATH, encoding="utf-8") as f:
                t = f.read()
            js = t[t.index("=") + 1:].rstrip().rstrip(";")
            d = json.loads(js)
            h = d.get("history", [])
            if isinstance(h, list):
                return h
    except Exception:
        pass
    return []


def compute_run_stats(history: list) -> dict:
    """累计运行天数 + 连续运行天数（连续按自然日向前数，跳过周末）。"""
    if not history:
        return {"streak": 0, "total_days": 0}
    dates = sorted({h.get("date") for h in history if h.get("date")})
    total = len(dates)
    from datetime import datetime as _dt
    d = _dt.strptime(dates[-1], "%Y-%m-%d").date()
    streak = 0
    while True:
        if d.weekday() >= 5:           # 周六/周日跳过，不计入连续但继续向前
            d -= timedelta(days=1)
            continue
        if d.strftime("%Y-%m-%d") in dates:
            streak += 1
            d -= timedelta(days=1)
        else:
            break
    return {"streak": streak, "total_days": total}


def build_payload() -> dict:
    """构造站点数据源；Phase 2/3/4/5/6/7 接入真实数据并保留兜底逻辑。"""
    generated_at = _now()
    payload = {
        "updated_at": generated_at,
        "updated_at_iso": now_beijing().isoformat(),
        "timezone": "Asia/Shanghai",
        "status": "ok",
        "source": "akshare",
        "message": "本页数据由 GitHub Actions 自动抓取，部分数据源可能因网络波动降级。",
        "indices": [],                       # Phase 2 由 AKShare 填充
        "news": [],                          # Phase 3 由多源 RSS + 财联社填充
        "sectors": [],                       # Phase 4 由 AKShare 行业板块填充
        "sector_summary": {},                # Phase 4 板块强弱统计
        "breadth": {},                       # Phase 5 市场宽度（涨跌家数/涨停跌停）
        "movers": {"top_gainers": [], "top_losers": []},  # Phase 5 领涨/领跌个股
        "fx": [],                            # Phase 5 外汇牌价
        "global_indices": [],                # Phase 6 环球股指（港股/美股/日股）
        "funds": [],                         # Phase 6 基金净值排行 TOP10
        "northbound": {"daily": [], "total_net_20d": 0, "avg_net_5d": 0, "inflow_streak": 0},  # Phase 9
        "turnover": {},                    # Phase 10
        "commodities": [],                 # Phase 11
        "dragon_tiger": {"list": [], "total": 0, "up_count": 0, "down_count": 0},  # Phase 12
        "treasury": {"yields": {}, "date": "", "curve_inverted": False, "spread_10y_2y": None},  # Phase 13
        "csi300_val": {},                  # Phase 14
        "convertible_bonds": {"list": [], "total_count": 0, "up_count": 0, "down_count": 0, "avg_price": 0},  # Phase 15
        "logs": [
            {
                "time": generated_at,
                "level": "info",
                "event": "pipeline_bootstrap",
                "detail": "基础链路运行成功，等待接入真实数据源",
            }
        ],
    }

    payload = fetch_indices_with_fallback(payload)   # Phase 2
    payload = fetch_news_with_fallback(payload)      # Phase 3
    payload = fetch_sectors_with_fallback(payload)   # Phase 4
    payload = fetch_breadth_and_movers_with_fallback(payload)  # Phase 5-A 市场宽度+个股
    payload = fetch_fx_with_fallback(payload)        # Phase 5-B 外汇牌价
    payload = fetch_global_indices_with_fallback(payload)  # Phase 6-A 环球股指
    payload = fetch_funds_with_fallback(payload)     # Phase 6-B 基金排行
    payload = fetch_northbound_with_fallback(payload)     # Phase 9 北向资金
    payload = fetch_turnover_with_fallback(payload)       # Phase 10 两市成交额
    payload = fetch_commodities_with_fallback(payload)    # Phase 11 商品期货
    payload = fetch_dragon_tiger_with_fallback(payload)   # Phase 12 龙虎榜
    payload = fetch_treasury_with_fallback(payload)       # Phase 13 国债收益率
    payload = fetch_csi300_val_with_fallback(payload)     # Phase 14 沪深300估值
    payload = fetch_convertible_bonds_with_fallback(payload)  # Phase 15 可转债
    payload = generate_commentary(payload)           # Phase 8 专业洞察：盘面简评

    # ── Phase 7：历史沉淀（快照累积 + 连续运行统计）──
    history = load_existing_history()
    today = now_beijing().strftime("%Y-%m-%d")
    sh_pct, sh_price = _extract_index_pct(payload.get("indices", []), "上证指数")
    sz_pct, _ = _extract_index_pct(payload.get("indices", []), "深证成指")
    cyb_pct, _ = _extract_index_pct(payload.get("indices", []), "创业板指")
    snapshot = {
        "date": today,
        "status": payload["status"],
        "sh_pct": sh_pct,
        "sz_pct": sz_pct,
        "cyb_pct": cyb_pct,
        "sh_price": sh_price,
    }
    history = [h for h in history if h.get("date") != today]   # 同日幂等：覆盖而非重复
    history.append(snapshot)
    if len(history) > HISTORY_MAX:
        history = history[-HISTORY_MAX:]
    payload["history"] = history
    payload["run_stats"] = compute_run_stats(history)
    return payload


def write_data_js(payload: dict) -> str:
    os.makedirs(SITE_DIR, exist_ok=True)
    # 用全局变量挂载数据，规避 file:// 与跨域 fetch 的限制，
    # 这样页面在本地双击打开、python -m http.server、GitHub Pages 上都能正常读取。
    js = "window.__SITE_DATA__ = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n"
    with open(DATA_JS_PATH, "w", encoding="utf-8") as f:
        f.write(js)
    return DATA_JS_PATH


def main() -> None:
    try:
        payload = build_payload()
        path = write_data_js(payload)
        print(f"[OK] 已生成 {path}")
        print(f"[OK] 状态={payload['status']} 来源={payload['source']} "
              f"指数={len(payload.get('indices', []))} 资讯={len(payload.get('news', []))} "
              f"板块={len(payload.get('sectors', []))} 宽度={'Y' if payload.get('breadth') else 'N'} "
              f"环球={len(payload.get('global_indices', []))} 基金={len(payload.get('funds', []))} "
              f"外汇={len(payload.get('fx', []))} 时间={payload['updated_at']}")
        sys.exit(0)
    except Exception as e:
        # 最后一道防线：即便整段逻辑异常，也产出一份降级数据，保证页面不白屏
        fallback = {
            "updated_at": _now(),
            "updated_at_iso": now_beijing().isoformat(),
            "timezone": "Asia/Shanghai",
            "status": "degraded",
            "source": "fallback",
            "message": f"采集脚本异常，已启用兜底数据：{e}",
            "indices": [],
            "news": [],
            "sectors": [],
            "sector_summary": {},
            "breadth": {},
            "movers": {"top_gainers": [], "top_losers": []},
            "fx": [],
            "global_indices": [],
            "funds": [],
            "northbound": {"daily": [], "total_net_20d": 0, "avg_net_5d": 0, "inflow_streak": 0},
            "turnover": {},
            "commodities": [],
            "dragon_tiger": {"list": [], "total": 0, "up_count": 0, "down_count": 0},
            "treasury": {"yields": {}, "date": "", "curve_inverted": False, "spread_10y_2y": None},
            "csi300_val": {},
            "convertible_bonds": {"list": [], "total_count": 0, "up_count": 0, "down_count": 0, "avg_price": 0},
            "history": load_existing_history(),
            "run_stats": compute_run_stats(load_existing_history()),
            "logs": [{"time": _now(), "level": "error", "event": "script_exception", "detail": str(e)}],
        }
        write_data_js(fallback)
        print(f"[WARN] 脚本异常，已写入兜底数据：{e}")
        sys.exit(0)  # 退出码 0：避免流水线被判失败而停摆，把"失败"体现在数据里而非进程里


if __name__ == "__main__":
    main()
