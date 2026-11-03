# 福建数字经济政策观察

- 用户需求：检索福建省数字经济相关政策与公开公示，供区域业务团队跟踪支持方向。
- 决策用途：识别区域扶持重点和公开项目动态。
- 本轮结果：**本轮检查通过**
- 实际工具调用：1；失败 0
- 章节覆盖率：56%（不代表证据质量）

## 预期业务检查（不自动宣称通过）

- 省级地区过滤被准确记录
- 公示公开与申报指南不混用
- 政策时间和发布机构可追溯
- 结论不外推到福建省外

## 本轮自动检查发现


## 使用局限

- 公开公示可能晚于实际项目进度
- 地区字段取决于上游归类

## 证据与复现

- [审计结果](result.json)
- [工具调用、结果形态与响应摘要哈希](calls.json)
- [JSON](report.json) / [HTML](report.html) / [Markdown](report.md)

```bash
python3 policy-skill/scripts/compose_report.py --keyword '数字经济' --pn-type '公示公开' --address '[["福建省"]]' --page-size 10 --output policy-skill/output/05-local-digital-economy/report.json --report-output policy-skill/output/05-local-digital-economy/report.html
```

## 逐场景业务复核

当前真实产物逐项复核通过；结论限于本次上游公开样本与报告声明口径。

