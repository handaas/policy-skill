# policy-skill：已验收示例

本目录只展示 **4 个完全通过的真实正向场景**（最低要求4例）。

每例均为真实、非空、非缓存调用；技术检查、独立业务检查和离线浏览器检查全部通过。不把空数据、报错处理或仅生成页面计作通过。历史验收记录保留在本地 test-records/；本目录的 HTML/Markdown 由原 JSON 重渲染，不代表重新查询或重新验收。

| 场景 | 真实使用需求 | 报告 |
|---|---|---|
| [江门专精特新赋能行动精确检索](09-jiangmen-specialized-action/README.md) | 检索江门市工业和信息化局发布的专精特新企业赋能行动申报指南，核对标题、机构、政策类型和发布日期，供申报团队定位原文；不要判断企业资格或审批概率。 | [HTML](09-jiangmen-specialized-action/report.html) / [MD](09-jiangmen-specialized-action/report.md) / [JSON](09-jiangmen-specialized-action/report.json) |
| [企业获批项目与政策联动](04-enterprise-approved-projects/README.md) | 结合华为技术有限公司的历史获批项目，检索科技创新相关政策并分析项目层级。 | [HTML](04-enterprise-approved-projects/report.html) / [MD](04-enterprise-approved-projects/report.md) / [JSON](04-enterprise-approved-projects/report.json) |
| [福建数字经济政策观察](05-local-digital-economy/README.md) | 检索福建省数字经济相关政策与公开公示，供区域业务团队跟踪支持方向。 | [HTML](05-local-digital-economy/report.html) / [MD](05-local-digital-economy/report.md) / [JSON](05-local-digital-economy/report.json) |
| [乡村振兴政策主题研究](07-rural-revitalization/README.md) | 检索乡村振兴相关政策，帮助农业项目团队了解支持方向和发布机构分布。 | [HTML](07-rural-revitalization/report.html) / [MD](07-rural-revitalization/report.md) / [JSON](07-rural-revitalization/report.json) |

- [逐例验收结果](results.json) · [业务复核](review.json) · [证据摘要](evidence-index.json)
- 完整测试记录仅存于本地 test-records/live-replaced-20261027/（仅本地审计用，不随本目录发布），不属于可展示示例。
- 当前数据与结论限于原查询时点及公开样本；覆盖率不代表准确率或低风险。
