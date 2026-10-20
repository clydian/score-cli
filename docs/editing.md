# MusicXML 校准契约 v1

本文件定义 `edit` / `validate` / `compare` / 范围 `render` / `calibration` 的独立 JSON 契约。本文描述的 v1 根对象 `schemaVersion` 为字符串 `"1"`；结构 changeset/edit report 的 v2 见 [结构编辑契约](structural-editing.md)。现有 outline / inspect / 单小节 render 的默认输出保持不变。

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

范围输出是新目录，内含 `manifest.json` 与有序 PNG。 自 0.2.11，裁图纳入与所选小节横向相交的圆滑线、延音线、渐强渐弱楔形和结尾括号的纵向边界；跨格连线不会把未选小节横向拉进图中。自 0.2.12，栅格化前移除 Verovio 生成的 SVG 文字容器换行缩进，避免保留空白的多行 words 在 resvg 中整段消失；实际文字、行内空格、坐标和源 MusicXML 保持不变。仍需目视最终图，裁图完整不等于源记号或排版已经验收。普通 `render --measure X1 --output X1.png` 仍输出单张 PNG。`--measure X1 --context 2` 可选邻近小节。端点按文档顺序，绝不把 printed number 转成整数。

低音歌词与符头／加线相碰时，可增加仅渲染的上方留白：

```sh
uv run score-cli render score.musicxml --from-measure 0 --to-measure 74 --breaks auto --lyric-word-space 2.5 --lyric-top-min-margin 4 --output proof/clear-lyrics
```

`--lyric-top-min-margin`（API `lyric_top_min_margin`）接受 0–8 的有限数值，单位为 Verovio 的 MEI units，默认 2 保持既有布局。单小节和范围渲染均支持，范围 manifest 的 `renderParameters.lyricTopMinMargin` 记录实际值。它调整整个渲染的歌词最小上方间距，不修改源 XML，也不改变产品里的 alphaTab 排版；更大间距可能增加系统高度和页数，应复看整曲。MusicXML 歌词定位属性不一定被各排版器执行，勿为局部显示问题改音高、歌词或删除连线。

## 快照、顺序和文件事务

changeset 必需顶层字段为 `schemaVersion`、`inputSha256`、`operations`；v2 另可提供下文的 `acknowledgedWarnings`。输入哈希是原始文件字节 SHA-256（MXL 为容器字节）。operations 是非空有序数组，操作 ID 非空且唯一。每个操作必须显式给出 `expected` 和 `value`；不存在用 null 表示，不省略。

note target 精确包含：

```json
{"partId":"P1","printedMeasure":"X1","staff":"1","voice":"1","offset":"0","eventIndex":1}
```

字符串必须精确匹配；offset 是以四分音符为单位的约分有理数字符串（例如 `"3/2"`）；默认 voice/staff 为 `"1"`。eventIndex 从 1 开始，按该 part/小节中**全部直接 note 元素**的文档顺序计数，包含休止、和弦音、倚音，不是声部内编号。与 inspect 的 `order` 一致。重复 printed number 拒绝，不能猜 occurrence。

事务先在原始快照解析全部目标并保存 XML 节点引用，然后逐个应用。后续操作 expected 对照执行前的当前状态；不能根据修改后的 offset/voice/index 重新寻找目标。v1 不接受结构操作；这些操作由 v2 契约支持。

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

自 0.2.9，`validate` 对显式 `natural`、`sharp`、`flat`、`double-sharp`、`flat-flat` 与 `pitch/alter` 不一致的音符报告 `accidental-pitch-mismatch` warning，定位到具体事件。省略 alter 按 0 处理；提醒性或括号升降号也应与所写音高一致。未知／微分音升降号不由此规则解释。校验不会自动改谱：回看原 PDF，确认应改显示记号还是音高；仅有听音一致不能证明显示正确。结构编辑引入的新 warning 仍受既有逐项确认机制约束。

`validate` 另对 note 中位于首个 `lyric` 之后的同 MusicXML 命名空间 `notations` 报 `notations-after-lyric` error，定位到具体事件。`coverage.checked` 的 `notations-before-lyric-note-order` 仅表示这一条元素顺序约束；外来扩展命名空间的同名元素不参与判断。校验不会自动重排元素，新引入的此类 error 也不能用 warning acknowledgment 豁免。回看源谱确认符号内容后，以 hash-bound 编辑将 `notations` 放在全部 `lyric` 之前。其他 note 子元素顺序、choice / multiplicity 等仍需完整 XSD 校验，`full-musicxml-schema` 继续列为 unchecked。

edit report 包含工具版本、inputSha256/outputSha256、完整有序 changeset、diagnosticsBefore/After、comparison、diagnosticMatching。诊断匹配使用 code+severity+完整 location+reason 的多重集合精确匹配，新增项标记 new-or-unmatched。新错误/警告默认均阻止发布；无法匹配不是“已证明新增”，会保守阻止。既有问题允许定点修复。对已经逐项核原谱的合法部分 voice，可以使用下面的 v2 精确 warning 确认；它不删除诊断、不降低 severity，也不豁免任何新 error。

