# 结构编辑契约 v2

Issue #2。继续使用 `edit_score` / `score-cli edit` 的读取、快照定位、全谱校验和双文件发布事务。changeset 的顶层仍只有 `schemaVersion`、`inputSha256`、`operations`；结构操作必须使用 `schemaVersion: "2"`。v1 的字段编辑继续支持。输出仍为新建的未压缩 XML，保留原 partwise/timewise 根结构。

## 定位、旧值与失败

每个操作都提供唯一 `id`、`type`、`target`、`expected`、`value`。所有已有对象在**原始快照**解析为 XML 对象身份；顺序执行时核对 `expected`。删除/替换后的旧对象不能被后续操作使用；不能用改后的编号重新查找原对象。

结构操作的 `expected` 是**有序 XML 字符串数组**，对应下表所列的整个目标子树。比较 namespace URI、属性、内容、注释、PI 和子元素顺序，忽略排版空白和 namespace 前缀拼写。可以用 lxml `ET.tostring(element, encoding="unicode", with_tail=False)` 取得原生子树。MXL 需先读取其中声明的 XML；附件边界沿用 v1。

非结构音符操作仍用 `partId + printedMeasure + staff + voice + offset + eventIndex`，所有字段除 eventIndex 外均为字符串；eventIndex 是小节内**全部 note**的 1-based 顺序。

- part-measure：`{"partId":"P1","printedMeasure":"X1"}`。
- 逻辑小节：`{"printedMeasure":"X1"}`，在每个 part 中必须恰好出现一次。
- part：`{"partId":"P1"}`，按 ID，不按名称。
- printed measure 精确匹配字符串，`0`、`X1`、前导零均保留。重号拒绝，区间和序列只按文档顺序。
- 任一定位、旧值、映射、语义保留、时间线或引用冲突，使整笔事务失败，不发布乐谱或报告。

## 操作

| type | target / expected | value 与必需策略 |
| --- | --- | --- |
| `insert-event` | 完整音符定位器 / `[锚点note XML]`；或 part-measure / `[原生measure或part XML]` | 完整 note XML；音符锚点 `position: before/after`，小节边缘 `position: start/end`；`timeline: shift-following`、`inherit: effective-context` |
| `delete-event` | 完整音符定位器 / `[note XML]` | `null`；`timeline: shift-following`；discard 声明该 note |
| `replace-measure` | part-measure / `[原生measure或part XML]` | 同类型、同属性的完整原生 wrapper XML；替换其全部子内容；discard 声明被替换掉的子树 |
| `insert-measure` | 逻辑小节 / partwise 按 part 文档顺序列出所有锚点 measure；timewise 只有外层 measure | partwise 为 `{P1: "<measure…>…", P2: "…"}`；timewise 为含全部 part 的完整 measure XML。`position: before/after`、`inherit: effective-context`；所有 part 必须显式提供同一新编号 |
| `delete-measure` | 同上 | `null`；discard 包含所有被删除原生 wrapper |
| `renumber-measures` | `{"printedMeasures":["0","X1"]}`；expected 先按给定标签顺序，再按 part 顺序列出 wrapper | `{"0":"X1","X1":"0"}`。必须完整覆盖所选旧编号，原子交换允许，与未选编号冲突则拒绝 |
| `rename-part` | part；expected 为 `[score-part定义, part内容…]`，timewise 内容按小节顺序 | `{"id":"S1","name":"Soprano","instruments":{"I1":"IS1"}}`；不改乐器 ID 时显式 `{}`。同步所有原生 part 与该 part 内 instrument/MIDI IDREF |
| `reorder-parts` | `{}` / `[完整part-list XML]` | 完整新 part-list XML。score-part 定义必须原样保留；可以显式编排 part-group。同步所有原生 part 顺序；删除旧分组元素需 discard |
| `add-part` | 锚点 part；expected 同 rename-part | `{"definition":"<score-part…>","content":["<part…>"]}`，partwise 一个完整 part，timewise 每个小节一个 part。`position: before/after` 决定定义、内容及分组位置；必须提供与现有序列一致的全部音乐 |
| `delete-part` | part；expected 同 rename-part | `null`；discard 列出完整定义和所有原生内容。分组不自动猜改，空分组/悬空引用须在同批显式修复 |
| `merge-part` | `{"sourcePartId":"P6","targetPartId":"P1"}`；expected 先来源定义及内容，再目标定义及内容 | 见下节 |

插入不会推测缺失音乐，也不自动造休止。XML 中 duration 使用有效 divisions 的原生单位，voice/staff 默认规则沿用 MusicXML。`start` 指首个 XML 子元素之前，可能早于本小节 attributes；若需在 attributes 后插入，使用实际 note 锚点或完整 replace-measure。最终校验会拒绝新增错误。

## 显式新对象引用

创建操作可提供 `bind: "新对象名"`。insert-event 绑定新 note；replace-measure 绑定 wrapper；insert-measure 绑定所有原生小节 wrapper 的集合；add-part 绑定定义及内容集合。后续 `target: {"ref":"新对象名"}` 按类型使用：音符字段/删除、替换 part-measure、逻辑小节插入/删除、part 增删改。

