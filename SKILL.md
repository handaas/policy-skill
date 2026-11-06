---
name: policy-report
description: Use for generating a professional policy big-data report (政策大数据报告) from the HandaaS policy MCP — covering 立项项目统计、项目归口分布、获批项目趋势、政策检索明细、政策详情. Trigger when users ask for “政策大数据报告”, “政策分析报告”, “查政策”, “政策检索”, “政策申报指南”, “立项项目统计”, “补贴政策”, or “企业获批项目”. Driven by a policy keyword (--keyword); optionally combine an enterprise (--enterprise) for approved-project statistics or a --policy-id for policy details. Infer intent, pick the right MCP tools, and produce HTML + Markdown + JSON reports automatically. MCP 服务名称触发词：政策动态追踪。
---

# 政策大数据报告

## 用户契约

把“政策大数据报告”作为面向用户的调用短语。`policy-report` 仅为内部包名。

当本 skill 处于激活状态：

1. 不要向用户索要 product_id、MCP 工具名、API 字段、内部参数或凭证信息；只接受政策关键词、（可选）企业名称、政策 id。
2. 接受自然目标，例如“查一下专精特新相关政策”“给我一份高企认定的政策报告”“看看这家公司获批过哪些项目”“检索某条政策的详情”。
3. 政策检索以**政策关键词**为主输入；当用户附带企业名称时，自动模糊补全企业全称并启用立项项目统计。
4. 保留上游 total；当前页区分“标题确认”“正文线索”“未命中”，并按标题+机构+日期标重复。类型、词频、月份聚合只使用标题确认且去重样本；正文命中仅作待复核线索，不猜本地过滤后的 total。
5. 优先使用 MCP 连接（`POLICY_MCP_URL` Remote MCP 或本地 `handaas-mcp-server/policy-mcp-server`）；不要让用户处理签名或凭证。
6. 同时产出 HTML（可分享交付）、Markdown（知识库 / wiki）、JSON（系统集成）三类产物。
7. 报告正文必须是专业研究报告风格：只见政策事实与结构化数据，绝不出现工具名、入参、product_id、内部字段或空表。
8. 绝不打印 `secret_id`、`secret_key`、签名、token 或原始签名请求。
9. 默认 dry-run；真实付费 / 凭证调用需用户明确要求且 MCP 连接配置完整。
10. 数据为空时明确说明数据范围 / 口径（例如未提供企业导致立项项目统计为空），不渲染空表、不臆造事实。


- MCP 返回的嵌套 JSON 字符串（如金额 `{"coinType":"人民币","value":430000000.0}`、地址 `{"city":"杭州市",...}`）必须解析为可读文本（如"4.30 亿 人民币"、"浙江省杭州市"），绝不在报告正文、表格或指标中输出原始 JSON 字符串。
- 报告所有章节标题、指标卡标签必须用中文；`core_analysis.sections` 的 `title` 字段必须中文，不可显示英文 key（如 `holders`、`investments`）。
- 指标值必须可读化：金额格式为"X 亿/万 + 币种"，地址拼接省市区，比率显示百分号。详见 `references/report-output.md` 的「数据格式约束」。

## 内容整理与交付审校（强制）

1. **政策文本 ≠ 企业资格**：检索到政策、申报指南或公示，只说明政策存在；不得写成企业“可申报”“符合条件”“已获补贴/资助”。只有立项项目统计中的计数可作为获批项目证据，且仍不推断金额与企业能力。
2. **阶段与类型分离**：申报指南、公示公开、其他政策是政策文本类型，不是审批结果；已按类型筛选时，不再输出“某类型占比 100%”的结构结论。
3. **相关性分层**：标题确认、正文线索、未命中必须分开；只有标题确认且按“标题+机构+日期”去重的样本可做主题聚合，正文命中仅作待复核线索。
4. **总数可能截断**：上游返回 10000 时按“可能为上限/部分结果”处理，不把它当完整政策总量，不与样本量相除。
5. **词频不是主题**：固定词表计数为机械线索，同义词、否定句和模板重复未处理；不得把“高频词”直接表述为政策重点或企业机会。
6. **时间与样本限制**：当前年度为不完整年度，不参与项目趋势同比；最新两个年度任一 <10 个时按小样本披露规则只列计数、不作升降判断（该阈值是报告规则，不是统计显著性结论）；趋势数据止于早年时须注明。正常生成与离线修订均调用 `apply_content_review(report)`。

