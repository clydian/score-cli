# MusicXML 校准契约 v1

本文件定义 `edit` / `validate` / `compare` / 范围 `render` / `calibration` 的独立 JSON 契约。所有根对象 `schemaVersion` 为字符串 `"1"`。现有 outline / inspect / 单小节 render 的默认输出保持不变。

## 快速闭环

```sh
uv run score-cli outline score.musicxml
uv run score-cli inspect score.musicxml --measure X1
uv run score-cli validate score.musicxml
uv run score-cli edit score.musicxml --changes changes.json --output fixed.musicxml --dry-run
uv run score-cli edit score.musicxml --changes changes.json --output fixed.musicxml
uv run score-cli compare score.musicxml fixed.musicxml
uv run score-cli render fixed.musicxml --from-measure X1 --to-measure 0 --context 1 --output proof/new-range
```

范围输出是新目录，内含 `manifest.json` 与有序 PNG。普通 `render --measure X1 --output X1.png` 仍输出单张 PNG。`--measure X1 --context 2` 可选邻近小节。端点按文档顺序，绝不把 printed number 转成整数。

## 快照、顺序和文件事务

changeset 的顶层只允许 `schemaVersion`、`inputSha256`、`operations`。输入哈希是原始文件字节 SHA-256（MXL 为容器字节）。operations 是非空有序数组，操作 ID 非空且唯一。每个操作必须显式给出 `expected` 和 `value`；不存在用 null 表示，不省略。

note target 精确包含：

```json
{"partId":"P1","printedMeasure":"X1","staff":"1","voice":"1","offset":"0","eventIndex":1}
```

字符串必须精确匹配；offset 是以四分音符为单位的约分有理数字符串（例如 `"3/2"`）；默认 voice/staff 为 `"1"`。eventIndex 从 1 开始，按该 part/小节中**全部直接 note 元素**的文档顺序计数，包含休止、和弦音、倚音，不是声部内编号。与 inspect 的 `order` 一致。重复 printed number 拒绝，不能猜 occurrence。

事务先在原始快照解析全部目标并保存 XML 节点引用，然后逐个应用。后续操作 expected 对照执行前的当前状态；不能根据修改后的 offset/voice/index 重新寻找目标。结构插入/删除、part/小节变更均不支持。

只写新 `.xml` / `.musicxml`，拒绝与输入同路径或已有输出/报告。默认报告位置为 `<output>.edit.json`。内存中修改并完成全谱校验后，先在同文件系统写临时文件、fsync，再用不覆盖已有文件的 hard link 发布报告，最后发布乐谱。捕获到失败时撤销本次已发布链接；输入始终不写。进程被强杀/掉电不能保证两个路径同时可见：报告先发布，乐谱最后发布，是完成标记；读者必须同时验证报告与乐谱 SHA-256。不把孤立报告视为成功。重试使用新路径或人工核实后清理孤立报告。范围渲染的完成标记则是最后发布的 manifest。

`--dry-run` 执行同样的解析、预检、操作和校验，返回同类报告（status=dry-run），不创建目录、乐谱或报告文件。

## 操作表

共有字段 `id`、`type`、`expected`、`value`。note 操作另有 `target`。