为新 XML 内的具体音符或 part-measure 提供 `bindings: {"new-note":"XML-ID"}`，使用新内容中显式、唯一的 XML `id` 定位。后续使用 `{"ref":"new-note"}`，不复用可漂移的数组下标。引用必须来自先前创建操作，不能前向、重名或引用已删除对象；嵌套引用的 ID 必须恰好出现一次。

## 删除清单与 dry-run

结构操作的 `discard` 是被删除子树的 XML 字符串数组，数量也必须一致。删除 note/measure/part 时声明完整被删对象；replace-measure 按直接子树匹配，原样保留的子树继续使用原 XML 对象，变化或移除的旧子树必须逐项声明。所有后代（歌词、连线、未知扩展等）都包含在子树声明中；不能只承认删音高却漏掉歌词。

编辑报告 v2 的 `structure.operations` 按操作列出 `preserved`、`moved`、`deleted`、`added` XML，包含 direction、barline、harmony、sound、未知元素、注释和 PI。merge 另列被消耗的 wrapper 及规则。定位/旧值/语义冲突通过带 operationId 的稳定诊断返回。未声明删除不产生输出。已有 direction/harmony 的相对时间偏移不能被意外移动；需要改变这些偏移时应在替换中显式删除旧对象并提供新对象。

## Audiveris 碎片合并

`merge-part.value` 必须完整声明：

```json
{
  "measures": {"1":"1", "2":"2"},
  "voices": {"1":"1"},
  "staves": {"1":"1"},
  "instruments": {},
  "destination": "replace",
  "sourceDisposition": "delete-part",
  "wrapperPolicy": "keep-target",
  "contextPolicy": "require-equal"
}
```

将指定来源 part-measure 的全部子元素迁移到目标 part-measure，保留目标 wrapper 属性。来源 part 消耗并删除，来源定义、未映射小节的所有子元素、目标被替换的所有子元素必须分别列入 discard。没有按名称猜声部，没有丢弃未映射内容的默认规则。

voice/staff 必须覆盖所有移动音符的有效值；方向等非 note 对象的显式 voice/staff 也必须覆盖。乐器目标必须在目标 part 声明。多对一的小节、voice/staff 或乐器映射会拒绝。迁移后逐音核对时间偏移、时值、继承上下文，必须与来源一致；不同 divisions/谱号/移调等需先用显式内容操作准备兼容上下文。当前合并是**整个 part-measure 替换**，不提供猜测性的重叠声部叠加；重叠冲突以明确 discard 或拒绝处理。

## compare 与校准

`compare_scores(..., mapping=...)` / `compare BEFORE AFTER --mapping mapping.json` 支持：

- `{"parts":{"P1":"S1"}}`：显式 part ID 映射，其余按精确 ID/printed measure 对齐。
- `{"measures":[{"before":{"partId":"P1","printedMeasure":"0"},"after":{"partId":"P1","printedMeasure":"X1"}}]}`：**完整**原始到新对象清单，必须覆盖两个版本全部 part-measure。新增 before=null，删除 after=null。编辑报告的 `structure.mapping` 可直接使用。
- 声部重命名、重排、编号变化在 `structureDifferences` 报告；新增/删除单列，不产生大量假错音。`relation: merged` 标识已声明的多对一合并；无法逐事件可靠对齐时单列 `unaligned`，状态 inconclusive，绝不宣称 equal。

`calibration_status(..., edit_report=报告)`，或 `calibration status AFTER --source-pdf SOURCE --record OLD --edit-report AFTER.edit.json`：校验报告输入哈希与清单旧版本一致、输出哈希与当前文件一致，再迁移目标，记录历史。所有受版本变化影响的非 unreviewed 记录保守转 needs-review。删除目标保留 `targetRemoved`，不能因新对象复用编号而再 verified，必须建立新记录。仅结构映射不等于源谱复核。

## 可重放真实案例

[Cantate Domino changeset](../tests/fixtures/structure/cantate-merge.changes.json) 是真实 Audiveris P6→P1、第 1–8 小节合并；[验收记录](issue-2-acceptance.md) 区分自动化、渲染内容与源谱证据。

```sh
uv run score-cli edit tests/fixtures/structure/cantate-fragments.musicxml \
  --changes tests/fixtures/structure/cantate-merge.changes.json \
  --output tmp/cantate-merged.musicxml --dry-run
uv run score-cli edit tests/fixtures/structure/cantate-fragments.musicxml \
  --changes tests/fixtures/structure/cantate-merge.changes.json \
  --output tmp/cantate-merged.musicxml
uv run score-cli render tmp/cantate-merged.musicxml \
  --from-measure 1 --to-measure 8 --output tmp/cantate-proof
```

引用语义依据 [MusicXML 4.0 score-instrument](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/score-instrument/)、[midi-instrument](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/midi-instrument/)、[part-list](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/part-list/)。校验仍不是完整 XSD 或未知扩展语义解释器；报告覆盖边界沿用现有 validate。
