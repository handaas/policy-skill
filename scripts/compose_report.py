#!/usr/bin/env python3
"""Compose a policy big-data report by orchestrating the policy MCP.

Calls the upstream policy-mcp-server tools and assembles a structured JSON
payload rendered into a professional HTML / Markdown report. Supports
``--dry-run`` which returns a well-formed skeleton from the bundled sample data
WITHOUT contacting the MCP.

Policy report is keyword-driven: the primary input is a *policy keyword*
(``--keyword``) used for policy search; an optional ``--enterprise`` enables
the approved-project statistics (立项项目统计), and ``--policy-id`` fetches a
single policy detail.

This file never prints secrets; MCP credentials live in the server's own .env.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from typing import Any, Dict, List, Mapping, Optional

from common import REPORT_BANNER, REPORT_TYPE, json_dumps, load_json_file, print_json
import mcp_client
from render_report import render_html, render_markdown, html_to_pdf

SAMPLE_PATH = pathlib.Path(__file__).resolve().parent.parent / "assets" / "report.example.json"

# Policy MCP tools.
T_FUZZY = "policy_bigdata_fuzzy_search"
T_APPROVED_STATS = "policy_bigdata_approved_project_stats"
T_POLICY_INFO = "policy_bigdata_policy_info"
T_POLICY_SEARCH = "policy_bigdata_policy_search"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _is_api_error(value: Any) -> bool:
    """Detect MCP API error responses (not empty data, but actual failures like 405)."""
    if value is None:
        return False
    if isinstance(value, str):
        return any(s in value for s in ("接口调用失败", "查询失败", "状态码：4", "状态码：5"))
    if isinstance(value, dict):
        for v in value.values():
            if isinstance(v, str) and any(s in v for s in ("接口调用失败", "查询失败", "状态码：4", "状态码：5")):
                return True
    return False

def _first_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if _is_api_error(value):
            return []
        for key in ("resultList", "list", "items", "data"):
            if isinstance(value.get(key), list):
                return value[key]
    if value in (None, "", {}):
        return []
    return [value]


def _first_record(value: Any) -> Dict[str, Any]:
    for record in _first_list(value):
        if isinstance(record, dict):
            return record
    if isinstance(value, dict):
        return value
    return {}


def _text(value: Any, limit: int = 0) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        t = json.dumps(value, ensure_ascii=False)
    else:
        t = str(value)
    t = " ".join(t.split())
    if limit and len(t) > limit:
        return t[: limit - 1].rstrip() + "…"
    return t


def _region_text(value: Any) -> str:
    """pnRegion is a dict {province, city, district} — render as a readable
    '省/市/区' string. Falls back to _text for legacy string values."""
    if isinstance(value, dict):
        parts = [value.get(k) for k in ("province", "city", "district") if value.get(k)]
        return "、".join(str(p).strip() for p in parts if str(p).strip())
    return _text(value)


def _month_key(date_str: Any) -> str:
    """Normalize a date string like '2026-08-05' to a 'YYYY-MM' month key."""
    s = _text(date_str)
    if not s:
        return ""
    # Take first 7 chars if it looks like YYYY-MM...
    return s[:7] if len(s) >= 7 and s[4] in "-/" else s


# Policy sub-theme keywords for term-frequency analysis (人才/资金/培训/产业/技术...).
_POLICY_SUBTHEME_KEYWORDS = ["人才", "资金", "培训", "产业", "技术", "创新", "补贴", "平台", "数据", "安全"]


def _policy_keyword_freq_rows(search: Any) -> List[Dict[str, Any]]:
    """Count occurrences of sub-theme keywords across all pnText bodies.
    Returns rows: {主题词, 出现次数} sorted desc."""
    counter: Dict[str, int] = {kw: 0 for kw in _POLICY_SUBTHEME_KEYWORDS}
    for item in _first_list(search):
        if not isinstance(item, dict):
            continue
        body = item.get("pnText") or ""
        if not isinstance(body, str):
            body = _text(body)
        for kw in _POLICY_SUBTHEME_KEYWORDS:
            counter[kw] += body.count(kw)
    rows = [{"主题词": kw, "出现次数": str(n)} for kw, n in counter.items() if n > 0]
    rows.sort(key=lambda r: int(r["出现次数"]), reverse=True)
    return rows


def _policy_monthly_trend_rows(search: Any) -> List[Dict[str, Any]]:
    """Aggregate pnPublishDate into monthly counts: {月份, 政策数量}."""
    counter: Dict[str, int] = {}
    for item in _first_list(search):
        if not isinstance(item, dict):
            continue
        mk = _month_key(item.get("pnPublishDate"))
        if not mk:
            continue
        counter[mk] = counter.get(mk, 0) + 1
    rows = [{"月份": k, "政策数量": str(v)} for k, v in sorted(counter.items())]
    return rows


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_call(tool: str, arguments: Dict[str, Any]) -> Any:
    try:
        result = mcp_client.call_tool(tool, arguments)
        # Detect API error responses (405, etc.) and return error marker
        if _is_api_error(result):
            return {"_error": "API错误", "_raw": result}
        return result
    except Exception as exc:
        return {"_error": str(exc)}


def _safe_total(payload: Any) -> Any:
    if isinstance(payload, dict):
        if _is_api_error(payload):
            return None
        return payload.get("total")
    return None


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

def resolve_enterprise_name(raw: str) -> Dict[str, Any]:
    """Resolve an enterprise name for the approved-project stats tool.

    A policy keyword is usually NOT an enterprise, so this only resolves when
    the caller explicitly passes ``--enterprise``. If the value already looks
    like a full enterprise name we use it directly; otherwise we fuzzy-search.
    """
    raw = (raw or "").strip()
    if not raw:
        return {"keyword": "", "enterprise": "", "resolved": False, "reason": "未提供企业主体"}
    if any(suffix in raw for suffix in ("公司", "集团", "有限", "院", "厂", "中心", "事务所", "合作社", "合伙")):
        return {"keyword": raw, "enterprise": raw, "resolved": True, "reason": "视为企业全称"}
    fuzzy = _safe_call(T_FUZZY, {"matchKeyword": raw, "pageSize": 1})
    record = _first_record(fuzzy)
    name = str(record.get("name") or "").strip()
    if name:
        return {"keyword": raw, "enterprise": name, "resolved": True, "reason": "由关键词模糊查询补全", "fuzzy_total": _int(_safe_total(fuzzy)), "record": record}
    return {"keyword": raw, "enterprise": raw, "resolved": False, "reason": "模糊查询未命中企业全称"}


# --------------------------------------------------------------------------- #
# Enterprise profile helpers (from fuzzy_search record)
# --------------------------------------------------------------------------- #

def _extract_profile(record: Dict[str, Any]) -> Dict[str, Any]:
    """Extract enterprise profile fields from a fuzzy_search record."""
    return {
        "name": _text(record.get("name")),
        "reg_capital": record.get("regCapitalValue"),
        "reg_capital_coin": _text(record.get("regCapitalCoinType")),
        "annual_turnover": _text(record.get("annualTurnover")),
        "oper_status": _text(record.get("operStatus")),
        "enterprise_type": _text(record.get("enterpriseType")),
        "found_time": _text(record.get("foundTime")),
        "legal_rep": _text(record.get("legalRepresentative")),
        "address": _text(record.get("address")),
        "homepage": _text(record.get("homepage")),
    }


def _format_capital(val: Any, coin: str = "") -> str:
    """Format capital value: 10995210218.0 -> '109.95 亿'."""
    try:
        v = float(val)
        if v >= 1e8:
            s = f"{v / 1e8:.2f} 亿"
        elif v >= 1e4:
            s = f"{v / 1e4:.2f} 万"
        else:
            s = f"{v:.0f}"
        if coin:
            s += f" {coin}"
        return s
    except (TypeError, ValueError):
        return _text(val) if val else "-"


def _enrich_metrics_with_profile(metrics: List[Dict[str, Any]], record: Any) -> List[Dict[str, Any]]:
    """Append enterprise profile metrics from a fuzzy_search record."""
    if not isinstance(record, dict):
        return metrics
    _prof = _extract_profile(record)
    if _prof.get("reg_capital") and _prof["reg_capital"] not in ("-", "", None):
        metrics.append({"label": "注册资本", "value": _format_capital(_prof["reg_capital"], _prof.get("reg_capital_coin", "")), "hint": "工商登记注册资本"})
    if _prof.get("found_time") and _prof["found_time"] != "-":
        metrics.append({"label": "成立时间", "value": _prof["found_time"], "hint": "工商登记成立日期"})
    if _prof.get("oper_status") and _prof["oper_status"] != "-":
        metrics.append({"label": "经营状态", "value": _prof["oper_status"], "hint": "工商登记经营状态"})
    if _prof.get("enterprise_type") and _prof["enterprise_type"] != "-":
        metrics.append({"label": "企业类型", "value": _prof["enterprise_type"], "hint": "工商登记企业类型"})
    if _prof.get("legal_rep") and _prof["legal_rep"] != "-":
        metrics.append({"label": "法定代表人", "value": _prof["legal_rep"], "hint": "工商登记法定代表人"})
    return metrics

def _derive_core_metrics(metrics: List[Dict[str, Any]], core: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Derive additional metrics from core analysis sections."""
    type_dist = core.get("type_dist", []) if isinstance(core, dict) else []
    keyword_freq = core.get("keyword_freq", []) if isinstance(core, dict) else []
    monthly = core.get("monthly_trend", []) if isinstance(core, dict) else []
    search = core.get("search_records", []) if isinstance(core, dict) else []
    if isinstance(type_dist, list) and type_dist:
        metrics.append({"label": "政策类型数", "value": str(len(type_dist)), "hint": "涉及的政策类型数"})
    if isinstance(keyword_freq, list) and keyword_freq:
        metrics.append({"label": "高频主题词", "value": str(len(keyword_freq)), "hint": "出现频次较高的主题词数"})
        try:
            top_kw = max(keyword_freq, key=lambda r: int(r.get("出现次数", "0")) if str(r.get("出现次数", "0")).isdigit() else 0)
            if top_kw.get("主题词"):
                metrics.append({"label": "最热主题", "value": str(top_kw["主题词"]), "hint": "出现频次最高的主题词"})
        except (ValueError, TypeError):
            pass
    if isinstance(monthly, list) and monthly:
        metrics.append({"label": "覆盖月份", "value": str(len(monthly)), "hint": "有政策发布的月份数"})
    if isinstance(search, list) and search:
        agencies = set(str(r.get("发布机构", "")) for r in search if r.get("发布机构"))
        if agencies:
            metrics.append({"label": "发布机构数", "value": str(len(agencies)), "hint": "涉及的政策发布机构数"})
    return metrics


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #

def build_subject(keyword: str, enterprise_resolved: Mapping[str, Any], filters: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "keyword": keyword,
        "matchKeyword": keyword,
        "enterprise": enterprise_resolved.get("enterprise") or "",
        "enterprise_resolved": bool(enterprise_resolved.get("resolved")),
        "enterprise_resolve_reason": enterprise_resolved.get("reason", ""),
        "pn_type": filters.get("pn_type") or "全部",
        "agency": filters.get("agency") or "",
        "address": filters.get("address") or "",
        "policy_id": filters.get("policy_id") or "",
    }


def build_metrics(approved: Mapping[str, Any], search_total: Any) -> List[Dict[str, Any]]:
    metrics: List[Dict[str, Any]] = []
    a = approved if isinstance(approved, dict) else {}
    if a:
        # Compute total for level-share deltas.
        total_proj = 0.0
        for k in ("nationalProjectCount", "provincialProjectCount"):
            try:
                total_proj += float(a.get(k) or 0)
            except (TypeError, ValueError):
                pass
        level = a.get("ppeLevelStat") if isinstance(a.get("ppeLevelStat"), dict) else {}
        for k in ("municipalProjectCount", "districtProjectCount"):
            try:
                total_proj += float(level.get(k) or 0)
            except (TypeError, ValueError):
                pass

        def _share_delta(val: Any) -> Dict[str, Any]:
            d: Dict[str, Any] = {}
            try:
                n = float(val)
                if total_proj > 0:
                    d["delta"] = f"占 {n / total_proj * 100:.0f}%"
            except (TypeError, ValueError):
                pass
            return d

        m1: Dict[str, Any] = {"label": "国家级项目", "value": _text(a.get("nationalProjectCount")) or "-", "hint": "获批国家级项目数量"}
        m1.update(_share_delta(a.get("nationalProjectCount")))
        metrics.append(m1)
        m2: Dict[str, Any] = {"label": "省级项目", "value": _text(a.get("provincialProjectCount")) or "-", "hint": "获批省级项目数量"}
        m2.update(_share_delta(a.get("provincialProjectCount")))
        metrics.append(m2)
        if level:
            m3: Dict[str, Any] = {"label": "市级项目", "value": _text(level.get("municipalProjectCount")) or "-", "hint": "获批市级项目数量"}
            m3.update(_share_delta(level.get("municipalProjectCount")))
            metrics.append(m3)
            m4: Dict[str, Any] = {"label": "区级项目", "value": _text(level.get("districtProjectCount")) or "-", "hint": "获批区级项目数量"}
            m4.update(_share_delta(level.get("districtProjectCount")))
            metrics.append(m4)
    metrics.append({"label": "政策检索结果", "value": (_text(search_total) if search_total is not None else "-"), "hint": "本次政策检索命中条数"})
    return [m for m in metrics if m.get("value") not in ("", None, "-")]