## MCP 服务入口

- MCP 服务当前名称：政策动态追踪（连接仍使用原服务目录标识）。

- 上游 MCP 项目：`handaas-mcp-server/policy-mcp-server`（位于 `HANDAAS_MCP_SERVER_ROOT` 或本仓库同级目录）。
- Remote MCP：设置环境变量 `POLICY_MCP_URL`（streamable-http），可选 `POLICY_MCP_TOKEN`。
- 本地 MCP：设置 `HANDAAS_MCP_SERVER_ROOT` 指向 `handaas-mcp-server` 仓库根目录；该 server 自己的 `.env` 提供 `INTEGRATOR_ID` / `SECRET_ID` / `SECRET_KEY`。
- 首次真实查询前，运行 `scripts/mcp_client.py ping` 与 `scripts/mcp_client.py list-tools` 验证连通。

## 按需加载 references

- 不清楚该 MCP 有哪些工具、参数、返回字段、何时调用：`references/mcp-tools-reference.md`。
- 报告结构、章节、质量底线、渲染工作流：`references/report-output.md`。

## 付费调用与预算约束（必读）

1. 每次业务工具调用与每次明细翻页都可能计费；想要 total/页数只是为了精确规划，不构成默认全量拉取的授权。
2. 调用前先推演所需结论与数据维度，确定工具/参数计划、必要页数与最大调用预算。total 未知时，第一个必要明细页既是数据又是 total 探测，绝不为此重复付费。
3. 优先用统计/聚合接口（`policy_bigdata_approved_project_stats`）回答问题；只在结论、图表、代表记录或明确全量/计数需求确实需要时取政策检索明细；`policy_bigdata_policy_info` 仅在明确给出 `--policy-id` 时按需调用。
4. 用 schema 允许的最大合理 pageSize 取所需行数，证据/样本目标满足即停，且不超过明确预算。更多调用必须有具体缺失结论支撑，不因为"补齐所有章节"而追加；不得用样本分布冒充全量结论。预算不足以支撑关键结论时，先说明证据缺口与预计额外调用数，等明确授权后再扩大——不得静默降级结论，也不得静默扩大计费范围。
5. 当前任务/报告内复用相同请求（含第一页规划数据）：同一 tool+相同参数只调用一次；不要为渲染重跑 compose/MCP——用已保存 JSON 本地重渲染；不得自动重试、重复取统计/明细或并行获取相同数据；补充查询先列明缺口并复用已返回记录。
6. `total_pages`/`remaining_pages` 是按请求 pageSize 的估算；短但非空的页仍有剩余记录时在预算内继续。只有稳定有效 total 与实际扫描数一致才算完整采集；报错、提前空页、重复页、total 变更/缺失、数量溢出均为不完整。显式预算或样本目标停止即部分采集，绝不宣称全量。不调用无关或不必要维度的工具。

本 skill 分页明细接口：`policy_bigdata_policy_search`（政策检索，pageSize≤50），预算经 `--max-pages`（默认 1）传递；`policy_bigdata_approved_project_stats`（统计）、`policy_bigdata_policy_info`（按 id 详情）与模糊补全为单次调用，不进入分页预算。

## 意图路由

| 用户意图 | 内部工作流 |
| --- | --- |
| 按政策关键词检索政策 | `compose_report.py --keyword ...` |
| 关键词检索 + 企业立项项目统计 | `compose_report.py --keyword ... --enterprise ...` |
| 查询某条政策详情 | `compose_report.py --keyword ... --policy-id <id>` |
| 按政策类型过滤（申报指南 / 公示公开 / 其他政策） | `compose_report.py --keyword ... --pn-type ...` |
| 按发布机构 / 地区过滤 | `compose_report.py --keyword ... --agency ... --address ...` |
| 只给企业关键词（不是全称） | 先 `policy_bigdata_fuzzy_search` 补全全称，再查立项项目统计 |
| 只要 JSON / 只要 HTML / 只要 Markdown | 用 `--output`（JSON）或 `--report-output`（HTML+MD），或 `render_report.py` 重渲染 |
| 连接 / 工具不存在 / 传参错误 | `mcp_client.py ping` / `list-tools` 排查；报脱敏后的缺失项 |

