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
import copy
import datetime as dt
import json
import pathlib
from typing import Any, Dict, List, Mapping, Optional, Sequence

from common import REPORT_BANNER, REPORT_TYPE, attach_pagination, call_tool_once, collect_detail_pages, die, json_dumps, load_json_file, paid_call_scope, print_json
import mcp_client
from semantic_review import prepare_draft
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
        if value.get("_mcp_error") or value.get("_error") or value.get("isError") is True or value.get("error"):
            return True
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
        if set(value) <= {"text", "error", "code", "_error", "_mcp_error"}:
            return []
        for key in ("resultList", "list", "items", "data"):
            if isinstance(value.get(key), list):
                return value[key]
    if value in (None, "", {}):
        return []
    return []


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
        result = call_tool_once(mcp_client.call_tool, tool, arguments)
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


def _payload_status(payload: Any) -> str:
    if _is_api_error(payload):
        return "error"
    if isinstance(payload, dict) and str(payload.get("text") or "").strip() == "查询数据为空":
        return "empty"
    if _first_list(payload) or _safe_total(payload) is not None:
        return "success" if (_first_list(payload) or _safe_total(payload) not in (0, "0")) else "empty"
    if isinstance(payload, dict) and payload:
        return "success"
    return "empty"


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
    fuzzy_total = _int(_safe_total(fuzzy))
    if fuzzy_total is not None and fuzzy_total > 1:
        return {
            "keyword": raw,
            "enterprise": raw,
            "resolved": False,
            "reason": f"模糊查询返回多候选（{fuzzy_total}），未静默选择首条",
            "fuzzy_total": fuzzy_total,
        }
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

SAMPLE_METRIC_LABELS = {"高频主题词", "最热主题", "覆盖月份", "发布机构数", "政策类型数"}