| type | expected / value | 策略与边界 |
|---|---|---|
| pitch | `{step,alter,octave,accidental}` | step A-G；alter 有理数字符串，首期只编辑整数半音；octave 0-9 整数；accidental 必须显式 null 或 sharp/flat/natural/double-sharp/flat-flat，并与 alter 一致。null 删除显示临时记号，交给排版器根据调号决定，不改变 alter。已有延音链拒绝，先显式删除两端再编辑、重建。|
| lyric | null 或 `{text,syllabic}` | 另有 `selector:{number:"1"}` 或 name，或同时指定。唯一定位；null→对象为新增，对象→对象为更新，对象→null为删除。syllabic 为 null/single/begin/middle/end。包含 elision/extend/humming/laughing 的复杂歌词拒绝，未知未编辑子元素保留。|
| duration | `{duration:"1",type:"quarter",dots:0,timeModification:null}` | 另需 `timeline:"shift-following"`。duration 用四分音符有理数；必须能在该音符有效 divisions 下表示为整数。type/dots/timeModification 同时校验并写入；比例为 `{actualNotes:3,normalNotes:2}`。非和弦、非倚音才推进游标。保留 backup/forward 的原始值；若由此造成别的 voice 空洞/重叠、方向元素移动或小节越界，拒绝。可用一个事务内的相邻时值补偿保持后续位置。倚音时值编辑拒绝；显式 normal-type/normal-dot 的连音编辑拒绝。|
| voice / staff | 精确字符串 | 不改变音符文档次序或 duration，最终重算时间线与配对；staff 为正整数字符串。|
| kind | `{kind:"note",pitch:{…}}` 或 `{kind:"rest",pitch:null}` | 不移动后续事件。拒绝和弦锚点/和弦音、unpitched 和 tied 音符转换。rest→note 的 pitch accidental 先设 null，可再用 pitch 操作设置。|
| tie / slur | boolean | 另有 `start`、`end` 两个 note locator 和 `number:"1"`。两端必须按时间顺序，v1 在同 part/voice 中编辑。true 新增、false 删除。expected 可为共同 boolean，或 `{start:true,end:false}` 显式修复缺失端点。tie 新增时要求音高相同且时间连续；删除可用于修复错误音高的现有链。tie 同时维护演奏 tie 和记谱 tied；slur 只维护记谱。编号 1–16，不重编号其他符号。|
| dynamics | null 或 `"p"` 等 | target 是独立 direction locator。只编辑一个简单力度符号；保留 direction 中的 words、sound 等内容。不把记谱力度推断为播放 MIDI velocity。若删除最后一个符号会连带丢失 sound/未知内容/ID，拒绝。|
| wedge | value 为 crescendo/diminuendo/null；expected 为 boolean | 另有 start/end direction locator 与 number。跨小节支持，要求同 part/staff/voice、两端有序。只改变记谱 wedge，不添加自动播放渐变。|

可人工检查并直接重放的 changeset 见 `tests/fixtures/calibration/*.changes.json`。

Direction locator 包含 `partId, printedMeasure, staff, voice, offset, directionIndex`。正 directionIndex 从 1 开始计数该小节全部直接 direction 元素，voice 缺省是空字符串。`directionIndex:0, offset:"0"` 表示新建小节起点方向，不占用 note 编号；同一虚拟 locator 在事务内共享节点。不支持在任意中间时刻新建方向，已有方向可在其明确 offset 上编辑。所有方向最终位置必须保持不变，不能被时值操作隐式移动。

## 校验、诊断和比较

Diagnostic 字段：`code`（稳定 kebab-case）、`severity`（error/warning/info/inconclusive）、`location`、`reason`、`operationId`。校验位置可含 measureOrdinal 来区分损坏输入中的重号。错误操作的异常通过 `ScoreError.diagnostic` 暴露；CLI 输出 schemaVersion/status=failed/diagnostics。validate 包含 coverage.checked/unchecked 和 inputSha256；不是完整 MusicXML XSD 校验。

检查完整乐谱的 part/小节序列、定位、divisions、正 duration、backup/forward 负游标和 divisions 边界、和弦锚点、倚音、显示时值一致性、按 voice 的区间覆盖、跨小节 tie/tied/slur/wedge。和弦不重复计时，staff 不拆分同一个 voice。弱起、implicit、non-controlling、无拍号不要求每个 voice 填满；普通不完整 voice 仅报告警告，无法确认语义的情形明确 inconclusive。

edit report 包含工具版本、inputSha256/outputSha256、完整有序 changeset、diagnosticsBefore/After、comparison、diagnosticMatching。诊断匹配使用 code+severity+完整 location+reason 的多重集合精确匹配，新增项标记 new-or-unmatched。新错误/警告均阻止发布；无法匹配不是“已证明新增”，会保守阻止。既有问题允许定点修复。此策略可能拒绝本来安全但使旧诊断位置变化的编辑，应缩小事务或先修复已有问题。

compare 仅在相同 part/小节结构下按全部 note ordinal 对齐；voice ID 改变或 note 数量变化不猜映射，报告 unaligned 与 added/removed **候选**。无唯一身份时不能把候选当成已证明新增/删除。报告 notationDifferences（字段、前后值）、soundingDifferences、两侧 validation、覆盖范围与两个输入哈希。相同数量下 ordinal 是显式比较策略，不是跨编辑稳定身份的承诺。

