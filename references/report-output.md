# 报告输出 — 政策大数据报告

本文件规定 `policy-report` skill 产出的报告结构、质量底线与渲染工作流。所有产物遵循 `AGENTS.md` 的统一 JSON 骨架与本 skill 的领域裁剪。

## 默认展示模式

- HTML：可分享 / 可交付的可视化报告；独立本地文件，内嵌 CSS，无调试 / 内部段落。
- Markdown：知识库 / wiki / PRD / 后续手工编辑。
- JSON：系统集成或二次处理。

`compose_report.py` 通过 `--report-output <path>` 同时产出 HTML + Markdown；`--output <path>` 产出 JSON。`render_report.py` 可基于已有 JSON 重渲染。

## 报告结构（7 章）

1. **报告摘要**：分析对象（政策关键词 / 企业）、数据覆盖范围、核心发现、关键指标卡。
2. **查询对象与口径**：政策关键词、企业全称、匹配方式、数据范围、产品、局限。
3. **数据总览**：国家级 / 省级 / 市级 / 区级项目数、政策检索结果数等指标卡（部分仅在提供企业时填充）。
4. **核心分析**（政策专属子章节，由 `core_analysis.sections` 驱动渲染）：
   - 立项项目统计（KV：各级别项目数；未提供企业时给出说明）。
   - 项目归口分布（表：主管机构 / 项目数量）。
   - 获批项目趋势（表：年份 / 获批项目数）。
   - 政策检索明细（表：政策标题 / 发布机构 / 地区 / 政策类型 / 发布日期）。
   - 政策详情（KV，仅在 `--policy-id` 提供时出现：政策标题 / 发布机构 / 发布时间 / 政策类型 / 原文链接 / 正文摘要）。
5. **代表性记录**：关键政策记录 Top N（标题 / 机构 / 类型 / 发布日期）。
6. **特征与洞察**：结构化解读（项目申报层级 / 归口集中度 / 申报活跃度 / 政策匹配广度），每条含 `feature` / `evidence` / `interpretation`。
7. **数据口径与来源**：MCP server、数据产品、生成时间、是否 dry-run。

## 质量底线

- 报告脱离 Skill 上下文也可独立阅读；正文只见政策事实与结构化数据。
- 绝不出现工具名、入参（如 `matchKeyword=...`）、product_id、内部字段名、空表、调试信息。
- HTML 采用研究报告视觉风格：A4 风、灰色顶部条纹、蓝色报告横幅、左侧目录 / 范围侧栏、深蓝章节标题、深蓝表头、浅蓝斑马行、打印友好分页。
- 数据为空时明确说明数据范围 / 口径（如未提供企业导致立项项目统计为空），不渲染空表、不臆造事实。
- 绝不打印 `secret_id` / `secret_key` / 签名 / token / 原始签名请求。
- 自动补全企业全称时，在报告口径中说明“由关键词模糊查询补全”。

### 数据格式约束（铁律）

以下约束适用于 compose_report.py 组装数据与 render_report.py 渲染输出的全过程：

1. **嵌套 JSON 字符串必须解析**：MCP 返回的某些字段（如 `regCapital`、`addressValue`、`subscriptionDetail`）可能是 JSON 字符串（例：`{"coinType":"人民币","value":430000000.0}`）。compose 层必须调用 `_unwrap_json_str()` / `_parse_reg_capital()` / `_flatten_addr()` 解析为可读文本（如"4.30 亿 人民币"、"浙江省杭州市滨江区..."）。绝不在报告正文、表格单元格或指标值中输出原始 JSON 字符串。

2. **section 标题必须用中文**：`core_analysis.sections` 数组中每个 section 的 `title` 字段必须使用中文（如"企业基本信息"、"对外投资"、"股东信息"）。`key` 字段用英文 snake_case 供程序索引，但 `title` 绝不可显示英文 key。即使缺少 sections 数组，渲染器回退逻辑也内置了 `_TITLE_MAP` 映射。

3. **指标值可读化**：所有 `metrics` 的 `value` 字段必须格式化为人类可读形式：
   - 金额：`10995210218.0` → `109.95 亿 人民币`（≥1 亿用亿，≥1 万用万）
   - 地址：嵌套 dict → 省+市+区拼接 或取 `value` 字段
   - 比率：`0.8858` → `88.58%`
   - 日期：保持 `yyyy-MM-dd` 格式
   - "-" 表示字段缺失（MCP 未返回）；`0` 表示真实为零

4. **企业画像指标提取**：有 fuzzy_search 的 skill 必须从返回的 record 中提取 `regCapitalValue` / `foundTime` / `operStatus` / `enterpriseType` / `legalRepresentative`，通过 `_enrich_metrics_with_profile()` 追加为指标卡。

5. **分布派生指标**：`_derive_core_metrics()` 从 core_analysis 各 section 计算分布指标（CR3 集中度、覆盖城市/平台/类目数、价格区间、正面占比等），确保指标总数 M ≥ 6。

## 工作流

```bash
# 1. 干跑（不调真实 API，用样例数据组装报告骨架）
python scripts/compose_report.py \
  --keyword "专精特新" \
  --dry-run \
  --output output/policy.json \
  --report-output output/policy.html

# 2. 真实查询 + 渲染（需 MCP 连接就绪）
python scripts/compose_report.py \
  --keyword "专精特新" \
  --output output/policy.json \
  --report-output output/policy.html

# 3. 关键词检索 + 企业立项项目统计
python scripts/compose_report.py --keyword "专精特新" --enterprise "示例科技有限公司" --report-output output/policy_full.html

# 4. 按政策类型 / 发布机构 / 地区过滤
python scripts/compose_report.py --keyword "高企认定" --pn-type 申报指南 --agency "工业和信息化部" --report-output output/policy_filtered.html

# 5. 查询某条政策详情
python scripts/compose_report.py --keyword "专精特新" --policy-id "<政策id>" --report-output output/policy_detail.html

# 6. 重渲染已有 JSON
python scripts/render_report.py --input output/policy.json --output output/policy.html
python scripts/render_report.py --input output/policy.json --output output/policy.md
```

返回：JSON 路径、HTML 路径、Markdown 路径，以及政策关键词映射与数据口径摘要。