compare 在已对齐的 part/小节内部按全部 note ordinal 对齐；显式结构映射、新增/删除见 v2 文档。voice ID 改变或 note 数量变化不猜映射，报告 unaligned 与 added/removed **候选**。无唯一身份时不能把候选当成已证明新增/删除。报告 notationDifferences（字段、前后值）、soundingDifferences、两侧 validation、覆盖范围与两个输入哈希。相同数量下 ordinal 是显式比较策略，不是跨编辑稳定身份的承诺。

发声音高是以 C4=60 为基准的半音数：pitch + transpose.chromatic + 12×transpose.octave-change。clef-octave-change 和 octave-shift 不再重复加八度。unpitched、instrument/play、transpose.double 等无法确定的表示返回 inconclusive。不是完整演奏引擎，repeat、sound 跳转、微分音调律等不推断。

### 跨声部延音线校验

`tie` / `tied` 先按实际乐谱时间处理，并优先保留同 part、同 voice、同所写音高的配对。没有同 voice 配对时，仅当同 part 中剩余的起点和终点各自唯一、所写音高相同、起点时值恰好到达终点时，才允许跨 voice（或 staff）相连。`tied` 的 number 仍分别匹配；播放 `tie` 没有 number，多个同音候选仍可能无法消歧。同一时点的全部终点先集中检查，不能因 XML 中哪个 voice 先出现就先消耗某条延音线。歧义报告 `ambiguous-tie` / `ambiguous-tied` error；错误不能用 warning acknowledgment 豁免。

本规则不改动源 XML、不新增播放解释，也不扩大 v1 `tie` 编辑的同 voice locator 限制。结构 changeset v2 可在保留真实音高、时值和端点后恢复共符干和弦。所写音高拼写仍须一致；unpitched 的显示线位、休止或缺失音高不能用于跨 voice 推断；等音异名、反复边界的单音符视觉 tie 等既有未解释范围没有在本次扩展。含零时值 tie 端点（例如倚音）的 part 保留原先按 voice、文档顺序配对的路径，暂不推断该 part 的跨 voice tie。

