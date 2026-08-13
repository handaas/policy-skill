---
name: policy-report
description: Use for generating a professional policy big-data report (政策大数据报告) from the HandaaS policy MCP — covering 立项项目统计、项目归口分布、获批项目趋势、政策检索明细、政策详情. Trigger when users ask for “政策大数据报告”, “政策分析报告”, “查政策”, “政策检索”, “政策申报指南”, “立项项目统计”, “补贴政策”, or “企业获批项目”. Driven by a policy keyword (--keyword); optionally combine an enterprise (--enterprise) for approved-project statistics or a --policy-id for policy details. Infer intent, pick the right MCP tools, and produce HTML + Markdown + JSON reports automatically.
---

# 政策大数据报告

## 用户契约

把“政策大数据报告”作为面向用户的调用短语。`policy-report` 仅为内部包名。

当本 skill 处于激活状态：

1. 不要向用户索要 product_id、MCP 工具名、API 字段、内部参数或凭证信息；只接受政策关键词、（可选）企业名称、政策 id。
2. 接受自然目标，例如“查一下专精特新相关政策”“给我一份高企认定的政策报告”“看看这家公司获批过哪些项目”“检索某条政策的详情”。
3. 政策检索以**政策关键词**为主输入；当用户附带企业名称时，自动模糊补全企业全称并启用立项项目统计。
4. 优先使用 MCP 连接（`POLICY_MCP_URL` Remote MCP 或本地 `handaas-mcp-server/policy-mcp-server`）；不要让用户处理签名或凭证。
5. 同时产出 HTML（可分享交付）、Markdown（知识库 / wiki）、JSON（系统集成）三类产物。
6. 报告正文必须是专业研究报告风格：只见政策事实与结构化数据，绝不出现工具名、入参、product_id、内部字段或空表。
7. 绝不打印 `secret_id`、`secret_key`、签名、token 或原始签名请求。
8. 默认 dry-run；真实付费 / 凭证调用需用户明确要求且 MCP 连接配置完整。
9. 数据为空时明确说明数据范围 / 口径（例如未提供企业导致立项项目统计为空），不渲染空表、不臆造事实。


- MCP 返回的嵌套 JSON 字符串（如金额 `{"coinType":"人民币","value":430000000.0}`、地址 `{"city":"杭州市",...}`）必须解析为可读文本（如"4.30 亿 人民币"、"浙江省杭州市"），绝不在报告正文、表格或指标中输出原始 JSON 字符串。
- 报告所有章节标题、指标卡标签必须用中文；`core_analysis.sections` 的 `title` 字段必须中文，不可显示英文 key（如 `holders`、`investments`）。
- 指标值必须可读化：金额格式为"X 亿/万 + 币种"，地址拼接省市区，比率显示百分号。详见 `references/report-output.md` 的「数据格式约束」。

## MCP 服务入口

- 上游 MCP 项目：`handaas-mcp-server/policy-mcp-server`（位于 `HANDAAS_MCP_SERVER_ROOT` 或本仓库同级目录）。
- Remote MCP：设置环境变量 `POLICY_MCP_URL`（streamable-http），可选 `POLICY_MCP_TOKEN`。
- 本地 MCP：设置 `HANDAAS_MCP_SERVER_ROOT` 指向 `handaas-mcp-server` 仓库根目录；该 server 自己的 `.env` 提供 `INTEGRATOR_ID` / `SECRET_ID` / `SECRET_KEY`。
- 首次真实查询前，运行 `scripts/mcp_client.py ping` 与 `scripts/mcp_client.py list-tools` 验证连通。

## 按需加载 references

- 不清楚该 MCP 有哪些工具、参数、返回字段、何时调用：`references/mcp-tools-reference.md`。
- 报告结构、章节、质量底线、渲染工作流：`references/report-output.md`。

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
