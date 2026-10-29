# Verovio 6.3 的斜向 direction bracket 位置风险

MusicXML 的 [bracket](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/bracket/)
允许分别指定端点的 `default-y`，以所属谱表顶线为原点，并用 `relative-y`
作相对调整。图形线的显示位置不等于滑音等播放解释。

## 真实复现

`tests/fixtures/render/direction-bracket.musicxml` 是无版权的两声部、三谱表
合成例：第二声部第二谱表，在第 2、3 拍后分别放置同编号 bracket 的起止点，
两端高度为 15 和 -47.5 tenths。Verovio `6.3.0-425dd7b` 的 MEI 保留
`tstamp="3"`、`tstamp2="0m+4"`，但没有所属谱表或端点高度；原始整页 SVG
只有空的 `bracketSpan` 组。直接导入与 CLI 正式加载路径结果相同，排除裁图
以及 rest/lyric 适配造成的丢失。第一声部单谱表对照则实际画出水平线，即使
两端明确给了不同高度。普通横线仍可以正确绘制。

[Verovio 6.3 官方导入代码](https://github.com/rism-digital/verovio/blob/version-6.3.0/src/iomusxml.cpp#L2135-L2167)
的 bracket 分支未传递谱表和端点高度，符合以上实际结果。此处提供风险提示，
没有修复 Verovio，也没有修改 XML、MEI 或 SVG 来模拟原谱。

## Warning 契约与范围

`prepare_render_input` 仅对同声部、同谱表、同编号的明确 start/stop 配对发出
`verovio-sloped-direction-bracket-risk`，且两端必须都有可解析的 `default-y`，
加上各自 `relative-y` 后高度不同。记录包含声部、谱表、编号以及起止印刷小节
和序号。单小节、系统和范围渲染共享此报告；CLI 写到 stderr，范围 manifest
保留 `renderInputCompatibility.warnings`。与既有兼容 warning 一样，扫描覆盖
完整输入，不只包含当前裁图。

配对遵守 MusicXML 的
[start-stop-continue](https://www.w3.org/2021/06/musicxml40/musicxml-reference/data-types/start-stop-continue/)
和 [number-level](https://www.w3.org/2021/06/musicxml40/musicxml-reference/data-types/number-level/)：
stop 可以在文档中先出现，编号复用按文档序处理。两次同型端点造成的歧义不作
推断；不会将一个声部或谱表的端点配到另一个上。只识别与根元素同 namespace
的 MusicXML 结构，忽略外部 namespace 的同名扩展；谱表和编号按正整数身份
比较，合法空白及前导零不会拆散同一对端点。

普通横线、重复结尾的 `ending`、未配对或缺少明确高度的线，以及仅中间
`continue` 点偏离的线，不在本次检查范围。无 warning 不能证明渲染正确。
遇到提示时，应保留源 XML，对照原谱及独立引擎；显示和 MIDI 分开验证，不能
为了让预览出线而添加原谱没有支持的 `glissando` 或改变音符。