def _derive_core_metrics(metrics: List[Dict[str, Any]], core: Mapping[str, Any], subject: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """Derive policy metrics with explicit sample scope.

    "发布机构数" is computed from the retained page, so it is labeled as a
    sample count. Body keyword counts are mechanical occurrences, not themes.
    "政策类型数" is omitted when the query already filters by policy type,
    because the distribution is then fixed by the filter.
    """
    type_dist = core.get("type_dist", []) if isinstance(core, dict) else []
    keyword_freq = core.get("keyword_freq", []) if isinstance(core, dict) else []
    monthly = core.get("monthly_trend", []) if isinstance(core, dict) else []
    search = core.get("search_records", []) if isinstance(core, dict) else []
    pn_type = str((subject or {}).get("pn_type") or "全部")
    if isinstance(type_dist, list) and len(type_dist) >= 2 and pn_type in ("", "全部"):
        metrics.append({"label": "政策类型数", "value": str(len(type_dist)), "hint": "本页归纳样本涉及的政策类型数（非全量）"})
    if isinstance(keyword_freq, list) and keyword_freq:
        metrics.append({"label": "有命中主题词数", "value": str(len(keyword_freq)), "hint": "固定词表中出现过的词数，不代表主题数"})
        try:
            top_kw = max(keyword_freq, key=lambda r: int(r.get("出现次数", "0")) if str(r.get("出现次数", "0")).isdigit() else 0)
            if top_kw.get("主题词"):
                metrics.append({"label": "高频词", "value": str(top_kw["主题词"]), "hint": "固定词表中出现次数最多的词（机械计数，非语义主题）"})
        except (ValueError, TypeError):
            pass
    if isinstance(monthly, list) and monthly:
        metrics.append({"label": "有政策月份数", "value": str(len(monthly)), "hint": "归纳样本中有政策发布的月份数"})
    if isinstance(search, list) and search:
        agencies = set(
            str(r.get("发布机构", "")) for r in search
            if r.get("发布机构") and r.get("相关性") == "标题确认" and r.get("重复标记") != "重复样本"
        )
        if agencies:
            metrics.append({"label": "样本内发布机构数", "value": str(len(agencies)), "hint": "本页标题确认且去重样本涉及的发布机构数（非全量）"})
    return metrics


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #

def build_subject(keyword: str, enterprise_resolved: Mapping[str, Any], filters: Mapping[str, Any]) -> Dict[str, Any]:
    enterprise_input = str(filters.get("enterprise") or "")
    resolved = bool(enterprise_resolved.get("resolved"))
    return {
        "keyword": keyword,
        "matchKeyword": keyword,
        "enterprise": (enterprise_resolved.get("enterprise") or "") if resolved else "",
        "enterprise_input": enterprise_input,
        "enterprise_resolved": resolved,
        "enterprise_resolve_reason": enterprise_resolved.get("reason", ""),
        "enterprise_blocked_reason": (enterprise_resolved.get("reason", "") if enterprise_input and not resolved else ""),
        "pn_type": filters.get("pn_type") or "全部",
        "agency": filters.get("agency") or "",
        "address": filters.get("address") or "",
        "policy_id": filters.get("policy_id") or "",
    }


def _approved_level_values(approved: Mapping[str, Any]) -> Dict[str, Any]:
    """Read all four project levels from the real nested ppeLevelStat shape.

    Older samples may expose national/provincial at the top level, so those are
    retained only as a compatibility fallback when the nested value is absent.
    """
    level_value = approved.get("ppeLevelStat")
    level = level_value if isinstance(level_value, dict) else {}
    return {
        key: level.get(key) if level.get(key) is not None else approved.get(key)
        for key in (
            "nationalProjectCount",
            "provincialProjectCount",
            "municipalProjectCount",
            "districtProjectCount",
        )
    }


def build_metrics(approved: Mapping[str, Any], search_total: Any) -> List[Dict[str, Any]]:
    metrics: List[Dict[str, Any]] = []
    a = approved if isinstance(approved, dict) else {}
    if a:
        level = _approved_level_values(a)
        # Compute total for level-share deltas.
        total_proj = 0.0
        for k in ("nationalProjectCount", "provincialProjectCount", "municipalProjectCount", "districtProjectCount"):
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

        m1: Dict[str, Any] = {"label": "国家级项目", "value": _text(level.get("nationalProjectCount")) or "-", "hint": "获批国家级项目数量"}
        m1.update(_share_delta(level.get("nationalProjectCount")))
        metrics.append(m1)
        m2: Dict[str, Any] = {"label": "省级项目", "value": _text(level.get("provincialProjectCount")) or "-", "hint": "获批省级项目数量"}
        m2.update(_share_delta(level.get("provincialProjectCount")))
        metrics.append(m2)
        if level:
            m3: Dict[str, Any] = {"label": "市级项目", "value": _text(level.get("municipalProjectCount")) or "-", "hint": "获批市级项目数量"}
            m3.update(_share_delta(level.get("municipalProjectCount")))
            metrics.append(m3)
            m4: Dict[str, Any] = {"label": "区级项目", "value": _text(level.get("districtProjectCount")) or "-", "hint": "获批区级项目数量"}
            m4.update(_share_delta(level.get("districtProjectCount")))
            metrics.append(m4)
    total_text = _text(search_total) if search_total is not None else "-"
    total_hint = "本次政策检索命中条数"
    if total_text.replace(",", "") in ("10000", "10000.0"):
        total_hint += "；上游返回 10000，可能为结果上限，按部分结果处理"
    metrics.append({"label": "政策检索结果", "value": total_text, "hint": total_hint})
    return [m for m in metrics if m.get("value") not in ("", None, "-")]


def build_caliber(subject: Mapping[str, Any]) -> Dict[str, Any]:
    parts = ["政策检索按政策关键词匹配", f"（政策类型={subject.get('pn_type', '全部')}）"]
    if subject.get("enterprise"):
        parts.append(f"；立项项目统计按企业主体“{subject.get('enterprise')}”匹配")
    products = [item["name"] for item in _requested_product_rows(subject)]
    limit = "数据来自政策公开数据库；少量字段可能存在更新延迟。检索总数可能受上游上限影响（例如返回 10000 条时按部分结果处理）；政策发布/申报指南不等同于企业符合条件或已获资助。"
    if subject.get("enterprise_blocked_reason"):
        limit += f" 企业主体未唯一解析（{subject.get('enterprise_blocked_reason')}），未执行企业立项统计；政策关键词检索仍为独立范围。"
    return {
        "match_target": f"政策关键词“{subject.get('keyword')}”" + (f" / 企业“{subject.get('enterprise')}”" if subject.get("enterprise") else ""),
        "match_type": "".join(parts),
        "data_scope": "、".join("政策检索明细" if item == "政策检索" else item for item in products),
        "products": products,
        "limit": limit,
    }


def _requested_product_rows(subject: Mapping[str, Any]) -> List[Dict[str, str]]:
    """List only products whose tools were requested for this report."""
    rows = [{"name": "政策检索", "product_id": "66c702b725f04ab44cd24ceb"}]
    reason = str(subject.get("enterprise_resolve_reason") or "")
    if subject.get("enterprise_input") and reason and reason not in ("视为企业全称", "未提供企业主体"):
        rows.append({"name": "企业模糊查询", "product_id": "675cea1f0e009a9ea37edaa1"})
    if subject.get("enterprise"):
        rows.append({"name": "立项项目统计", "product_id": "66c702b725f04ab44cd24c9c"})
    if subject.get("policy_id"):
        rows.append({"name": "政策详情", "product_id": "66c702b725f04ab44cd24cd6"})
    return rows


def build_core_analysis(approved: Any, search: Any, policy_info: Any, subject: Mapping[str, Any]) -> Dict[str, Any]:
    a = approved if isinstance(approved, dict) else {}
    pn_type = _text(subject.get("pn_type") or "全部")

    # 立项项目统计 KV + 表
    approved_kv: Dict[str, Any] = {}
    if a:
        level = _approved_level_values(a)
        for k, label in (
            ("nationalProjectCount", "国家级项目数"),
            ("provincialProjectCount", "省级项目数"),
            ("municipalProjectCount", "市级项目数"),
            ("districtProjectCount", "区级项目数"),
        ):
            if level.get(k) is not None:
                approved_kv[label] = _text(level.get(k))
    if subject.get("enterprise") and approved_kv:
        approved_kv.setdefault("匹配企业", subject.get("enterprise"))

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

    # 政策检索明细：逐条做本地关键词证据标注，并按稳定字段标记重复。
    search_rows = []
    title_confirmed_unique_items: List[Dict[str, Any]] = []
    seen_keys = set()
    keyword = _text(subject.get("keyword")).strip().lower()
    total = None
    if isinstance(search, dict):
        total = search.get("total")
    for item in _first_list(search):
        if not isinstance(item, dict):
            continue
        title = _text(item.get("pnTitle"))
        body = _text(item.get("pnText"))
        title_hit = bool(keyword and keyword in title.lower())
        body_hit = bool(keyword and keyword in body.lower())
        stable_key = (title, _text(item.get("pnAgency")), _text(item.get("pnPublishDate")))
        duplicate = stable_key in seen_keys
        seen_keys.add(stable_key)
        if title_hit and not duplicate:
            title_confirmed_unique_items.append(item)
        relevance = "标题确认" if title_hit else "正文线索" if body_hit else "未命中"
        search_rows.append({
            "政策标题": title or "-",
            "发布机构": _text(item.get("pnAgency")) or "-",
            "地区": _region_text(item.get("pnRegion")) or "-",
            "政策类型": _text(item.get("pnType")) or "-",
            "发布日期": _text(item.get("pnPublishDate")) or "-",
            "相关性": relevance,
            "命中位置": "标题+正文" if title_hit and body_hit else "标题" if title_hit else "正文" if body_hit else "-",
            "重复标记": "重复样本" if duplicate else "-",
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
        if r.get("相关性") != "标题确认" or r.get("重复标记") == "重复样本":
            continue
        t = r.get("政策类型")
        if t and t != "-":
            type_counts[t] = type_counts.get(t, 0) + 1
    type_dist_rows = [{"政策类型": k, "数量": str(n)} for k, n in sorted(type_counts.items(), key=lambda kv: kv[1], reverse=True)]

    # 政策主题词频（来源：pnText 全文）& 政策发布时间趋势（来源：pnPublishDate）
    keyword_freq_rows = _policy_keyword_freq_rows(title_confirmed_unique_items)
    monthly_trend_rows = _policy_monthly_trend_rows(title_confirmed_unique_items)
    relevance_summary = {
        "上游总数": total if total is not None else "-",
        "纳入样本数": len(search_rows),
        "标题确认样本数（含重复）": sum(1 for r in search_rows if r.get("相关性") == "标题确认"),
        "标题确认去重样本数": len(title_confirmed_unique_items),
        "正文线索样本数": sum(1 for r in search_rows if r.get("相关性") == "正文线索"),
        "未命中样本数": sum(1 for r in search_rows if r.get("相关性") == "未命中"),
        "重复样本数": sum(1 for r in search_rows if r.get("重复标记") == "重复样本"),
    }

    sections = [
        {"key": "approved_stats", "title": "立项项目统计", "kind": "kv"},
        {"key": "level_dist", "title": "项目层级分布", "kind": "donut", "note": "按申报层级（国家/省/市/区）统计获批项目占比", "chart": {"name": "层级", "value": "项目数"}, "columns": [("层级", "层级"), ("项目数", "项目数")]},
        {"key": "agency_stat", "title": "项目归口分布", "kind": "bar", "note": "按主管机构统计获批项目数量", "chart": {"name": "主管机构", "value": "项目数量", "orient": "v"}, "columns": [("主管机构", "主管机构"), ("项目数量", "项目数量")]},
        {"key": "year_project_stat", "title": "获批项目趋势", "kind": "line", "note": "按年度统计获批项目数量", "chart": {"x": "年份", "y": "获批项目数", "area": True}, "columns": [("年份", "年份"), ("获批项目数", "获批项目数")]},
        {"key": "type_dist", "title": "政策类型分布", "kind": "pie", "note": "仅按标题确认且去重的归纳样本统计政策类型", "chart": {"name": "政策类型", "value": "数量", "donut": True}, "columns": [("政策类型", "政策类型"), ("数量", "数量")]},
        {"key": "keyword_freq", "title": "政策文本高频词", "kind": "bar", "note": "仅对标题确认且去重样本的正文做固定词表机械计数；同义词未合并，不能等同于政策主题", "chart": {"name": "主题词", "value": "出现次数", "orient": "v"}, "columns": [("主题词", "主题词"), ("出现次数", "出现次数")]},
        {"key": "monthly_trend", "title": "政策发布时间趋势", "kind": "line", "note": "仅按标题确认且去重样本的发布月份统计", "chart": {"x": "月份", "y": "政策数量", "area": True}, "columns": [("月份", "月份"), ("政策数量", "政策数量")]},
        {"key": "relevance_summary", "title": "检索相关性校验", "kind": "kv", "note": "保留上游 total；主题聚合仅使用标题确认且按标题+机构+日期去重的归纳样本，正文命中仅作线索"},
        {"key": "search_records", "title": "政策检索明细", "kind": "table", "note": f"上游命中 {total if total is not None else '未知'} 条；本次归纳 {len(search_rows)} 条，标题确认相关去重样本 {len(title_confirmed_unique_items)} 条",
         "columns": [("政策标题", "政策标题"), ("发布机构", "发布机构"), ("地区", "地区"), ("政策类型", "政策类型"), ("发布日期", "发布日期"), ("相关性", "相关性"), ("命中位置", "命中位置"), ("重复标记", "重复标记")]},
    ]
    # A type distribution under an explicit type filter is tautological
    # ("公示公开 100%" when the query already selected 公示公开).
    if pn_type not in ("", "全部") or len(type_dist_rows) < 2:
        type_dist_rows = []
        sections = [s for s in sections if s.get("key") != "type_dist"]
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
        "relevance_summary": relevance_summary,
        "source_status": {
            "approved_stats": _payload_status(approved) if subject.get("enterprise") else "not_requested",
            "policy_search": _payload_status(search),
            "policy_info": _payload_status(policy_info) if subject.get("policy_id") else "not_requested",
        },
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
            "相关性": item.get("相关性") or "-",
            "重复标记": item.get("重复标记") or "-",
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


def _row_year(value: Any) -> Optional[int]:
    text = _text(value)
    return int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else None


def _year_trend_analysis(rows: List[Mapping[str, Any]], as_of_year: Optional[int] = None) -> Dict[str, Any]:
    """Direction/peak for the approved-project year series.

    Always drops the current partial year, even when fewer than two complete
    years remain (then returns an ``insufficient_years`` result instead of a
    YoY comparison). Skips direction when the latest two complete years have
    fewer than 10 approvals; always reports the latest year so a stale series
    (e.g. ending in 2023) is not described as "近年".
    """
    points: List[tuple[Any, float]] = []
    for r in rows:
        try:
            n = float(str(r.get("获批项目数", 0)).replace(",", ""))
        except (TypeError, ValueError):
            n = 0.0
        points.append((r.get("年份", "-"), n))
    if not points:
        return {}

    source_points = list(points)
    partial_period = None
    if as_of_year is not None:
        current = [(p, n) for p, n in points if _row_year(p) == as_of_year]
        if current:
            # The current year is always partial, so exclude it even when that
            # leaves fewer than two complete years (no YoY against a full year).
            partial_period = _text(current[-1][0])
            points = [(p, n) for p, n in points if _row_year(p) != as_of_year]
    if len(points) < 2:
        result: Dict[str, Any] = {
            "insufficient": "完整年度不足 2 期，未作趋势研判",
            "insufficient_reason": "insufficient_years",
            "complete_periods": len(points),
        }
        if partial_period:
            result["partial_period"] = partial_period
        if points:
            result["last_period"] = _text(points[-1][0])
            result["last"] = points[-1][1]
        elif partial_period:
            # Only the current partial year is visible; keep it as a snapshot.
            result["last_period"] = _text(source_points[-1][0])
            result["last"] = source_points[-1][1]
            result["latest_is_partial"] = True
        return result

    last_period, last_n = points[-1]
    prev_period, prev_n = points[-2]
    result: Dict[str, Any] = {
        "peak_period": _text(points[max(range(len(points)), key=lambda i: points[i][1])][0]),
        "peak_value": points[max(range(len(points)), key=lambda i: points[i][1])][1],
        "last_period": _text(last_period),
        "last": last_n,
        "partial_period": partial_period,
    }
    if prev_n < 10 or last_n < 10:
        result["insufficient"] = "最新两个年度任一少于 10 个，按小样本披露规则不输出同比"
        result["insufficient_reason"] = "small_sample"
        return result
    pct = (last_n - prev_n) / prev_n * 100
    if abs(pct) <= 5:
        result.update(direction="基本持平", yoy="")
    else:
        verb = "上升" if pct > 0 else "下降"
        result.update(direction=f"{verb} {abs(pct):.0f}%", yoy=f"{_text(last_period)} 年较 {_text(prev_period)} 年{verb} {abs(pct):.0f}%")
    if as_of_year is not None and _row_year(last_period) is not None and _row_year(last_period) < as_of_year - 1:
        result["stale"] = f"数据止于 {_text(last_period)}"
    return result


def _row_relevance(row: Mapping[str, Any]) -> Optional[str]:
    """Stored relevance label, or None when the source never evaluated it."""
    value = _text((row or {}).get("相关性")).strip()
    return value if value in ("标题确认", "正文线索", "未命中") else None


def build_insights(subject: Mapping[str, Any], core: Mapping[str, Any], metrics: Sequence[Mapping[str, Any]], as_of_year: Optional[int] = None) -> List[Dict[str, Any]]:
    insights: List[Dict[str, Any]] = []
    metric_map = {m["label"]: str(m["value"]) for m in metrics}
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
                "interpretation": "该占比仅描述已返回获批项目的层级结构，不能据此推断企业能力、政府认可程度或未来获批概率。",
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
                "interpretation": f"当前返回样本的归口分布{focus}；这是历史分布观察，不证明渠道稳定性或申报成效。",
            })

    # 3. 获批项目年度趋势
    year_stat = core.get("year_project_stat") or []
    if year_stat:
        ta = _year_trend_analysis(year_stat, as_of_year)
        if ta and not ta.get("insufficient"):
            latest_label = "最新完整年度" if ta.get("partial_period") else "最新年度"
            extra = f"；{ta['partial_period']} 年数据不完整，未纳入同比" if ta.get("partial_period") else ""
            if ta.get("stale"):
                extra += f"；{ta['stale']}，不代表当前年度"
            insights.append({
                "feature": "获批项目趋势",
                "evidence": f"峰值在“{ta['peak_period']}”（{ta['peak_value']:.0f} 个）；{latest_label} {ta['last_period']} 为 {ta['last']:.0f} 个，{ta.get('yoy') or ta['direction']}{extra}。",
                "interpretation": "年度变化仅是已返回获批项目数量的描述性趋势；没有外部政策、竞争或申报过程证据，不能解释变化原因，也不能外推未来获批概率。",
            })
        elif ta and ta.get("insufficient") and ta.get("last_period"):
            parts = []
            latest_label = "最新年度" if ta.get("latest_is_partial") else "最新完整年度"
            parts.append(f"{latest_label} {ta['last_period']} 为 {ta['last']:.0f} 个")
            if ta.get("latest_is_partial"):
                parts.append("该年度数据不完整，不参与同比")
            elif ta.get("partial_period"):
                parts.append(f"{ta['partial_period']} 年数据不完整，不参与同比")
            parts.append(ta["insufficient"])
            if ta.get("insufficient_reason") == "insufficient_years":
                interpretation = "完整年度不足 2 期时，本报告仅披露可见年度计数与当前年度快照，不输出同比方向或趋势结论；当前年度数据仍保留在获批项目趋势表中。"
            else:
                interpretation = "最新两个完整年度任一少于 10 个时，本报告按小样本处理，仅披露原始计数，不以同比方向作结论；该阈值为报告披露规则，不代表统计显著性。"
            insights.append({
                "feature": "获批项目趋势数据不足",
                "evidence": "；".join(parts) + "。",
                "interpretation": interpretation,
            })

    # 4. 政策类型集中度（基于检索结果聚合）
    type_dist = core.get("type_dist") or []
    pn_type = _text(subject.get("pn_type") or "全部")
    if type_dist and len(type_dist) >= 2 and pn_type in ("", "全部"):
        conc = _concentration_rows(type_dist, "政策类型", "数量", 3)
        if conc:
            insights.append({
                "feature": "政策类型结构",
                "evidence": f"归纳样本中“{conc['top']}”类占比约 {conc['top_share']:.0f}%，前 3 类合计 {conc['cr']:.0f}%（CR3）。",
                "interpretation": "该比例仅描述本页标题确认且去重样本的类型构成，不代表可申报机会数量、实施成效或竞争强度；已按类型筛选时该分布不具区分度。",
            })

    # 5. 政策匹配广度 + 地区覆盖
    search_total = metric_map.get("政策检索结果")
    search_rows = core.get("search_records") or []
    evaluated_rows = [r for r in search_rows if _row_relevance(r) is not None]
    unverified_rows = [r for r in search_rows if _row_relevance(r) is None]
    relevant_rows = [
        r for r in evaluated_rows
        if _row_relevance(r) == "标题确认" and r.get("重复标记") != "重复样本"
    ]
    if search_total and search_rows:
        regions = set()
        for r in relevant_rows:
            rg = r.get("地区")
            if rg and rg != "-":
                # split on comma to count provinces
                for part in str(rg).split(","):
                    part = part.strip()
                    if part:
                        regions.add(part)
        region_clause = f"，覆盖地区 {len(regions)} 个" if regions else ""
        cap_clause = "（可能为上游结果上限）" if str(search_total).replace(",", "") in ("10000", "10000.0") else ""
        if unverified_rows and not evaluated_rows:
            evidence = f"上游命中 {search_total} 条{cap_clause}；本页列示 {len(search_rows)} 条记录，但来源未包含本地相关性校验结果，标题确认样本数与地区覆盖无法核实（相关性未评估，保持未知）。"
            interpretation = "来源记录未提供相关性校验结果，无法区分标题确认与正文线索；报告未重新执行语义匹配，缺失评估保持未知，不推断为零值；上游总数未经本地相关性过滤，也可能受接口上限影响，不外推政策适用范围、申报资格或补贴金额。"
        elif unverified_rows:
            evidence = f"上游命中 {search_total} 条{cap_clause}；本页经校验的标题确认且去重样本 {len(relevant_rows)} 条{region_clause}；另有 {len(unverified_rows)} 条未包含相关性校验结果，未计入确认或否定样本。"
            interpretation = "来源记录中部分样本未提供相关性校验结果，无法判定其相关性，未按零值或未命中处理；上游总数未经本地相关性过滤，也可能受接口上限影响；正文命中仅作为待复核线索，只能基于已校验的标题确认样本做描述，不外推政策适用范围、申报资格或补贴金额。"
        else:
            evidence = f"上游命中 {search_total} 条{cap_clause}；本页经校验的标题确认且去重样本 {len(relevant_rows)} 条{region_clause}。"
            interpretation = "上游总数未经本地相关性过滤，也可能受接口上限影响；正文命中仅作为待复核线索，只能基于标题确认样本做描述，不外推政策适用范围、申报资格或补贴金额。"
        insights.append({
            "feature": "政策匹配广度",
            "evidence": evidence,
            "interpretation": interpretation,
        })

    if not insights:
        insights.append({
            "feature": "数据完整性",
            "evidence": "部分维度未返回有效数据。",
            "interpretation": "建议核对政策关键词或企业全称，或检查 MCP 连接与上游数据产品覆盖范围。",
        })
    return insights


def build_abstract(subject: Mapping[str, Any], core: Mapping[str, Any], metrics: Sequence[Mapping[str, Any]]) -> str:
    kw = subject.get("keyword") or "目标政策关键词"
    scopes = ["政策检索明细"]
    if subject.get("enterprise"):
        scopes.extend(["立项项目统计", "项目归口分布", "获批项目趋势"])
    if subject.get("policy_id"):
        scopes.append("政策详情")
    parts = [f"本报告以政策关键词“{kw}”为检索对象，基于政策公开数据，系统呈现{'、'.join(scopes)}。"]
    if subject.get("enterprise_blocked_reason"):
        parts.append("企业主体未唯一解析，未执行企业立项统计；以下内容仅为独立政策关键词检索结果。")
    if metrics:
        kv = "、".join(f"{m['label']} {m['value']}" for m in metrics[:5])
        parts.append(f"关键指标包括：{kv}。")
    parts.append("检索聚合仅使用归纳样本中标题确认且按稳定字段去重的样本；正文命中仅保留为待复核线索，上游 total 原样保留，分布与趋势不作因果解释。")
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
    return apply_content_review(_assemble(subject, core, metrics, dry_run=True))


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #

def _generated_year(value: Any) -> Optional[int]:
    text = _text(value)
    return int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else None


def _content_quality_report(core: Mapping[str, Any]) -> Dict[str, Any]:
    """Section-fill rate from final declared sections and actual bodies.

    0 is populated; only None/""/[]/{} count as empty. Not an accuracy score.
    """
    ca = core if isinstance(core, dict) else {}
    sections = [s for s in (ca.get("sections") or []) if isinstance(s, dict) and s.get("key")]

    def filled(value: Any) -> bool:
        return value is not None and value != "" and value != [] and value != {}

    if sections:
        total = len(sections)
        populated = sum(1 for spec in sections if filled(ca.get(spec["key"])))
    else:
        keys = [k for k in ca if k != "sections"]
        total = max(1, len(keys))
        populated = sum(1 for key in keys if filled(ca.get(key)))
    return {
        "total_sections": total,
        "populated_sections": populated,
        "empty_sections": total - populated,
        "coverage_pct": round(populated / max(1, total) * 100),
    }


def _assemble(subject: Mapping[str, Any], core: Mapping[str, Any], metrics: Sequence[Mapping[str, Any]], *, dry_run: bool) -> Dict[str, Any]:
    abstract = build_abstract(subject, core, metrics)
    records = build_records(core)
    generated_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    insights = build_insights(subject, core, metrics, _generated_year(generated_at))
    quality_report = _content_quality_report(core)
    if quality_report["populated_sections"] == 0:
        import sys
        print("⚠️ 质量门禁警告: 所有核心分析维度均无数据", file=sys.stderr)
    title = f"“{subject.get('keyword') or '目标关键词'}” 政策大数据报告"
    report = {
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
            "products": _requested_product_rows(subject),
            "generated_at": generated_at,
            "dry_run": dry_run,
            "source_status": core.get("source_status", {}),
            "blocked_reason": subject.get("enterprise_blocked_reason") or None,
            "quality_report": quality_report,
        },
    }
    return report