def build_caliber(subject: Mapping[str, Any]) -> Dict[str, Any]:
    parts = ["政策检索按政策关键词匹配", f"（pnType={subject.get('pn_type', '全部')}）"]
    if subject.get("enterprise"):
        parts.append(f"；立项项目统计按企业主体“{subject.get('enterprise')}”匹配")
    return {
        "match_target": f"政策关键词“{subject.get('keyword')}”" + (f" / 企业“{subject.get('enterprise')}”" if subject.get("enterprise") else ""),
        "match_type": "".join(parts),
        "data_scope": "立项项目统计、政策检索明细、政策详情",
        "products": ["政策检索", "立项项目统计", "政策详情"],
        "limit": "数据来自政策公开数据库；少量字段可能存在更新延迟。",
    }


def build_core_analysis(approved: Any, search: Any, policy_info: Any, subject: Mapping[str, Any]) -> Dict[str, Any]:
    a = approved if isinstance(approved, dict) else {}

    # 立项项目统计 KV + 表
    approved_kv: Dict[str, Any] = {}
    if a:
        for k, label in (
            ("nationalProjectCount", "国家级项目数"),
            ("provincialProjectCount", "省级项目数"),
        ):
            if a.get(k) is not None:
                approved_kv[label] = _text(a.get(k))
        level = a.get("ppeLevelStat") if isinstance(a.get("ppeLevelStat"), dict) else {}
        for k, label in (
            ("municipalProjectCount", "市级项目数"),
            ("districtProjectCount", "区级项目数"),
        ):
            if level.get(k) is not None:
                approved_kv[label] = _text(level.get(k))
    if subject.get("enterprise"):
        approved_kv.setdefault("匹配企业", subject.get("enterprise"))
    elif not approved_kv:
        approved_kv["说明"] = "未提供企业主体，立项项目统计为空；可用 --enterprise 补充企业全称以启用该项目统计。"

    agency_rows = []
    for item in _first_list(a.get("ppeAgencyStat")):
        if not isinstance(item, dict):
            continue
        agency_rows.append({
            "主管机构": _text(item.get("agency")) or "-",
            "项目数量": _text(item.get("count")) or "-",
        })
    year_project_rows = []
    for item in _first_list(a.get("ppeYearProjectStat")):
        if not isinstance(item, dict):
            continue
        year_project_rows.append({
            "年份": _text(item.get("year")) or "-",
            "获批项目数": _text(item.get("count")) or "-",
        })

    # 政策检索明细表
    search_rows = []
    total = None
    if isinstance(search, dict):
        total = search.get("total")
    for item in _first_list(search):
        if not isinstance(item, dict):
            continue
        search_rows.append({
            "政策标题": _text(item.get("pnTitle")) or "-",
            "发布机构": _text(item.get("pnAgency")) or "-",
            "地区": _region_text(item.get("pnRegion")) or "-",
            "政策类型": _text(item.get("pnType")) or "-",
            "发布日期": _text(item.get("pnPublishDate")) or "-",
        })

    # 政策详情 KV
    info_kv: Dict[str, Any] = {}
    pi = policy_info if isinstance(policy_info, dict) else {}
    if pi:
        for k, label in (
            ("pnTitle", "政策标题"),
            ("pnAgency", "发布机构"),
            ("pnPublishDate", "发布时间"),
            ("pnType", "政策类型"),
            ("pnRegion", "发布地区"),
            ("pnOriginUrl", "政策原文链接"),
        ):
            if k == "pnRegion":
                region_val = _region_text(pi.get("pnRegion"))
                if region_val:
                    info_kv[label] = region_val
            elif pi.get(k):
                info_kv[label] = _text(pi.get(k))
        text_val = pi.get("pnText")
        if text_val:
            info_kv["政策正文摘要"] = _text(text_val, limit=400)

    # Derive project level distribution (国家/省/市/区) from approved_kv.
    level_dist_rows: List[Dict[str, Any]] = []
    for label in ("国家级项目数", "省级项目数", "市级项目数", "区级项目数"):
        v = approved_kv.get(label)
        try:
            n = float(str(v)) if v is not None else None
        except (TypeError, ValueError):
            n = None
        if n and n > 0:
            level_name = label.replace("项目数", "")
            level_dist_rows.append({"层级": level_name, "项目数": str(int(n))})

    # Derive policy type distribution from search_rows (政策类型 aggregation).
    type_counts: Dict[str, int] = {}
    for r in search_rows:
        t = r.get("政策类型")
        if t and t != "-":
            type_counts[t] = type_counts.get(t, 0) + 1
    type_dist_rows = [{"政策类型": k, "数量": str(n)} for k, n in sorted(type_counts.items(), key=lambda kv: kv[1], reverse=True)]

    # 政策主题词频（来源：pnText 全文）& 政策发布时间趋势（来源：pnPublishDate）
    keyword_freq_rows = _policy_keyword_freq_rows(search)
    monthly_trend_rows = _policy_monthly_trend_rows(search)

    sections = [
        {"key": "approved_stats", "title": "立项项目统计", "kind": "kv"},
        {"key": "level_dist", "title": "项目层级分布", "kind": "donut", "note": "按申报层级（国家/省/市/区）统计获批项目占比", "chart": {"name": "层级", "value": "项目数"}, "columns": [("层级", "层级"), ("项目数", "项目数")]},
        {"key": "agency_stat", "title": "项目归口分布", "kind": "bar", "note": "按主管机构统计获批项目数量", "chart": {"name": "主管机构", "value": "项目数量", "orient": "v"}, "columns": [("主管机构", "主管机构"), ("项目数量", "项目数量")]},
        {"key": "year_project_stat", "title": "获批项目趋势", "kind": "line", "note": "按年度统计获批项目数量", "chart": {"x": "年份", "y": "获批项目数", "area": True}, "columns": [("年份", "年份"), ("获批项目数", "获批项目数")]},
        {"key": "type_dist", "title": "政策类型分布", "kind": "pie", "note": "按政策类型统计检索命中数", "chart": {"name": "政策类型", "value": "数量", "donut": True}, "columns": [("政策类型", "政策类型"), ("数量", "数量")]},
        {"key": "keyword_freq", "title": "政策主题词频", "kind": "bar", "note": "对政策正文(pnText)中各子主题词出现次数统计（人才/资金/培训/产业/技术…）", "chart": {"name": "主题词", "value": "出现次数", "orient": "v"}, "columns": [("主题词", "主题词"), ("出现次数", "出现次数")]},
        {"key": "monthly_trend", "title": "政策发布时间趋势", "kind": "line", "note": "按发布月份(pnPublishDate)统计政策数量", "chart": {"x": "月份", "y": "政策数量", "area": True}, "columns": [("月份", "月份"), ("政策数量", "政策数量")]},
        {"key": "search_records", "title": "政策检索明细", "kind": "table", "note": f"本次检索命中 {total if total is not None else '若干'} 条，展示前 {len(level_dist_rows)} 条",
         "columns": [("政策标题", "政策标题"), ("发布机构", "发布机构"), ("地区", "地区"), ("政策类型", "政策类型"), ("发布日期", "发布日期")]},
    ]
    if info_kv:
        sections.append({"key": "policy_info", "title": "政策详情", "kind": "kv", "note": f"按政策 id 查询：{subject.get('policy_id')}"})

    return {
        "sections": sections,
        "approved_stats": approved_kv,
        "level_dist": level_dist_rows,
        "agency_stat": agency_rows,
        "year_project_stat": year_project_rows,
        "type_dist": type_dist_rows,
        "keyword_freq": keyword_freq_rows,
        "monthly_trend": monthly_trend_rows,
        "search_records": search_rows,
        "policy_info": info_kv,
    }


