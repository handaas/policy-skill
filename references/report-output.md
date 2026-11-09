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

5. **分布派生指标**：发布机构数、主题词数、月份数均来自当前归纳样本，标签写“样本内/有命中”；已按政策类型筛选时不生成“政策类型数”。`_derive_core_metrics()` 是现行实现，必须使用样本限定标签。

## 内容审校清单（交付前逐项核对）

1. 政策标题/申报指南/公示只证明文本存在，不证明企业符合条件、可获补贴或已获批；不得补写金额、截止日期或适用对象。
2. 标题确认与正文线索分开；类型聚合只用标题确认且按标题+机构+日期去重的样本。来源记录缺少相关性校验字段时保持未知，不按 0 条计，也不依据标题重新推断。
3. 已按类型筛选时不展示类型占比；未筛选但只有 1 类时也不做 CR3 结构结论。
4. 上游返回 10000 按“可能为上限”处理；总数不与当前页样本相除。
5. 固定词表频次是机械线索，不能等同于政策主题；同义词合并必须有证据并保留原词。
6. 当前年度视为不完整年度，始终不参与项目趋势同比；剔除后即使完整年度不足 2 期，也只披露可见计数并说明数据不足，不输出同比方向，当前年度数据仍保留在趋势表。最新两个完整年度任一 <10 个或数据止于早年时，只披露计数并注明时间。该 <10 阈值是报告披露规则，不表述为统计显著性。

## AI 审校交付门禁（草稿 → final）

`compose_*` 正常生成与 `--dry-run` 只产出草稿：JSON 标记 `data_source.semantic_review.status=pending`，同名 HTML/Markdown 带“数据草稿（待AI语义审校）”提示，不能交付。`apply_content_review`/`organize_report` 是确定性整理，不是 AI 审校。

```bash
python scripts/review_report.py --input output/draft.json --request output/review-request.json
# 当前 AI 阅读请求中的 report 后写 output/ai-review.json
python scripts/review_report.py --input output/draft.json --review output/ai-review.json \
  --output output/final/report.json --report-output output/final/report.html
```

请求含 `source_sha256`、`report`、`visible_section_keys`、`instructions`、`response_fields`；响应：

```json
{
  "source_sha256": "<与请求一致>",
  "summary": [{"text": "逐句摘要", "sources": ["/core_analysis/..."], "kind": "fact"}],
  "normalizations": [{"sources": ["/core_analysis/..."], "category": "类别", "normalized": "规范表达", "evidence": "原文摘录", "reason": "理由"}],
  "insights": [{"feature": "特征", "evidence": "证据摘录", "interpretation": "解读", "sources": ["/metrics/0"]}]
}
```

- `source_sha256` 必须与请求一致；不一致须重新请求，不能沿用旧判断。
- `sources` 使用 JSON Pointer，只能指向本报告实际存在的 `/subject/…`、`/core_analysis/…`、`/metrics/…`、`/caliber/…`、`/data_source/…`、`/analysis_request/…`；`/core_analysis/sections`、`/data_source/semantic_review` 与旧 `abstract`/`summary`/`insights` 不是事实依据。
- 每项至少一个来源且不能重复路径；同一来源可支持多项判断；不能借其他企业、案例、记录或常识补本记录。
- `summary` 写 3–5 句有信息量的逐句摘要，`kind` 只能是 `fact`/`interpretation`/`limitation`；无数据依据只能写 `limitation`。`normalizations` 是独立视图，原文不改写；`evidence` 必填，由当前 AI 选择简洁可读的原文摘录作为“原文依据”列，并由同项 `sources` 支撑，完整原值仍保留在 draft/request 与来源 SHA 记录中；必须保留否定、最高、至少、至多、试用期、转正后、仅限、部分、疑似、待定、已失效等限定；不同主体、互斥金额或比例不能合并；没有实际归类需要时可为空；`insights` 的 `feature`、`evidence`、`interpretation` 都须由同一 `sources` 支撑；`evidence` 是实际 AI 写的简洁可读证据摘录，保留来源数字、单位与限定。
- 所有文本（含 `normalized`、`category`、`reason`、`evidence`、洞察）中的数字必须逐字出现在所引 values 中，不新造派生数字、不改精度；需要派生指标先在脚本计算再引用。
- 只使用本次数据，不调用 MCP/外部模型 API/新增查询。应用后 `status=reviewed` 并记录来源 SHA-256、原 `generated_at`、审校时间与判断证据；原查询时间和原件不变。`summary` 写入 `abstract`/`summary`/`executive_summary`，`normalizations` 写入 `core_analysis.ai_normalization`（独立表格），`insights` 写入 `insights`；原始字段不改写。

**展示与交付**：空板块连标题和目录一起隐藏，但只能影响展示，不能从 `quality_report` 分母抹去未覆盖维度或提高覆盖率；真实 `0`/`False` 保留，缺失/未查询不等于 0；失败只写口径限制，不推断“无风险”。AI 标准化/摘要是解释视图，不新增数据来源或覆盖率。核对最终 JSON/HTML/Markdown 后才交付；请求文件、草稿或手工润色件不算完成。

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

审校复核：完整保留有来源的摘要句子及采集层“数据缺口／主体解析受阻”提示；重审不得引用 `/core_analysis/ai_normalization` 等既有 AI 视图作为原始证据。HTML 与 Markdown 应使用一致的样本数量、趋势顺序及数据列，单元格中的竖线和换行不得破坏表格结构。
