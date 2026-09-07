# #2 结构编辑实施与验收

日期：2026-09-07。审查固定点：`b44a28bbe8288dbbcf072c043e1ce8e3e9f796d0`。

## 实现与自动验证

changeset v2 在既有编辑事务内实现事件插入/删除、part-measure 替换、所有 part 同步的小节插入/删除/重编号、part 重命名/重排/添加/删除及显式碎片合并。结构报告携带语义去向和原始→输出对象映射，compare 与校准接口消费该映射。

验证结果：完整测试 **71 passed**；`uv run mypy src/score_cli` 通过（14 个源文件）；`git diff --check` 通过。18 个新增公共接口测试覆盖：

- 原始快照、事件/新建对象引用、part 与逻辑小节引用类型、过期或缺失引用、同批中途失败无输出。
- dry-run 与实际发布哈希一致，输入不变；逐项声明删除，旧值不符/映射冲突拒绝。
- XML 未变语义、namespace、注释/PI、direction/harmony/sound/barline/未知元素；partwise/timewise 新小节及嵌套引用。
- 所有 part 原子同步、`0`/`X1` 原子交换、重号碰撞、同名不同 ID 的 part 操作、instrument/MIDI 与分组校验。
- compare 结构映射及新增/删除/无法对齐，继承诊断基于原始对象身份映射，校准 verified 随结构改变失效。
- 真实 Audiveris 合并重放，输出前 8 小节的 21 个音高/时值与独立源谱转录表一致。

这些测试证明接口行为与明确风险，不构成完整 MusicXML XSD、任意乐谱正确性或所有 OMR 场景的证明。

## 真实碎片案例

材料为用户已有 Cantate Domino 的原始 Audiveris 5.11.0 输出。原文件及摘录 SHA-256、提取规则、源 PDF 路径与哈希保存在 [source.json](evidence/issue-2/source.json)。提供版 PDF 页脚允许自由分发、复制、演出或录制；原谱署名与版权信息保留。

摘录仅保留原 P1、P6 的文档顺序第 1–16 小节。原输入有 12 个 part；P6 第 1–8 小节包含第一高音声部，P1 相应位置为 OMR 占位休止，P1 从第 9 小节继续该声部。没有人工制造错音或将校准版充作原始 OMR。

变更：P6→P1，显式小节映射 1→1 … 8→8，voice/staff 1→1。移动来源小节全部内容，删除 P1 对应占位内容和 P6 第 9–16 小节的占位内容，消耗来源定义与 part wrapper。来源 part 的 **78 个 Audiveris 分隔注释也逐项列入 discard**。第 9–16 小节的 P1 音乐保留。

- [可重放输入](../tests/fixtures/structure/cantate-fragments.musicxml)
- [显式 changeset](../tests/fixtures/structure/cantate-merge.changes.json)
- [输出 MusicXML](evidence/issue-2/after.musicxml)
- [完整编辑报告及语义去向](evidence/issue-2/after.musicxml.edit.json)
- [compare 结果](evidence/issue-2/compare.json)、[结构映射](evidence/issue-2/mapping.json)
- [证据文件哈希](evidence/issue-2/files.json)

编辑前有 P1 m1 的 measure-overflow（占位休止 5 拍超过 3/4）和 P1 m9 的 incomplete-voice。合并后前者消失，后者作为既有警告保留，**没有新增诊断**。compare 对多对一 part-measure 合并明确列为 unaligned/inconclusive，不将旧占位休止和迁入音符按下标比较成大量错音。

## 图像与源谱核对

已实际查看 [源 PDF 第 1 页图像](evidence/issue-2/source-page-1.png)、[合并前裁剪](evidence/issue-2/before-render/001-page-1.png)、[合并后裁剪](evidence/issue-2/after-render/001-page-1.png)。前图显示两个 part：P1 占位休止、P6 的真实音符；后图为一个 P1，包含同一音乐内容。图像确实有谱线、音符和歌词，不是仅检查文件存在。

逐项对照源 PDF 第 1 页第 1 系统第一高音声部 m1–8，共 21 个事件，核对书写音高、起点/时值、歌词文本与分配；一致。已在回归中保存独立转录的音高/时值预期。渲染 manifest 保留实际坐标、参数和输入哈希，渲染页码与源 PDF 页码没有自动等同。

范围外：其他声部、第 9–16 小节的源谱一致性、方向文字、分组/版式一致性。P1 m9 已有缺拍问题仍存在；本次只完成真实结构合并案例，不宣称完整 Cantate Domino 已校准。

## 校准生命周期证据

- [合并前 8 条 scoped verified](evidence/issue-2/calibration-before.json)，目标为 P6 m1–8。
- [应用结构映射后](evidence/issue-2/calibration-mapped.json)，目标迁到 P1 m1–8，**verified=0、needs-review=8**。
- 重新对照源谱后建立 [新版 scoped verified](evidence/issue-2/calibration-after.json)；[状态快照](evidence/issue-2/calibration-status.json) 为 verified=8。

复核者明确记录为 Codex 可视源谱复核，不冒充真人签字。状态依赖实际文件及其哈希；迁移机器后应重新运行 calibration status，不能将快照当成永久有效证据。

## 重放

使用新的输出路径，不能覆盖已有产物：

```sh
uv sync
uv run score-cli edit tests/fixtures/structure/cantate-fragments.musicxml \
  --changes tests/fixtures/structure/cantate-merge.changes.json \
  --output tmp/cantate-merged.musicxml --dry-run
uv run score-cli edit tests/fixtures/structure/cantate-fragments.musicxml \
  --changes tests/fixtures/structure/cantate-merge.changes.json \
  --output tmp/cantate-merged.musicxml
uv run score-cli compare tests/fixtures/structure/cantate-fragments.musicxml \
  tmp/cantate-merged.musicxml --mapping docs/evidence/issue-2/mapping.json
uv run score-cli render tmp/cantate-merged.musicxml \
  --from-measure 1 --to-measure 8 --output tmp/cantate-render
```

## 双轴审查

Standards 首轮发现删除小节后仍可修改脱离文档的 direction，已修复 dynamics/wedge 的目标存活检查，并保护新方向的 offset-zero 锚点。复查无剩余发现。

Spec 首轮发现来源 part 小节外注释/PI/扩展没有逐项声明删除，已纳入删除匹配，显著 wrapper text/tail 拒绝。复查发现 part 集合引用可被误用为逻辑小节，已增加实际对象类型及完整集合检查。针对性复查无剩余发现。

契约支持边界见 [结构编辑文档](structural-editing.md)：合并采用显式整小节替换，不自动叠加重叠声部；上下文不兼容则拒绝；未知扩展语义、MXL 附件打包和完整源谱自动判断不在承诺范围。