发声音高是以 C4=60 为基准的半音数：pitch + transpose.chromatic + 12×transpose.octave-change。clef-octave-change 和 octave-shift 不再重复加八度。unpitched、instrument/play、transpose.double 等无法确定的表示返回 inconclusive。不是完整演奏引擎，repeat、sound 跳转、微分音调律等不推断。

## XML 保留与支持矩阵

使用 lxml 的完整 ElementTree，关闭实体展开、网络和 DTD 加载，保留未知命名空间元素、属性、相对顺序、文档外/内注释、PI、CDATA 和 DOCTYPE。输出统一 UTF-8 XML 声明；不承诺空白、属性顺序、前缀拼写、原编码和字节一致。对未触及节点不从 inspect JSON 重建。未知扩展与核心同名元素不会作为音符处理。

| 输入/结构 | 支持与证明 |
|---|---|
| partwise / timewise / 默认命名空间 | 三者都原结构写回，公共 edit 测试检查输出音高与保留内容 |
| MXL | 恰好一个 container rootfile 和 score；输出解压 XML。多 rootfile、附件、额外容器资源、image/link 或实体引用拒绝，不能静默丢资源 |
| chord / grace / tuplet | 定位、计时、校验支持；编辑边界见操作表 |
| pickup / incomplete / cross-staff voice | Fraction 游标、按 voice 区间，不简单逐 note 求和 |
| transpose / octave clef / octave-shift | 来自规范的固定预期值测试，区分显示与发声 |
| 未知扩展 | 完整保留，语义含义未解释；不能宣称已校验其音乐正确性 |
| 结构重排、任意新方向时间、复杂歌词、MXL 再打包 | unsupported，后续扩展 |

规范依据：[transpose](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/transpose/)、[octave-change](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/octave-change/)、[octave-shift](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/octave-shift/)、[clef-octave-change](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/clef-octave-change/)、[chord](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/chord/)、[lxml parsing](https://lxml.de/parsing.html)。

## 范围 manifest

字段包括 inputSha256/toolVersion/rendererVersion/renderParameters/requested/selectedMeasures/contextClipped/renderedScorePageCount/images。完整输入先交给 Verovio 排版；每个相交系统输出一张包含连续目标小节的裁剪图，跨页按文档顺序。每张图有 path/sha256/measures/renderedScorePage/crop/coordinateUnit/definitionToSvgScale/rasterZoom。crop 是加入页边距平移与 padding 后的内部 SVG viewBox，单位 verovio-definition-units；乘 definitionToSvgScale 再乘 rasterZoom 得到 PNG 尺寸（取整）。sourcePdfPage 始终 null，人工校准记录另存源 PDF 映射。不能把渲染页码当作原谱页码。

## 校准记录生命周期

```sh
uv run score-cli calibration create fixed.musicxml --source-pdf source.pdf --targets targets.json --output review-0.json
uv run score-cli calibration update fixed.musicxml --source-pdf source.pdf --record review-0.json --update review-update.json --output review-1.json
uv run score-cli calibration status fixed.musicxml --source-pdf source.pdf --record review-1.json
```

Targets 是 `[{"id":"P1-m2-lyrics","partId":"P1","printedMeasure":"2","checks":["lyric syllabification only"]}]`。Update 字段为 recordId/state/reviewer/conclusion/sourceLocation/evidence/editReports；sourceLocation 包含正整数 page/system 和字符串 measures 数组；evidence/editReports 为本地文件路径数组。API 自动读取哈希和 UTC 时间。

状态流：unreviewed→needs-fix→needs-review→verified；无问题可 unreviewed→verified；发现问题或版本变化时回到 needs-review/needs-fix。verified 必须有实际存在的证据、源 PDF 位置、具名复核者、结论、检查范围、当前 XML/PDF 哈希和时间。工具只记录复核声明与文件证据，不自动认定图中内容正确。

查询状态时总是核对当前文件：乐谱或 PDF 任意字节变化保守使全部旧结论失效；证据丢失/变化也失效。更新一个记录前先使其他旧版本记录失效，再重绑定容器版本。JSON 静态文件的旧 state 不是当前状态，消费方必须调用 status。输出 counts 和 missingEvidence；局部 verified 不等于整小节或整谱认证。记录保留状态历史、证据文件哈希、修改报告引用。输出文件始终新建。
