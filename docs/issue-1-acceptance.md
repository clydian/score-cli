# #1 实施与验收记录

日期：2026-09-07。审查固定点：`1fbca77d8e34430c60ecc4e6d448aae1f726a31d`。

## 真实材料与授权

`tests/fixtures/calibration/samples.json` 记录三个最小首系统样本的原文件路径/哈希、提取方式和样本哈希。Os Justi 与 Cantate Domino 的提供版 PDF 页脚分别明确允许分发和复制，署名与版本信息保留。它们是用户已有的校准材料；没有把人工注入错误冒充 OMR 的实际错误。

源 PDF 哈希：

- Os Justi：`9d2b534ca4c185029490f527790bf86659081ba1da0c6956adbeffe6c66cb451`，第 1 页第 1 系统 m1–7。
- Cantate Domino：`859abc75c5f45e22ec60b3548de320bb641300390c5d67a3bb9a2334e6891a30`，第 1 页第 1 系统 m1–8。

Cantate Domino 最小样本来自既有声乐校准版本，作多 part 范围渲染/内容基线；Reh 钢琴缩编不在此 XML，未声明整页所有谱表一致。原始 OMR 的 part 结构修复仍属于后续结构票。

## 已运行的真实闭环

1. Os Justi Audiveris 原始完整 XML：首系统 P3 的 18 个音高降一个八度。原文件未提供 tenor 八度谱号，故这是**音高字段的局部修复**；谱号/显示上下文仍有缺口，未把该版本标为源谱一致。
2. Os Justi 已有完整校准 XML：第 2 小节四个声部的 8 个歌词元素 `jus-ti` 改回提供 PDF 的 `ju-sti`。实际运行 dry-run → edit → compare → 全谱布局范围 render。完整乐谱产物在 `tmp/issue-1/final-full-score/`。
3. 对修改后的完整第二份 XML，与源 PDF 第 1 页第 1 系统逐项核对 **Soprano m1–7 的音高/休止、起点/时值、歌词内容与分配**，共 17 个事件。可视图确实包含目标内容；不是只检查 PNG 存在。m2 修改后 `ju-sti` 与 PDF 一致。
4. [校准记录](evidence/issue-1/calibration.json) 保存 7 个 scoped verified，复核者注明 Codex 可视源谱复核，不冒充真人签字。力度、连线、其他声部、版面一致性没有被这 7 条记录覆盖。[状态快照](evidence/issue-1/status.json) 为当时结果；当前消费必须调用 calibration status 重新检查版本与文件。

可检查的证据：[原谱第一页](evidence/issue-1/source-page-1.png)、[修改前](evidence/issue-1/before.png)、[修改后](evidence/issue-1/after.png)、[编辑报告](evidence/issue-1/edit-report.json)、[范围坐标](evidence/issue-1/render-manifest.json)、[证据哈希](evidence/issue-1/files.json)。原 manifest 的 `001-page-1.png` 在此证据目录另名存为 `after.png`，文件哈希相同。裁剪 padding 可显示相邻小节的边缘片段，不把片段计入 selectedMeasures。

## 可重放命令

小样本不依赖本机外部完整 XML，使用新输出路径：

```sh
uv sync
uv run score-cli edit tests/fixtures/calibration/os-justi-lyrics.musicxml \
  --changes tests/fixtures/calibration/os-justi-lyrics.changes.json \
  --output tmp/replay-lyrics.musicxml --dry-run
uv run score-cli edit tests/fixtures/calibration/os-justi-lyrics.musicxml \
  --changes tests/fixtures/calibration/os-justi-lyrics.changes.json \
  --output tmp/replay-lyrics.musicxml
uv run score-cli compare tests/fixtures/calibration/os-justi-lyrics.musicxml tmp/replay-lyrics.musicxml
uv run score-cli render tmp/replay-lyrics.musicxml --from-measure 1 --to-measure 7 --output tmp/replay-proof
uv run score-cli edit tests/fixtures/calibration/os-justi-omr.musicxml \
  --changes tests/fixtures/calibration/os-justi-omr.changes.json \
  --output tmp/replay-pitch.musicxml
```

完整乐谱重放：使用 `tmp/issue-1/final-full-score/*.changes.json`，它们绑定 samples.json 中的原始完整输入哈希，不能拿小样本 changeset 直接编辑全谱。完整乐谱布局与最小样本布局可能分页不同，这也是 manifest 不推断源 PDF 页码的原因。

## 自动证明与边界

公共接口回归保护快照、旧值、重号、连续操作失败、新文件冲突、XML 保留（partwise/timewise/namespace/MXL）、未知扩展、歌词生命周期、音高与临时记号一致性、时值联动、voice/staff、note/rest、两端配对、跨小节 wedge、按 voice 时间线、移调八度、防止方向意外移动、跨页 PNG 像素内容和证据失效。最终验证：53 项测试通过；`uv run mypy src/score_cli` 通过，启用 check_untyped_defs；`git diff --check` 通过。

实现能力与源谱验收分开：validate 不等于完整 XSD 或音乐正确性证明；已存在的诊断会保留。两个真实输入还有其他原有问题，局部修复不构成整谱完成。新增方向目前仅支持小节起点，复杂歌词、部分连音表示、结构编辑、播放和 MXL 附件写回仍拒绝。所有原子操作已有接口，但并非每一种都取得独立真实修复案例；不能据此关闭 #1 的全部真实验收要求。


## 双轴审查

Standards：没有发现 AGENTS.md 或仓库文档违规。时间游标重复实现的维护风险已通过共享 timeline() 解决，独立校验器保留交叉检查。

Spec：两轮审查发现的代码缺陷已修复并加回归：alter 的合法数字写回、tied 编号、方向符号删除时保留无关内容、方向 staff 引用、删除错误延音以进入修复路径。复查未留下代码缺陷；上文列出的每类独立真实案例验收缺口仍保留，未关闭 Issue #1。
