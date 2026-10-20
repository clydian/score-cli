# Issue 7：整小节休止 voice 错位

问题：[Issue #7](https://github.com/clydian/score-cli/issues/7)。0.2.19 在渲染副本中恢复源可证明的独立整小节休止 layer，未改 MusicXML 或 edit 输出。

## 红 → 绿

`tests/fixtures/render/multivoice-measure-rest.musicxml` 是自行构造的最小例：voice 2 力度 direction 在 voice 1 whole-measure rest 之前。Verovio 6.3 将休止导入 layer 2，首音图形后移；去掉 direction 的 voice 后原生导入正常。原生 MIDI 首音仍为 q0，不能称原播放时间错误。

`uv run pytest tests/test_render_measure_rest_voice.py -q`：旧 main 0.2.18 的首项回归失败（休止实际 layer 2，预期 1），修复后 9 项通过。回归检查实际 MEI layer、首音 SVG x 对齐、原生/修复 MIDI 值一致、chord/tie/slur/direction/tempo/lyric 内容保留、namespace/above-lyric 组合及不支持范围原路径。全测试 263 passed；`uv run mypy src/score_cli` 18 模块通过；`git diff --check` 通过。

## 真实 Sun v20

输入 SHA256 `1e2473a4a94520aac73683f70f05f3addedf60e5490baa7299735d87c78d89be`。本地证据根：

`/Users/siahuat0727/Documents/same-page/artifacts/transcription/2026-10-21/sun-round2-source-first/newppoe/diagnostic-upper-measure-rest/`

- `MAIN-0218-REGRESSION-RED.log`：实际旧实现失败。
- `SUN-V20-REST-REPAIR-PROOF.json`、`verify-sun-v20-rest-repair.py`：捕获 actual MEI 的修复前/后层，源文件字节未变；2781 个音乐/控制/歌词元素的全部属性（含身份、端点引用）与文本多重集合完全相同，仅休止移到 layer 1。两个 MEI 快照同目录保留。
- `sun-v20-fixed-system1.png`：实际查看，Alto lower 首音与 SATB q0 对齐；上 whole-rest 保留。报告仅 1 次 voice 分离、0 次 staff 迁移。

Verovio 的此处探测导入 q=1000ms，Alto 首三个音从 0/1500/2000ms 起；这是渲染输入时序检查，不当成生产播放器的 tempo 验收。既有跨 voice tie 的 self-endpoint 渲染警告未在本修复中解决。Sun 其余源音符、布局、完整歌词/弧与实际产品验收仍按原曲台账待办，不能由本图通过外推全曲质量。