def build_records(core: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for item in core.get("search_records") or []:
        out.append({
            "政策标题": item.get("政策标题") or "-",
            "发布机构": item.get("发布机构") or "-",
            "政策类型": item.get("政策类型") or "-",
            "发布日期": item.get("发布日期") or "-",
        })
    return out[:20]


def _concentration_rows(rows: List[Mapping[str, Any]], name_key: str, value_key: str, top_n: int = 3) -> Dict[str, Any]:
    """CRn concentration from aggregated rows."""
    items = []
    for r in rows:
        try:
            items.append((r.get(name_key, "-"), float(str(r.get(value_key, 0)).replace(",", ""))))
        except (TypeError, ValueError):
            items.append((r.get(name_key, "-"), 0.0))
    total = sum(v for _, v in items)
    if not total:
        return {}
    items.sort(key=lambda x: x[1], reverse=True)
    cr = sum(v for _, v in items[:top_n]) / total * 100
    return {"top": items[0][0], "top_share": items[0][1] / total * 100, "cr": cr, "total": total, "count": len(items)}


def _year_trend_analysis(rows: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Direction/peak/YoY for 获批项目数 year series."""
    nums = []
    for r in rows:
        try:
            nums.append(float(str(r.get("获批项目数", 0)).replace(",", "")))
        except (TypeError, ValueError):
            nums.append(0.0)
    if not nums:
        return {}
    peak_idx = max(range(len(nums)), key=lambda i: nums[i])
    direction = "持平"
    yoy = ""
    if len(nums) >= 2:
        last, prev = nums[-1], nums[-2]
        if prev > 0:
            pct = (last - prev) / prev * 100
            if pct > 5:
                direction = f"上升 {pct:.0f}%"
            elif pct < -5:
                direction = f"下降 {abs(pct):.0f}%"
            yoy = f"同比 {pct:+.0f}%"
    return {"peak_period": rows[peak_idx].get("年份", "-"), "peak_value": nums[peak_idx], "direction": direction, "yoy": yoy, "last": nums[-1]}


def build_insights(subject: Mapping[str, Any], core: Mapping[str, Any], metrics: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    insights: List[Dict[str, Any]] = []
    metric_map = {m["label"]: str(m["value"]) for m in metrics}
    approved_kv = core.get("approved_stats") or {}

    # 1. 项目申报层级（高阶占比）
    level_dist = core.get("level_dist") or []
    if level_dist:
        conc = _concentration_rows(level_dist, "层级", "项目数", 4)
        if conc:
            # 高阶（国家级+省级）占比
            high = 0.0
            for r in level_dist:
                if r.get("层级") in ("国家级", "省级"):
                    try:
                        high += float(str(r.get("项目数", 0)).replace(",", ""))
                    except (TypeError, ValueError):
                        pass
            high_share = high / conc["total"] * 100 if conc["total"] else 0
            insights.append({
                "feature": "项目层级结构与高阶占比",
                "evidence": f"获批项目共 {int(conc['total'])} 个，国家级+省级合计占 {high_share:.0f}%；最多为“{conc['top']}”（{conc['top_share']:.0f}%）。",
                "interpretation": "高阶（国家/省级）项目占比越高，企业承担重大专项、获得政府认可的能力越强；偏低则多以市区级普惠政策为主。",
            })

    # 2. 项目归口集中度（CR3）
    agency_stat = core.get("agency_stat") or []
    if agency_stat:
        conc = _concentration_rows(agency_stat, "主管机构", "项目数量", 3)
        if conc:
            focus = "高度集中" if conc["top_share"] >= 50 else "较分散"
            insights.append({
                "feature": "项目归口集中度",
                "evidence": f"“{conc['top']}”获批项目占比约 {conc['top_share']:.0f}%，前 3 主管机构合计 {conc['cr']:.0f}%（CR3）。",
                "interpretation": f"归口分布{focus}；高度集中意味着主要政策渠道稳定，分散则需对接多个部门，建议聚焦主力渠道深耕。",
            })

    # 3. 获批项目年度趋势
    year_stat = core.get("year_project_stat") or []
    if year_stat:
        ta = _year_trend_analysis(year_stat)
        if ta:
            insights.append({
                "feature": "获批项目趋势",
                "evidence": f"峰值在“{ta['peak_period']}”（{ta['peak_value']:.0f} 个），近年{ta['direction']}，{ta.get('yoy', '')}。",
                "interpretation": "获批量上升反映政策红利期或企业申报能力增强；下降可能是政策窗口收窄或竞争加剧，需提前布局下一年度申报。",
            })

    # 4. 政策类型集中度（基于检索结果聚合）
    type_dist = core.get("type_dist") or []
    if type_dist:
        conc = _concentration_rows(type_dist, "政策类型", "数量", 3)
        if conc:
            insights.append({
                "feature": "政策类型结构",
                "evidence": f"检索政策中“{conc['top']}”类占比约 {conc['top_share']:.0f}%，前 3 类合计 {conc['cr']:.0f}%（CR3）。",
                "interpretation": "申报指南占比高意味当前有较多可申报机会；公示公开偏多则说明已有较多同类项目落地，竞争需评估。",
            })

    # 5. 政策匹配广度 + 地区覆盖
    search_total = metric_map.get("政策检索结果")
    search_rows = core.get("search_records") or []
    if search_total and search_rows:
        regions = set()
        for r in search_rows:
            rg = r.get("地区")
            if rg and rg != "-":
                # split on comma to count provinces
                for part in str(rg).split(","):
                    part = part.strip()
                    if part:
                        regions.add(part)
        region_clause = f"，覆盖地区 {len(regions)} 个" if regions else ""
        insights.append({
            "feature": "政策匹配广度",
            "evidence": f"按关键词“{subject.get('keyword')}”检索命中政策 {search_total} 条{region_clause}。",
            "interpretation": "命中量反映关键词与现行政策的关联广度；覆盖地区多说明政策适用范围广，可结合类型与机构筛选高价值政策。",
        })

    if not insights:
        insights.append({
            "feature": "数据完整性",
            "evidence": "部分维度未返回有效数据。",
            "interpretation": "建议核对政策关键词或企业全称，或检查 MCP 连接与上游数据产品覆盖范围。",
        })
    return insights


def build_abstract(subject: Mapping[str, Any], core: Mapping[str, Any], metrics: List[Mapping[str, Any]]) -> str:
    kw = subject.get("keyword") or "目标政策关键词"
    parts = [f"本报告以政策关键词“{kw}”为检索对象，基于政策公开数据，系统呈现立项项目统计、项目归口分布、获批项目趋势、政策检索明细与政策详情。"]
    if metrics:
        kv = "、".join(f"{m['label']} {m['value']}" for m in metrics[:5])
        parts.append(f"关键指标包括：{kv}。")
    parts.append("报告同时给出项目申报层级、归口集中度与申报活跃度的结构化解读，便于政策申报规划与政府扶持分析参考。")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# Dry-run sample
# --------------------------------------------------------------------------- #

def build_dry_run_payload(keyword: str, filters: Mapping[str, Any]) -> Dict[str, Any]:
    try:
        sample = load_json_file(SAMPLE_PATH)
    except Exception:
        sample = {}
    sample = sample if isinstance(sample, dict) else {}
    enterprise_resolved = {"enterprise": filters.get("enterprise") or "", "resolved": bool(filters.get("enterprise")), "reason": "dry-run"}
    subject = sample.get("subject") or build_subject(keyword, enterprise_resolved, filters)
    subject = {**subject, "keyword": keyword, **{k: v for k, v in filters.items() if v}}
    core = sample.get("core_analysis") or {}
    metrics = sample.get("metrics") or []
    return _assemble(subject, core, metrics, dry_run=True)


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #

def _assemble(subject: Mapping[str, Any], core: Mapping[str, Any], metrics: List[Mapping[str, Any]], *, dry_run: bool) -> Dict[str, Any]:
    abstract = build_abstract(subject, core, metrics)
    records = build_records(core)
    insights = build_insights(subject, core, metrics)
    # Quality gate: count populated core-analysis sections.
    ca = core if isinstance(core, dict) else {}
    secs = ca.get("sections", [])
    if secs:
        total_secs = len(secs)
        populated = sum(1 for s in secs if isinstance(s, dict) and ca.get(s.get("key")) not in (None, "", [], {}))
    else:
        total_secs = max(1, len([k for k in ca if k != "sections"]))
        populated = sum(1 for k in ca if k != "sections" and ca.get(k) not in (None, "", [], {}))
    quality_report = {
        "total_sections": total_secs,
        "populated_sections": populated,
        "empty_sections": total_secs - populated,
        "coverage_pct": round(populated / max(1, total_secs) * 100),
    }
    if populated == 0:
        import sys
        print("⚠️ 质量门禁警告: 所有核心分析维度均无数据", file=sys.stderr)
    title = f"“{subject.get('keyword') or '目标关键词'}” 政策大数据报告"
    return {
        "report_type": REPORT_TYPE,
        "title": title,
        "banner": REPORT_BANNER,
        "subject": dict(subject),
        "abstract": abstract,
        "summary": abstract,
        "executive_summary": [item["interpretation"] for item in insights][:5] or [abstract[:120]],
        "metrics": list(metrics),
        "caliber": build_caliber(subject),
        "core_analysis": dict(core),
        "representative_records": records,
        "insights": insights,
        "data_source": {
            "mcp_server": "policy-mcp-server",
            "products": [
                {"name": "立项项目统计", "product_id": "66c702b725f04ab44cd24c9c"},
                {"name": "企业模糊查询", "product_id": "675cea1f0e009a9ea37edaa1"},
                {"name": "政策详情", "product_id": "66c702b725f04ab44cd24cd6"},
                {"name": "政策检索", "product_id": "66c702b725f04ab44cd24ceb"},
            ],
            "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "dry_run": dry_run,
            "quality_report": quality_report,
        },
    }


def build_payload(keyword: str, filters: Mapping[str, Any], page_size: int) -> Dict[str, Any]:
    # 1. 政策检索（关键词驱动，始终执行）
    search_args: Dict[str, Any] = {
        "matchKeyword": keyword,
        "pnType": filters.get("pn_type") or "全部",
        "pageIndex": 1,
        "pageSize": page_size,
    }
    if filters.get("agency"):
        search_args["agency"] = filters["agency"]
    if filters.get("address"):
        search_args["address"] = filters["address"]
    search = _safe_call(T_POLICY_SEARCH, search_args)
    search_total = _safe_total(search) if isinstance(search, dict) else None

    # 2. 立项项目统计（企业驱动，仅在提供 --enterprise 时执行）
    approved: Any = {}
    enterprise_resolved: Dict[str, Any] = {"enterprise": "", "resolved": False, "reason": "未提供企业主体"}
    if filters.get("enterprise"):
        enterprise_resolved = resolve_enterprise_name(filters["enterprise"])
        if enterprise_resolved.get("enterprise"):
            approved = _safe_call(T_APPROVED_STATS, {
                "matchKeyword": enterprise_resolved["enterprise"],
                "keywordType": "name",
            })

    # 3. 政策详情（仅在提供 --policy-id 时执行）
    policy_info: Any = {}
    if filters.get("policy_id"):
        policy_info = _safe_call(T_POLICY_INFO, {"matchKeyword": filters["policy_id"]})

    subject = build_subject(keyword, enterprise_resolved, filters)
    core = build_core_analysis(approved, search, policy_info, subject)
    metrics = build_metrics(approved if isinstance(approved, dict) else {}, search_total)
    # --- Enterprise profile enrichment (from fuzzy_search) ---
    _enrich_metrics_with_profile(metrics, enterprise_resolved.get("record") if isinstance(enterprise_resolved, dict) else None)
    _derive_core_metrics(metrics, core if isinstance(core, dict) else {})
    return _assemble(subject, core, metrics, dry_run=False)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(description="Compose a policy big-data report via the policy MCP.")
    parser.add_argument("--keyword", required=True, help="政策关键词（政策法规/申报指南/公示公告关键词）")
    parser.add_argument("--enterprise", default=None, help="可选企业全称，用于启用立项项目统计（关键词将自动模糊补全）")
    parser.add_argument("--pn-type", default="全部", help="政策类型：全部 / 申报指南 / 公示公开 / 其他政策")
    parser.add_argument("--agency", default=None, help="可选发布机构过滤")
    parser.add_argument("--address", default=None, help="可选地区过滤，例如 [[\"福建省\"]] 或 [[\"国家部委\"]]；以 JSON 字符串传入")
    parser.add_argument("--policy-id", default=None, help="可选政策 id，用于查询政策详情")
    parser.add_argument("--page-size", type=int, default=10, help="政策检索明细分页大小（最多 50）")
    parser.add_argument("--dry-run", action="store_true", help="不调用真实 MCP，使用样例数据组装报告骨架")
    parser.add_argument("--output", help="输出 JSON 路径；省略则打印到 stdout")
    parser.add_argument("--report-output", help="同时输出 HTML 报告（.html）与 Markdown 报告（.md）")
    parser.add_argument("--pdf-output", help="额外输出 PDF 报告（.pdf）；需要 Playwright + Chromium")
    args = parser.parse_args()

    filters = {
        "enterprise": args.enterprise,
        "pn_type": args.pn_type,
        "agency": args.agency,
        "address": args.address,
        "policy_id": args.policy_id,
    }

    if args.dry_run:
        payload = build_dry_run_payload(args.keyword, filters)
    else:
        payload = build_payload(args.keyword, filters, args.page_size)

    if args.output:
        out = pathlib.Path(args.output).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json_dumps(payload, pretty=True), encoding="utf-8")
        print_json({"ok": True, "json": str(out), "dry_run": args.dry_run})
    else:
        print_json(payload)

    if args.report_output:
        base_out = pathlib.Path(args.report_output).expanduser()
        base_out.parent.mkdir(parents=True, exist_ok=True)
        html_path = base_out.with_suffix(".html") if base_out.suffix.lower() not in (".html", ".htm") else base_out
        md_path = html_path.with_suffix(".md")
        html_path.write_text(render_html(payload), encoding="utf-8")
        md_path.write_text(render_markdown(payload), encoding="utf-8")
        if args.pdf_output:
            pdf_path = pathlib.Path(args.pdf_output).expanduser()
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            html_to_pdf(render_html(payload), str(pdf_path))
        print_json({"ok": True, "html": str(html_path), "markdown": str(md_path), "pdf": str(pdf_path) if args.pdf_output else None, "dry_run": args.dry_run})


if __name__ == "__main__":
    main()
