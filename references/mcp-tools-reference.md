# MCP 工具参考 — policy-mcp-server

本 skill 连接的 MCP server：`handaas-mcp-server/policy-mcp-server`（“政策大数据”）。

> **重要**：政策报告是**关键词驱动**的。`--keyword`（政策关键词）是主输入，用于政策检索；
> 可选 `--enterprise`（企业全称，关键词会自动模糊补全）启用立项项目统计；
> 可选 `--policy-id` 查询单条政策详情。

## 通用约定

- `keywordType` 枚举：`name`（企业名称）/ `nameId`（企业 id）/ `regNumber`（注册号）/ `socialCreditCode`（统一社会信用代码）。仅 `approved_project_stats` 使用。
- `pnType` 枚举：`全部` / `申报指南` / `公示公开` / `其他政策`。
- 分页：`pageIndex` 从 1 开始；`pageSize` 单页最多 50。
- 地区 `address`：list of list 格式，如 `[["福建省"]]`、`[["贵州省","安顺市","平坝县"]]`、`[["国家部委"]]`、`[["北京"]]`；以 JSON 字符串从 CLI 传入。

---

## 工具清单

### 1. `policy_bigdata_policy_search` — 政策检索

用途：按政策关键词、政策类型、发布机构、地区检索政策法规 / 申报指南 / 公示公告。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 政策法规 / 申报指南 / 公示公告关键词 |
| `pnType` | string | 否 | 政策类型：全部（默认）/ 申报指南 / 公示公开 / 其他政策 |
| `agency` | string | 否 | 发布机构 |
| `address` | list of list | 否 | 地区，例如 `[["福建省"]]`、`[["国家部委"]]` |
| `policyPubStartTime` | string | 否 | 发布开始日期（格式 `2025-01-01`） |
| `policyPubEndTime` | string | 否 | 发布结束日期（格式 `2025-01-01`） |
| `pageIndex` | int | 否 | 从 1 开始（默认 1） |
| `pageSize` | int | 否 | 单页最多 50（默认 10） |

返回（list + `total`）：`pnId`（政策 id）、`pnTitle`（政策标题）、`pnAgency`（发布机构）、`pnRegion`（发布地区）、`pnType`（政策类型）、`pnPublishDate`（发布时间）、`pnText`（政策内容）等。

product_id：`66c702b725f04ab44cd24ceb`。

---

### 2. `policy_bigdata_approved_project_stats` — 立项项目统计

用途：按企业主体返回该企业获批项目的级别分布（国家/省/市/区）、归口主管机构分布、获批项目趋势与补贴金额趋势。**仅当提供 `--enterprise` 时调用。**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 企业名称 / 注册号 / 统一社会信用代码 / 企业 id（无全称则先调 fuzzy_search） |
| `keywordType` | string | 否 | 主体类型：name / nameId / regNumber / socialCreditCode |

返回：`ppeAgencyStat`（归口分布 list of {agency,count}）、`ppeLevelStat`（级别分布 dict：municipalProjectCount / districtProjectCount）、`ppeYearAmountStat`（补贴金额趋势 list of {year,amount}）、`ppeYearProjectStat`（获批项目趋势 list of {year,count}）、`provincialProjectCount`（省级项目数）、`nationalProjectCount`（国家级项目数）。

product_id：`66c702b725f04ab44cd24c9c`。

---

### 3. `policy_bigdata_policy_info` — 政策详情

用途：按政策 id 查询单条政策的详情，含发布机构、正文、附件、可能关联项目。**仅当提供 `--policy-id` 时调用。**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 政策 id |

返回：`pnTitle`（政策标题）、`pnAgency`（发布机构）、`pnPublishDate`（发布时间）、`pnType`（政策类型）、`pnRegion`（发布地区）、`pnOriginUrl`（原文链接）、`pnText`（正文）、`pnFileList`（附件）、`relatedProjects`（可能关联项目 list of {agency,maxGrantMount,declaredLevel}）。

product_id：`66c702b725f04ab44cd24cd6`。

---

### 4. `policy_bigdata_fuzzy_search` — 关键词模糊查询企业

用途：根据企业名称 / 品牌 / 产品等关键词模糊查询企业列表，用于补全企业全称（仅当 `--enterprise` 不是全称时调用）。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 匹配关键词 |
| `pageIndex` | int | 否 | 分页开始位置（默认 1） |
| `pageSize` | int | 否 | 单页最多 50 |

返回：`total` + 企业列表（`name`、`nameId`、`regCapitalValue`、`foundTime`、`operStatus`、`address`、`legalRepresentative`、`enterpriseType`、`catchReason` 等）。

product_id：`675cea1f0e009a9ea37edaa1`。

---

## 推荐调用顺序（报告编排）

1. `policy_bigdata_policy_search` → 按政策关键词检索明细（始终调用）。
2. （若提供 `--enterprise`）`policy_bigdata_approved_project_stats` → 立项项目统计。
3. （若提供 `--policy-id`）`policy_bigdata_policy_info` → 政策详情。
4. （仅当 `--enterprise` 不是全称）`policy_bigdata_fuzzy_search` → 补全企业全称后再调用步骤 2。

> 单次报告通常调用 1-3 个工具；政策检索始终以 `matchKeyword`（政策关键词）为主，立项统计以企业主体为主。
