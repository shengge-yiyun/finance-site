#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_demo_data.py — 离线演示数据生成器
=============================================
在无法连接网络或 akshare 不可用时，生成逼真的模拟金融数据，
使网站可以完整展示所有 12 个板块。

运行方式:
    python agent/generate_demo_data.py

输出文件:
    data.js              — 主数据文件 (window.__SITE_DATA__ 格式)
    data/portfolio.json  — 模拟持仓明细
"""

import json
import os
import random
import sys
from datetime import datetime, timezone, timedelta

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CST = timezone(timedelta(hours=8))
random.seed(42)


def now_str():
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def now_iso():
    return datetime.now(CST).isoformat()


def fmt_pct(v):
    return round(v, 2)


# ==================== 数据生成 ====================

def gen_indices():
    """A股三大指数"""
    bases = [
        ("上证指数", "000001", 3250.0),
        ("深证成指", "399001", 10520.0),
        ("创业板指", "399006", 2110.0),
    ]
    result = []
    for name, code, base in bases:
        pct = random.uniform(-2.0, 2.0)
        price = round(base * (1 + pct / 100), 2)
        result.append({
            "name": name, "code": code,
            "price": price, "change": round(price - base, 2),
            "change_pct": round(pct, 2), "up": pct >= 0,
        })
    return result


def gen_news_summary(indices, sectors, breadth):
    """根据当日数据自动生成一段金融要闻简报，而非伪造新闻链接列表"""
    sh = indices[0] if indices else None
    sz = indices[1] if len(indices) > 1 else None
    cyb = indices[2] if len(indices) > 2 else None

    parts = ["今日 A 股"]

    if sh:
        direction = "走强" if sh["up"] else "走弱"
        parts.append(f"上证指数{fmt_pct(sh['change_pct']):+}%{direction}")
    if sz:
        parts.append(f"深证成指{fmt_pct(sz['change_pct']):+}%")
    if cyb:
        parts.append(f"创业板指{fmt_pct(cyb['change_pct']):+}%")

    parts.append("。")

    # 市场宽度
    if breadth.get("total"):
        up_pct = breadth.get("up_pct", 0)
        mood = "涨多跌少、情绪偏暖" if up_pct >= 50 else "跌多涨少、情绪偏冷"
        parts.append(f"全市场 {breadth['total']} 只个股中上涨 {breadth['up']} 家（占比 {up_pct}%），{mood}；")
        parts.append(f"涨停 {breadth.get('limit_up', 0)} 家、跌停 {breadth.get('limit_down', 0)} 家。")

    # 板块
    if sectors:
        top3_up = [s for s in sectors if s["up"]][:3]
        top3_down = [s for s in sectors if not s["up"]][-3:]
        if top3_up:
            names_up = "、".join(f"{s['name']}({fmt_pct(s['change_pct']):+}%)" for s in top3_up)
            parts.append(f"领涨板块：{names_up}。")
        if top3_down:
            names_down = "、".join(f"{s['name']}({fmt_pct(s['change_pct']):+}%)" for s in top3_down)
            parts.append(f"领跌板块：{names_down}。")

    # 宏观背景
    parts.append("宏观方面，央行维持 LPR 利率不变，市场预期下半年仍有降准降息空间；"
                 "7 月 CPI 同比涨 0.5%、PPI 降幅收窄，物价总体平稳；"
                 "IMF 上调中国 2026 年 GDP 增速预期至 5.0%。")

    # 外部环境
    parts.append("海外方面，美国通胀低于预期推动美联储 9 月降息概率升至 85%，全球股市多数收涨；"
                 "欧盟公布对中国电动车加征关税终裁草案，中方表示强烈反对并将采取反制措施；"
                 "比特币突破 75000 美元创历史新高，黄金重返 2100 美元/盎司。")

    return "".join(parts)


def gen_sectors():
    """行业板块"""
    names_pcts = [
        ("半导体", 3.84), ("白酒", 2.91), ("电池", 2.45), ("光伏设备", 1.97),
        ("证券", 1.32), ("软件开发", 0.88), ("银行", 0.21), ("电力", -0.34),
        ("钢铁", -0.92), ("煤炭", -1.47), ("房地产", -2.13), ("航空机场", -2.78),
        ("旅游酒店", -3.42),
    ]
    leaders = ["中芯国际","贵州茅台","宁德时代","隆基绿能","东方财富","用友网络",
               "招商银行","长江电力","宝钢股份","中国神华","保利发展","中国国航","锦江酒店"]
    sectors = []
    for i, (name, pct) in enumerate(names_pcts):
        sectors.append({
            "name": name, "change_pct": pct, "up": pct >= 0,
            "leader": leaders[i] if i < len(leaders) else "",
        })
    up_count = sum(1 for s in sectors if s["up"])
    down_count = len(sectors) - up_count
    summary = {
        "total": len(sectors), "up_count": up_count, "down_count": down_count,
        "top_name": names_pcts[0][0], "top_pct": names_pcts[0][1],
        "bottom_name": names_pcts[-1][0], "bottom_pct": names_pcts[-1][1],
    }
    return sectors, summary


def gen_breadth():
    """市场宽度"""
    total = random.randint(4800, 5200)
    up = random.randint(1800, 3000)
    down = total - up - random.randint(100, 400)
    flat = total - up - down
    return {
        "total": total, "up": up, "down": down, "flat": flat,
        "limit_up": random.randint(30, 80), "limit_down": random.randint(1, 15),
        "up_pct": round(up / total * 100, 1),
    }


def gen_movers():
    """个股动向"""
    gainers_names = ["中芯国际","宁德时代","隆基绿能","药明康德","中国中免",
                     "东方财富","比亚迪","海康威视","立讯精密","韦尔股份"]
    losers_names = ["中国国航","锦江酒店","保利发展","中国神华","宝钢股份",
                    "南方航空","华侨城A","首旅酒店","万科A","华夏幸福"]
    top_gainers, top_losers = [], []
    for i in range(10):
        pct = round(random.uniform(5.0, 10.0), 2)
        top_gainers.append({"name": gainers_names[i], "code": f"{600000+i:06d}",
                            "price": round(random.uniform(10, 200), 2),
                            "change_pct": pct, "up": True})
        pct2 = round(random.uniform(-10.0, -5.0), 2)
        top_losers.append({"name": losers_names[i], "code": f"{600100+i:06d}",
                           "price": round(random.uniform(5, 80), 2),
                           "change_pct": pct2, "up": False})
    return {"top_gainers": top_gainers, "top_losers": top_losers}


def gen_fx():
    """外汇牌价"""
    return [
        {"name": "美元", "buy": round(random.uniform(7.20, 7.30), 4),
         "sell": round(random.uniform(7.20, 7.30), 4)},
        {"name": "欧元", "buy": round(random.uniform(7.80, 7.95), 4),
         "sell": round(random.uniform(7.80, 7.95), 4)},
        {"name": "日元", "buy": round(random.uniform(0.048, 0.050), 4),
         "sell": round(random.uniform(0.048, 0.050), 4)},
        {"name": "港币", "buy": round(random.uniform(0.92, 0.94), 4),
         "sell": round(random.uniform(0.92, 0.94), 4)},
        {"name": "英镑", "buy": round(random.uniform(9.10, 9.30), 4),
         "sell": round(random.uniform(9.10, 9.30), 4)},
    ]


def gen_global():
    """环球股指"""
    return [
        {"market": "港股", "name": "恒生指数", "price": round(random.uniform(19000, 20000), 2),
         "change_pct": round(random.uniform(-1.5, 1.5), 2),
         "up": random.random() > 0.45},
        {"market": "美股", "name": "纳斯达克", "price": round(random.uniform(18000, 19000), 2),
         "change_pct": round(random.uniform(-1.5, 1.5), 2),
         "up": random.random() > 0.4},
        {"market": "美股", "name": "标普500", "price": round(random.uniform(5500, 5700), 2),
         "change_pct": round(random.uniform(-1.0, 1.0), 2),
         "up": random.random() > 0.4},
        {"market": "美股", "name": "道琼斯", "price": round(random.uniform(39000, 41000), 2),
         "change_pct": round(random.uniform(-0.8, 0.8), 2),
         "up": random.random() > 0.45},
        {"market": "日股", "name": "日经225", "price": round(random.uniform(38000, 39500), 2),
         "change_pct": round(random.uniform(-2.0, 2.0), 2),
         "up": random.random() > 0.5},
    ]


def gen_funds():
    """基金排行"""
    fund_names = ["易方达蓝筹精选","华夏沪深300ETF联接","招商中证白酒","天弘创业板ETF联接",
                  "广发科技先锋","富国天惠成长","兴全趋势投资","中欧医疗健康",
                  "景顺长城鼎益","南方中证500ETF联接"]
    funds = []
    for i, name in enumerate(fund_names):
        pct = round(random.uniform(-3.0, 5.0), 2)
        funds.append({
            "name": name, "code": f"{100000+i:06d}",
            "nav": round(random.uniform(0.8, 3.5), 4),
            "change_pct": pct, "up": pct >= 0,
        })
    funds.sort(key=lambda x: x["change_pct"], reverse=True)
    return funds


def gen_commentary(indices, breadth, sectors_summary):
    """自动生成盘面简评"""
    items = []

    pcts = [idx["change_pct"] for idx in indices]
    avg = sum(pcts) / len(pcts) if pcts else 0

    if avg >= 0.3:
        tone, desc = "up", "三大指数多数收红，市场做多情绪较强"
    elif avg > -0.3:
        tone, desc = "neutral", "指数窄幅波动，多空分歧加大"
    else:
        tone, desc = "down", "指数多数收绿，盘面承压"

    parts = [f"{idx['name']}{fmt_pct(idx['change_pct']):+.2f}%" for idx in indices]
    items.append({
        "label": "大盘定调", "tone": tone,
        "text": f"今日 A 股整体{'偏强' if tone == 'up' else ('偏弱' if tone == 'down' else '震荡')}：{'、'.join(parts)}。{desc}。",
    })

    if breadth.get("total"):
        up_pct = breadth.get("up_pct", 0)
        mood = "做多情绪高涨" if up_pct >= 60 else ("情绪偏暖" if up_pct >= 50 else ("情绪偏冷" if up_pct >= 40 else "做空情绪占优"))
        items.append({
            "label": "市场广度", "tone": "up" if up_pct >= 50 else "down",
            "text": f"全市场 {breadth['total']} 只，上涨 {breadth['up']} 家（占比 {up_pct}%）、下跌 {breadth['down']} 家；涨停 {breadth.get('limit_up', 0)} 家、跌停 {breadth.get('limit_down', 0)} 家，{mood}。",
        })

    if sectors_summary.get("total"):
        items.append({
            "label": "资金主线", "tone": "neutral",
            "text": f"领涨板块为 {sectors_summary['top_name']}（{fmt_pct(sectors_summary['top_pct']):+.2f}%），领跌板块为 {sectors_summary['bottom_name']}（{fmt_pct(sectors_summary['bottom_pct']):+.2f}%）。{sectors_summary['total']} 个行业中 {sectors_summary['up_count']} 个上涨、{sectors_summary['down_count']} 个下跌。",
        })

    items.append({
        "label": "综合研判", "tone": "neutral",
        "text": "综合来看，今日属结构化震荡格局，不宜追高，精选个股、波段操作为主。" if abs(avg) < 0.3
        else ("量价配合尚可，属可参与度较高的多头环境，但宜避免追高已大涨的题材。" if avg >= 0.3
              else "赚钱效应偏弱，宜控制仓位、规避高位题材，等待企稳信号。"),
    })

    return items


def gen_history(indices, days=1):
    """生成历史快照 — 从今天往前数，默认只含今天（新项目首日运行）"""
    history = []
    base_date = datetime.now(CST).date()
    for d in range(days, 0, -1):
        date = base_date - timedelta(days=d)
        if date.weekday() >= 5:
            continue
        sh_pct = round(random.uniform(-2.0, 2.0), 2)
        history.append({
            "date": date.strftime("%Y-%m-%d"),
            "status": "ok",
            "sh_pct": sh_pct,
            "sz_pct": round(sh_pct + random.uniform(-0.5, 0.5), 2),
            "cyb_pct": round(sh_pct + random.uniform(-1.0, 1.0), 2),
            "sh_price": round(indices[0]["price"] + random.uniform(-80, 80), 2) if indices else None,
        })
    return history


def gen_portfolio():
    """模拟持仓"""
    holdings = [
        ("贵州茅台", "600519", 100, 1680.0, 1820.50),
        ("宁德时代", "300750", 500, 210.0, 245.30),
        ("中国平安", "601318", 2000, 45.0, 48.20),
        ("沪深300ETF", "510300", 8000, 4.85, 5.12),
        ("美的集团", "000333", 600, 62.0, 67.90),
        ("科创50ETF", "588000", 5000, 1.05, 1.18),
    ]
    result = []
    total_val, total_cost = 0.0, 0.0
    for name, code, shares, cost, price in holdings:
        mv = round(shares * price, 2)
        tc = round(shares * cost, 2)
        total_val += mv
        total_cost += tc
        result.append({
            "name": name, "code": code, "shares": shares,
            "cost_per_share": cost, "current_price": price,
            "market_value": mv, "weight_pct": 0.0,
        })
    for r in result:
        r["weight_pct"] = round(r["market_value"] / total_val * 100, 1)

    day_chg = round(random.uniform(-5000, 8000), 2)
    return {
        "timestamp": now_iso(), "total_value": round(total_val, 2),
        "total_cost": round(total_cost, 2), "day_change": day_chg,
        "day_change_pct": round(day_chg / total_val * 100, 2),
        "total_return_pct": round((total_val - total_cost) / total_cost * 100, 2),
        "holdings": result,
    }


# ==================== 主入口 ====================

def main():
    print("=" * 55)
    print("  金融情报中心 — 演示数据生成器 v2")
    print("  输出格式: data.js (window.__SITE_DATA__)")
    print("=" * 55)
    print()

    indices = gen_indices()
    sectors, sector_summary = gen_sectors()
    breadth = gen_breadth()
    portfolio = gen_portfolio()
    movers = gen_movers()
    fx = gen_fx()
    global_idx = gen_global()
    funds = gen_funds()
    commentary = gen_commentary(indices, breadth, sector_summary)
    news_summary = gen_news_summary(indices, sectors, breadth)
    now = datetime.now(CST)
    today = now.strftime("%Y-%m-%d")
    history = [{"date": today, "status": "ok",
        "sh_pct": indices[0]["change_pct"], "sz_pct": indices[1]["change_pct"],
        "cyb_pct": indices[2]["change_pct"], "sh_price": indices[0]["price"]}]

    log_detail = "{}指数, {}板块, {}基金, {}环球".format(
        len(indices), len(sectors), len(funds), len(global_idx))

    payload = {
        "updated_at": now_str(),
        "updated_at_iso": now_iso(),
        "timezone": "Asia/Shanghai",
        "status": "ok",
        "source": "demo-generator",
        "message": "演示数据（首日运行，自动化链路正常）",
        "indices": indices,
        "news": [],
        "news_summary": news_summary,
        "sectors": sectors,
        "sector_summary": sector_summary,
        "breadth": breadth,
        "movers": movers,
        "fx": fx,
        "global_indices": global_idx,
        "funds": funds,
        "commentary": commentary,
        "history": history,
        "run_stats": {"streak": 1, "total_days": 1},
        "logs": [
            {"time": now_str(), "level": "info", "event": "demo_generated",
             "detail": log_detail},
        ],
        "portfolio": portfolio,
    }

    # 写入 data.js
    js = "window.__SITE_DATA__ = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n"
    data_js_path = os.path.join(BASE_DIR, "data.js")
    with open(data_js_path, "w", encoding="utf-8") as f:
        f.write(js)
    print(f"  ✓ data.js — {len(payload['indices'])}指数, {len(payload['sectors'])}板块, "
          f"要闻简报已生成, {len(payload['funds'])}基金")

    # 同时写入 portfolio.json
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    pf_path = os.path.join(BASE_DIR, "data", "portfolio.json")
    with open(pf_path, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)
    print(f"  ✓ data/portfolio.json — ¥{portfolio['total_value']:,.0f}, {len(portfolio['holdings'])}项")

    print()
    print("=" * 55)
    print("  现在刷新浏览器即可看到完整效果")
    print("=" * 55)


if __name__ == "__main__":
    main()