依据：[W3C tie](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/tie/) 区分演奏与记谱；[tied](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/tied/) 说明同音端点和复杂情形的 number，没有规定两端 voice 必须相等；[voice](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/voice/) 用于区分 part 内线性事件流。因此“voice 改变必定断线”不是这些元素定义的必要约束，这是对规范的解释。[MuseScore 原生导入实现](https://github.com/musescore/MuseScore/blob/4509c9072c583f7ab0c805ded2ab88f29e0ec0e5/src/importexport/musicxml/internal/import/importmusicxmlpass2.cpp#L2349-L2371) 也有跨 voice 的同音、相邻时间端点补接。这里引用其源码行为，未声称实际运行 MuseScore 验收；Score CLI 对多候选采用更保守的歧义错误。

## 合法部分声部的精确 warning 确认

从 0.2.6 起，changeset v2 可选顶层字段 `acknowledgedWarnings`。v1 及没有此字段的 v2 保持原先的保守阻断行为。普通小节中的共享音符、后半拍进入的 divisi、只写一段的独立 voice 可能产生 `incomplete-voice` / `voice-gap` warning。工具没有原谱依据，不能自动认定合法，也不能为消除 warning 补休止或重复共享音符。

先运行原事务，包含 `--dry-run` 也一样：

```sh
uv run score-cli edit source.musicxml --changes changes.json --output reviewed.musicxml --dry-run 2> failure.json
```

若唯一阻断是新的或无法匹配的 warning，仍退出 1、`status: failed`，不会落地候选谱或成功 edit report。失败 diagnostic 的 `warningReview` 给出完整候选序列化后的 `outputSha256`，以及所有新 warning 的 `{code,severity,location,reason}`；它只是复核材料，不代表应用或批准。若有新 error，先报告 error，不提供可用于确认它的 warning 列表。

逐项对照原谱、目标 XML 与具体 voice / 时刻，再手工在原 changeset 增加确认：

```json
{
  "schemaVersion": "2",
  "inputSha256": "<原输入的64位小写SHA-256>",
  "operations": ["<保持已审查的原操作对象>"],
  "acknowledgedWarnings": {
    "outputSha256": "<warningReview给出的64位小写SHA-256>",
    "entries": [
      {
        "diagnostic": {
          "code": "incomplete-voice",
          "severity": "warning",
          "location": {"partId":"P5","printedMeasure":"25","measureOrdinal":25,"voice":"1"},
          "reason": "Voice ends at 3, before meter 4; may be intentional incomplete notation."
        },
        "rationale": "原谱第4页第1系统：上声部只写前三拍，末拍共享下声部同音的一次attack；已核实无需补休止。"
      }
    ]
  }
}
```

示例中的尖括号内容须替换，`operations` 必须仍为完整原操作对象。不要自动把 `warningReview` 全部复制为确认；尚有未核准的 warning 时继续处理音乐内容，不能将工具回归测试当成音乐验收。最后一小节跨声部延长或自由延音也需要单独判断。

契约要求：

- 输入 `inputSha256` 与完整输出 `outputSha256` 同时匹配。即使 warning 相同，改音高、布局或任一目标 XML 字节造成输出变化，都使旧确认失效。
- 每条 entry 必须有非空 `rationale`；diagnostic 恰好四个字段，完整 location（含 ordinal、voice、offset 等实际字段）与 reason 逐项精确匹配，不支持通配、仅 code 放行、整类 warning 放行。
- 按多重集合逐次消耗。少确认一项、增加一个相同 warning、改位置/理由都仍阻断；多余、重复或仅对应 existing warning 的确认以 `unused-warning-acknowledgment` 拒绝。
- severity 只能为 `warning`。error、未知 entry 字段、空确认、无效 hash 都拒绝；方向移动、旧值、discard、其他事务保护仍照常生效。
- 正式运行或 dry-run 成功时，report `schemaVersion: "2"` 保留 `warningAcknowledgments`、全部 `diagnosticsAfter`（warning 及其 `new-or-unmatched` origin 仍在），不伪称已经修复或完成原谱验收。独立 `validate` 仍会报告这些 warning。

重新运行同一 `edit` 命令可 dry-run / 正式发布到新文件；确认后也要核渲染和实际播放。原稿、原始诊断、确认理由和成功 edit report 一起保留作为可重放证据。

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
| 任意新方向时间、复杂歌词、MXL 再打包 | unsupported，后续扩展 |

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


结构操作请参见 [changeset v2 结构编辑契约](structural-editing.md)；本文的 v1 字段编辑契约继续支持。

### 自由拍方向的渲染兼容

Verovio 6.3 在非首 part 再次读取 `senza-misura` 时，会把不存在的 `beat-type` 当成零，导致渐强渐弱、文字等方向的时点塌为小节起点。单小节和范围渲染现在只在**渲染副本**中省略可证明冗余的声明：相同 ordinal 的首 part 有内容完全相同的无编号自由拍，且两 part 的前置简单计量声明完全一致。首 part 的原自由拍／文字保留，不补拍号，不改变任何音符、方向 offset、歌词、源文件或 `edit` 输出。

范围 manifest 的 `renderInputCompatibility.omittedRedundantTimeDeclarations` 列出适配的位置，`unchecked` 列出不满足条件的范围；单小节 Python API 的 `RenderResult.render_input_compatibility` 提供同样信息。独立／编号谱表拍号、混合拍号、不同前置分母或无法证明共享作用域的声明保持原样，**不代表显示已校验**。该兼容只恢复方向时间，不保证自由图形、重复次数、精确演奏长度或文字避让；仍应对照原谱查看最终图。

### 上方歌词的渲染兼容

Verovio 6.3 的 MusicXML 导入不保留 `lyric placement="above"`；其原生
MEI `verse place="above"` 可正确布局。CLI 在临时渲染副本给无 ID 的目标音符分配
唯一 ID，已有唯一 ID 保留；按音符 ID 与唯一正整数歌词行号定位导入后的 verse，
补 `place="above"` 后重新布局。`renderInputCompatibility.explicitAboveLyrics`
记录 adapter、映射 verse 元素数及 render-copy-only 状态（延长线终点也计入）。

此过程不改源文件、歌词文本、音符或播放数据；没有显式 above 的输入仍走原路径。
冲突 id/xml:id、重复 ID、非数字或重复行号、丢失的导入目标会报错，不按歌词文字猜声部。
这不是任意 `default-y` / `relative-y` 定位支持，也不替代原谱视觉复核或产品播放器验收。

## 多谱表休止的渲染归属（0.2.18）

Verovio 6.3 在某些多声部导入顺序下，将明确 `staff=2` 的全小节休止放入第一谱表。渲染现在先按源音符唯一身份检查归属：若该 MEI layer 的全部源事件都属于同一谱表，才在渲染副本中将完整 layer 归回该谱表。保持音符身份、时间、声部和歌词；源 MusicXML 与 edit 输出不变。单小节和范围图均适用，manifest 的 `renderInputCompatibility.explicitRestStaff` 记录 `relocatedLayers`。

混合跨谱表声部、未映射事件、目标已占用 layer 和变动的谱表数量不猜测重组，保留原导入并在 `unchecked` 列明范围；这不是这些情形的排版验收。隐藏休止仍是隐藏的 space，不当成丢失的可见休止。身份冲突或导入丢失身份直接报错，避免将修复应用到另一个音。此修复不处理同一谱表内部上下声部的休止纵向安排；例如 Sun 第23小节仍需独立复核。