- **pass** 省级地区过滤被准确记录：已证明“省级地区过滤被准确记录”。 实际调用=[{"tool":"policy_bigdata_policy_search","status":"data","row_count":10,"reported_total":96,"arguments":{"matchKeyword":"数字经济","pnType":"公示公开","pageIndex":1,"pageSize":10,"address":"[[\"福建省\"]]"}}] subject={"keyword":"数字经济","matchKeyword":"数字经济","enterprise":"","enterprise_input":"","enterprise_resolved":false,"enterprise_resolve_reason":"未提供企业主体","enterprise_blocked_reason":"","pn_type":"公示公开","agency":"","address":"[[\"福建省\"]]","policy_id":""} 口径={"match_target":"政策关键词“数字经济”","match_type":"政策检索按政策关键词匹配（pnType=公示公开）","data_scope":"政策检索明细","products":["政策检索"],"limit":"数据来自政策公开数据库；少量字段可能存在更新延迟。"} 实际记录样本={"type_dist":[{"政策类型":"公示公开","数量":"4"}],"keyword_freq":[{"主题词":"资金","出现次数":"10"},{"主题词":"产业","出现次数":"6"}],"monthly_trend":[{"月份":"2025-10","政策数量":"2"},{"月份":"2025-11","政策数量":"2"}],"search_records":[{"政策标题":"2026年漳州市第五批福建省高层次人才拟认定人选名单公示","发布机构":"漳州市人力资源和社会保障局","地区":"福建省、漳州市","政策类型":"公示公开","发布日期":"2026-09-14","相关性":"正文线索","命中位置":"正文","重复标记":"-"},{"政策标题":"2026年漳州市第四批福建省高层次人才拟认定人选名单公示","发布机构":"漳州市人力资源和社会保障局","地区":"福建省、漳州市","政策类型":"公示公开","发布日期":"2026-09-10","相关性":"正文线索","命中位置":"正文","重复标记":"-"}]} 可见章节=[{"title":"立项项目统计","note":null},{"title":"项目层级分布","note":"按申报层级（国家/省/市/区）统计获批项目占比"},{"title":"项目归口分布","note":"按主管机构统计获批项目数量"},{"title":"获批项目趋势","note":"按年度统计获批项目数量"},{"title":"政策类型分布","note":"仅按标题确认且去重的当前页样本统计政策类型"},{"title":"政策主题词频","note":"仅对标题确认且去重样本的正文(pnText)做子主题词统计"},{"title":"政策发布时间趋势","note":"仅按标题确认且去重样本的发布月份统计"},{"title":"检索相关性校验","note":"保留上游 total；主题聚合仅使用标题确认且按标题+机构+日期去重的当前页样本，正文命中仅作线索"},{"title":"政策检索明细","note":"上游命中 96 条；当前页 10 条，标题确认相关去重样本 4 条"}]
- **pass** 公示公开与申报指南不混用：已证明“公示公开与申报指南不混用”。 当前事实={"technical_status":"passed","successful_data_calls":1,"calls":[{"tool":"policy_bigdata_policy_search","status":"data","row_count":10,"reported_total":96,"arguments":{"matchKeyword":"数字经济","pnType":"公示公开","pageIndex":1,"pageSize":10,"address":"[[\"福建省\"]]"}}],"quality":{"total_sections":9,"populated_sections":5,"empty_sections":4,"coverage_pct":56},"sections":[{"title":"立项项目统计","note":null},{"title":"项目层级分布","note":"按申报层级（国家/省/市/区）统计获批项目占比"},{"title":"项目归口分布","note":"按主管机构统计获批项目数量"},{"title":"获批项目趋势","note":"按年度统计获批项目数量"},{"title":"政策类型分布","note":"仅按标题确认且去重的当前页样本统计政策类型"},{"title":"政策主题词频","note":"仅对标题确认且去重样本的正文(pnText)做子主题词统计"},{"title":"政策发布时间趋势","note":"仅按标题确认且去重样本的发布月份统计"},{"title":"检索相关性校验","note":"保留上游 tot…
- **pass** 政策时间和发布机构可追溯：已证明“政策时间和发布机构可追溯”。 实际记录样本={"type_dist":[{"政策类型":"公示公开","数量":"4"}],"keyword_freq":[{"主题词":"资金","出现次数":"10"},{"主题词":"产业","出现次数":"6"}],"monthly_trend":[{"月份":"2025-10","政策数量":"2"},{"月份":"2025-11","政策数量":"2"}],"search_records":[{"政策标题":"2026年漳州市第五批福建省高层次人才拟认定人选名单公示","发布机构":"漳州市人力资源和社会保障局","地区":"福建省、漳州市","政策类型":"公示公开","发布日期":"2026-09-14","相关性":"正文线索","命中位置":"正文","重复标记":"-"},{"政策标题":"2026年漳州市第四批福建省高层次人才拟认定人选名单公示","发布机构":"漳州市人力资源和社会保障局","地区":"福建省、漳州市","政策类型":"公示公开","发布日期":"2026-09-10","相关性":"正文线索","命中位置":"正文","重复标记":"-"}]} 可见章节=[{"title":"立项项目统计","note":null},{"title":"项目层级分布","note":"按申报层级（国家/省/市/区）统计获批项目占比"},{"title":"项目归口分布","note":"按主管机构统计获批项目数量"},{"title":"获批项目趋势","note":"按年度统计获批项目数量"},{"title":"政策类型分布","note":"仅按标题确认且去重的当前页样本统计政策类型"},{"title":"政策主题词频","note":"仅对标题确认且去重样本的正文(pnText)做子主题词统计"},{"title":"政策发布时间趋势","note":"仅按标题确认且去重样本的发布月份统计"},{"title":"检索相关性校验","note":"保留上游 total；主题聚合仅使用标题确认且按标题+机构+日期去重的当前页样本，正文命中仅作线索"},{"title":"政策检索明细","note":"上游命中 96 条；当前页 10 条，标题确认相关去重样本 4 条"}]
- **pass** 结论不外推到福建省外：已证明“结论不外推到福建省外”。 当前事实={"technical_status":"passed","successful_data_calls":1,"calls":[{"tool":"policy_bigdata_policy_search","status":"data","row_count":10,"reported_total":96,"arguments":{"matchKeyword":"数字经济","pnType":"公示公开","pageIndex":1,"pageSize":10,"address":"[[\"福建省\"]]"}}],"quality":{"total_sections":9,"populated_sections":5,"empty_sections":4,"coverage_pct":56},"sections":[{"title":"立项项目统计","note":null},{"title":"项目层级分布","note":"按申报层级（国家/省/市/区）统计获批项目占比"},{"title":"项目归口分布","note":"按主管机构统计获批项目数量"},{"title":"获批项目趋势","note":"按年度统计获批项目数量"},{"title":"政策类型分布","note":"仅按标题确认且去重的当前页样本统计政策类型"},{"title":"政策主题词频","note":"仅对标题确认且去重样本的正文(pnText)做子主题词统计"},{"title":"政策发布时间趋势","note":"仅按标题确认且去重样本的发布月份统计"},{"title":"检索相关性校验","note":"保留上游 tot…

## 离线浏览器检查

[Ego Lite 离线图表、页面溢出和脚本检查](browser-check.json)