## Golden path for 政策大数据报告

1. **解析政策关键词**：`--keyword` 是必填的主输入，直接用于政策检索。
2. **（可选）解析企业全称**：若用户附带企业且输入含“公司/集团/有限/院/厂/中心/事务所/合作社/合伙”等后缀视为全称；否则调 `policy_bigdata_fuzzy_search` 取首个命中，用于立项项目统计。
3. **调用政策工具**：`policy_bigdata_policy_search`（检索明细，始终调用）、`policy_bigdata_approved_project_stats`（立项统计，仅在提供企业时）、`policy_bigdata_policy_info`（政策详情，仅在提供 `--policy-id` 时）。
4. **组装统一报告**：核心分析含立项项目统计（KV）、项目归口分布（表）、获批项目趋势（表）、政策检索明细（表）、政策详情（KV，可选）。
5. **渲染三件套**：`compose_report.py --keyword ... [--enterprise ...] [--policy-id ...] --output ... --report-output ...` 直接产出 JSON + HTML + Markdown。
6. **返回路径**：返回 JSON、HTML、Markdown 文件路径，以及政策关键词 / 企业全称映射与数据口径。

- **渲染前置检查**：执行会产出含图表 HTML / PDF 的报告命令前，先验证 `node --version` 与本 skill 自带 `assets/vendor/echarts.min.js` 存在；内嵌静态 SVG 的生成需要 Node.js（推荐当前 LTS，无需 npm 包），缺失时报告生成明确报错。查看已生成的 HTML 与 Markdown 输出不需要 Node。

## 脚本速查

```bash
# 校验连接配置（脱敏）
python scripts/validate_config.py --allow-placeholders

# 连通性自测
python scripts/mcp_client.py ping
python scripts/mcp_client.py list-tools

# 干跑（不调真实 API，用样例数据组装报告骨架）
python scripts/compose_report.py \
  --keyword "专精特新" \
  --dry-run \
  --output output/policy.json \
  --report-output output/policy.html

# 真实查询 + 渲染（需 MCP 连接就绪）
python scripts/compose_report.py \
  --keyword "专精特新" \
  --max-pages 1 \
  --output output/policy.json \
  --report-output output/policy.html

# 关键词检索 + 企业立项项目统计
python scripts/compose_report.py --keyword "专精特新" --enterprise "示例科技有限公司" --report-output output/policy_full.html

# 按政策类型 / 发布机构 / 地区过滤
python scripts/compose_report.py --keyword "高企认定" --pn-type 申报指南 --agency "工业和信息化部" --report-output output/policy_filtered.html

# 查询某条政策详情
python scripts/compose_report.py --keyword "专精特新" --policy-id "<政策id>" --report-output output/policy_detail.html

# 手动调单个工具
python scripts/mcp_client.py call-tool \
  --tool policy_bigdata_policy_search \
  --arguments-json '{"matchKeyword": "专精特新", "pnType": "全部", "pageIndex": 1, "pageSize": 10}'

# 重渲染已有 JSON
python scripts/render_report.py --input output/policy.json --output output/policy.html
python scripts/render_report.py --input output/policy.json --output output/policy.md
```

## 输出字段

- `subject`：政策关键词、企业全称（可选）、政策类型、发布机构、地区、政策 id。
- `abstract` / `summary`：封面摘要与详细摘要。
- `metrics`：国家级 / 省级 / 市级 / 区级项目数、政策检索结果数（部分仅在提供企业时填充）。
- `caliber`：匹配对象、匹配方式、数据范围、产品、局限。
- `core_analysis`：立项项目统计（KV）、项目归口分布（表）、获批项目趋势（表）、政策检索明细（表）、政策详情（KV，可选）。
- `representative_records`：代表性政策记录（标题 / 机构 / 类型 / 发布日期）。
- `insights`：结构化解读（项目申报层级 / 归口集中度 / 申报活跃度 / 政策匹配广度）。
- `data_source`：MCP server、数据产品、生成时间、是否 dry-run。

若 API 调用失败，明确报出缺失的配置 / 缺失的工具 / MCP 错误 / 参数校验错误 / 上游网络错误，给出 dry-run 命令或配置步骤，绝不暴露密钥。