def _policy_derived_labels() -> set:
    return set(SAMPLE_METRIC_LABELS) | {"有命中主题词数", "高频词", "有政策月份数", "样本内发布机构数"}


def apply_content_review(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Rebuild policy narrative content from an existing payload.

    Pure/in-memory. Removes the tautological type distribution when the query is
    already type-filtered, normalizes sample-scope metric labels, removes raw
    field names from section notes, rebuilds the approved-project trend with
    partial-year / low-volume / staleness guards, and refreshes
    abstract/executive_summary/caliber.
    """
    out = copy.deepcopy(dict(report))
    core = out.setdefault("core_analysis", {})
    subject = out.get("subject") or {}
    pn_type = _text(subject.get("pn_type") or "全部")
    if pn_type not in ("", "全部") or len(core.get("type_dist") or []) < 2:
        core["type_dist"] = []
        core["sections"] = [s for s in (core.get("sections") or []) if not (isinstance(s, dict) and s.get("key") == "type_dist")]

    for spec in core.get("sections") or []:
        if not isinstance(spec, dict):
            continue
        key = spec.get("key")
        note = str(spec.get("note") or "")
        if key == "keyword_freq":
            spec["title"] = "政策文本高频词"
            spec["note"] = "仅对标题确认且去重样本的正文做固定词表机械计数；同义词未合并，不能等同于政策主题"
        elif key == "relevance_summary":
            spec["note"] = note.replace("上游 total", "上游总数")
        elif key == "search_records" and "10000" in note and "上限" not in note:
            spec["note"] = note + "；上游返回 10000，可能为结果上限"

    metrics: List[Dict[str, Any]] = []
    for metric in out.get("metrics") or []:
        if not isinstance(metric, dict) or metric.get("label") in _policy_derived_labels():
            continue
        item = dict(metric)
        if item.get("label") == "政策检索结果" and str(item.get("value", "")).replace(",", "") in ("10000", "10000.0"):
            item["hint"] = "本次政策检索命中条数；上游返回 10000，可能为结果上限，按部分结果处理"
        metrics.append(item)
    _derive_core_metrics(metrics, core, subject)
    out["metrics"] = metrics

    source = out.get("data_source") or {}
    insights = build_insights(subject, core, metrics, _generated_year(source.get("generated_at")))
    out["insights"] = insights
    abstract = build_abstract(subject, core, metrics)
    out["abstract"] = abstract
    out["summary"] = abstract
    out["executive_summary"] = [item["interpretation"] for item in insights][:5] or [abstract[:120]]
    out["caliber"] = build_caliber(subject)
    out.setdefault("data_source", {})["quality_report"] = _content_quality_report(core)
    return out


@paid_call_scope
def build_payload(keyword: str, filters: Mapping[str, Any], page_size: int, max_pages: int = 1) -> Dict[str, Any]:
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("max_pages 必须为正整数")
    # 1. 政策检索（关键词驱动，始终执行）
    search_args: Dict[str, Any] = {
        "matchKeyword": keyword,
        "pnType": filters.get("pn_type") or "全部",
        "pageSize": page_size,
    }
    if filters.get("agency"):
        search_args["agency"] = filters["agency"]
    if filters.get("address"):
        search_args["address"] = filters["address"]
    search = collect_detail_pages(
        _safe_call, T_POLICY_SEARCH, search_args,
        get_rows=_first_list, get_total=_safe_total, is_error=_is_api_error,
        max_pages=max_pages,
    )
    search_total = _safe_total(search) if isinstance(search, dict) else None

    # 2. 立项项目统计（企业驱动，仅在提供 --enterprise 时执行）
    approved: Any = {}
    enterprise_resolved: Dict[str, Any] = {"enterprise": "", "resolved": False, "reason": "未提供企业主体"}
    if filters.get("enterprise"):
        enterprise_resolved = resolve_enterprise_name(filters["enterprise"])
        if enterprise_resolved.get("resolved") and enterprise_resolved.get("enterprise"):
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
    _derive_core_metrics(metrics, core if isinstance(core, dict) else {}, subject)
    report = apply_content_review(_assemble(subject, core, metrics, dry_run=False))
    return attach_pagination(report, {"政策检索": search})


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
    parser.add_argument("--max-pages", type=int, default=1, help="政策检索明细最多付费翻页数（默认 1；仅在明确需要更多结论/证据时增大）")
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

    if not args.dry_run:
        if args.max_pages is not None and args.max_pages < 1:
            die("--max-pages 必须为正整数")

    if args.dry_run:
        payload = build_dry_run_payload(args.keyword, filters)
    else:
        payload = build_payload(args.keyword, filters, args.page_size, args.max_pages)

    payload = prepare_draft(payload)

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
