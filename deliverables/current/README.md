# 当前参赛候选材料（2026-10-31）

已按本轮源码、自动验收与已知边界更新，不再使用10月25日二进制快照。实测记录见[收尾报告](../../docs/CLOSURE-2026-10-31.md)，[人工事项](../../docs/CLOSURE-MANUAL-2026-10-31.md)尚未关闭，候选包不等于正式提交。

| 材料 | 文件 | 自动检查与剩余 |
|---|---|---|
| 技术文档 | [Word](02-AegisBank-技术文档.docx) / [PDF](02-AegisBank-技术文档.pdf) | 同源Markdown；PDF渲染检查，Word实际分页待人工 |
| 安全自评 | [Word](04-AegisBank-安全自评报告.docx) / [PDF](04-AegisBank-安全自评报告.pdf) | 含权限分级与风险清单；同上 |
| 答辩 | [12页PPT](03-AegisBank-答辩材料.pptx) / [预览PDF](03-AegisBank-答辩材料.pdf) | PowerPoint渲染检查；实际汇报≤10分钟待彩排 |
| 作品简介 | [报名正文](../01-作品简介.md) | 184字符（含空格），≤200字；上传前人工审阅 |
| 视频 | [4分40秒分镜](../04-演示视频脚本.md) | 尚无成片，须人工录制并核对≤5分钟 |
| 源码及复现 | [部署](../06-部署说明.md) / [测试](../07-测试与复现.md) | 独立库及干净源码复现证据见收尾报告；源码zip在本机交付目录 |

技术/安全Word由python-docx生成；对应PDF因本机Word导出无响应，使用ReportLab从同一Markdown生成，不声称是Word版式渲染。PPT由python-pptx生成并经本机PowerPoint导出PDF/图片。见[文档缩略图](../../docs/fixtures/closure-2026-10-31/documents-contact-sheet.jpg)和[PPT缩略图](../../docs/fixtures/closure-2026-10-31/ppt-contact-sheet.jpg)。

真实模型对照按用户选择暂缓，人工金标仍pending；所有金融结果来自Mock Bank Core，固定MFA、角色请求头和进程内沙箱仅用于演示。生产身份、真实MFA/IM、OS隔离、U3/U5均不因此完成。
