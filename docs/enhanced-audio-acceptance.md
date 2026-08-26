# Enhanced Audio Context-IR — 整体验收报告

日期：2026-08-26 ｜ 分支：`feature/enhanced-audio` ｜ HEAD：`5e983ef`
对照：`docs/OpenH3-IR_Enhanced_Audio_Context-IR_Development_Spec.md` §28 / §29 / §33 / §36A

## 门禁状态（终验实测）

| 门禁 | 结果 |
|---|---|
| `h3ir controls` | **23/23**，无 failing |
| 主套件 `pytest -q` | **1109 passed, 1 skipped**（Phase A 前基线 1092，净增 +17 即 Phase E） |
| Worker 套件 `pytest services/audio_worker/tests` | **42 passed** |

## §28 测试要求 — 逐项

规格点名的 9 个测试文件全部存在：

| 规格要求 | 文件 | 状态 |
|---|---|---|
| §28 清单 | `test_audio_observation.py` | ✅ |
| §28 清单 | `test_audio_cache.py` | ✅ §28.1 原案：同字节三角色（BGM/MUSIC_STYLE/BEAT_REFERENCE）一次 worker 调用、一条缓存、三张不同卡片 |
| §28 清单 | `test_audio_projection.py` | ✅ §28.2 措辞逐字钉扎：BGM 含 "background music" 且不得含 "newly generated"；MUSIC_STYLE 含 "newly generated score"；BEAT_REFERENCE 含 "rhythm" |
| §28 清单 | `test_audio_fallback_router.py` | ✅ §28.3 原案：music_style + 空 genres/instruments 触发 fallback；同观测挂 bgm 不触发 |
| §28 清单 | `test_audio_merge.py` | ✅ §28.4 原案数值：Omni 140 vs DSP 128.1@0.94 → 最终 128.1，Omni 不覆盖 |
| §28 清单 | `test_audio_timeline.py` | ✅ §28.5 原案数值：cut 3.67 + beat 3.80 → snap 到 3.80；最近 beat 4.10 → 不动 |
| §28 清单 | `test_audio_findings.py` | ✅ A22 在文本侧；A23/A24 在投影侧 |
| §28 清单 | `test_audio_degraded_mode.py` | ✅ LEGACY 路径：不可达 worker →  typed metadata + 响亮 warning；required=1 → 拒绝 |
| §28 清单 | `test_video_audio_pairing.py` | ✅ 17 个测试，5 项植入缺陷证伪（合成标签 / 缓存不剥离 / 网格不进 snap / worker 被喂 mp4 / 源事件冒充目标 sync sound） |

规格未点名但新增的相关文件：`test_audio_card_is_not_cached.py`、`test_audio_claims.py`、`test_audio_config.py`、`test_audio_provenance.py`、`test_audio_worker_client.py`、`test_reference_audio_words.py`。

§28.6 no-audio regression：音频默认关闭（`test_the_default_is_off_and_local`）；既有 1092 测试在新增模块后全绿；`h3ir controls` 23/23 不变——非音频 prompt 行为无变化。

## §23 Validator 规则 — 落点映射

| 规格规则 | 实现 | 说明 |
|---|---|---|
| A20 role/projection 一致性 | **不新增规则**，由既有 R22（marker 侧）+ R27（prose 侧）覆盖 | `test_audio_findings.py` 有等价性钉扎测试；头部注释记录这是决策而非遗漏 |
| A21 beat reference 不得 claim 信号复用 | 同上，R27-reference-audio-claimed-as-copied | 同上 |
| A22 timbre 不得仅由 transcript 推断 | `validate.py` A22-voice-from-transcript-only | ✅ |
| A23 event 时间越界 | `projector.py` WARN，越界事件丢弃不修复 | ✅ |
| A24 beat 单调性 | `projector.py` WARN，乱序网格整体停用 | ✅ |
| A25 source traceability | `compile.py` `_audio_provenance` → `IRDocument.provenance["audio"]` | ✅ 含 Phase E 视频内嵌音轨条目 |
| A26 fallback 不得覆盖确定性时序 | `merge.py` A26，**WARN 而非规格的 ERROR** | 有记录的理由：协议解析器已拒绝载荷，覆盖不可能 ship，ERROR 会进修复循环指令模型重写一件它无法影响的事 |
| A27 note 冲突可见 | 结构性保证：冲突检查与 A9-audio-note-discrepancy 是同一代码路径 | ✅ 编号改用 A9 有注释说明（A1 已被占用） |

## §24 Provenance

`IRDocument.provenance["audio"]` 按规格形状落地：observation_hash、audio_worker、sensevoice/clap 模型 id、fallback_used/fallback_model、projection_role；无音频时整个键省略。视频内嵌音轨以视频 label 入册，标记 `(embedded soundtrack)`。

## §25 降级策略

三态均支持：FULL（worker + 可选 fallback）/ PARTIAL（fallback 不可用 → 无补充 + finding，不失败）/ LEGACY（worker 不可达 → Role+note+transcript+duration 老路径）。

**一处偏离待维护者裁决**：规格的 LEGACY 要求产生 WARN `A0-audio-analysis-degraded`；实现用的是 log warning 而非 validator Finding。理由符合仓库规则 12（Finding 的 ERROR/WARN 会进修复循环发回模型，而 worker 宕机不是模型能修的事），但规格字面是 Finding 形态——如要严格对齐需补一个不进修复循环的文档级 finding。

## §29 Acceptance Criteria

**Audio v1（9 项）**：全部 ✅。Worker 独立运行（`services/audio_worker/`，自身 42 测试）；SenseVoice ASR / FSMN-VAD / CAM++ / DSP 在 `app.py` 接线（VAD→SenseVoice→CAM++ 单次调用链）；AudioObservation 可序列化（磁盘 round-trip 测试）；观测缓存正常；legacy 正常；非音频无回归。
*限制：真实权重下的端到端验证是部署环境事项，测试全部走 fake/pure-function 路径。*

**Audio v2（8 项）**：全部 ✅。CLAP 事件/声音语义（`b6b4ff8`）；role-aware projection；manifest characterisation 用投影；beat reference 影响 timeline；SFX 映射到 shot；ambient/sync 分流；新 validator 规则（上表）；caller/analyser discrepancy Finding（A9）。

**Full fallback（7 项）**：全部 ✅。Omni endpoint 配置；规则评分路由器；严格 JSON 协议（A28 拒绝偏离）；分层 merge；确定性事实不被覆盖（A26）；provenance 记录 fallback；fallback 不可用不破坏主路径。

**v3（4 项）**：

| 项 | 状态 |
|---|---|
| reference video 自动提取 soundtrack | ✅ ffmpeg/ffprobe → 16kHz 单声道 wav，按内容哈希缓存 |
| paired audio observation | ✅ 观测经同一 observer 链，存视频卡独立字段；**有意收窄**：不合成 `<Audio N>` manifest 条目（ref-en.txt 2.5：runtime 只为 wired soundtrack 发标签） |
| AV event alignment | ⏸ **规格自定延后**（§20 标注"后续增强"） |
| video soundtrack timing 可进入 H3 planning | ✅ beat grid 以视频 label 进 timeline_constraints，X20 吸附生效 |

## §33 Commit 顺序

规格建议 11 个 commit；实际 10 个（worker 侧的 SenseVoice/VAD/CAM++、DSP、观测缓存三件合入 `ae674db`/`7c750c3`）。顺序与规格一致：contracts → worker 协议 → worker 服务 → projector → timeline → findings → fallback → CLAP → provenance → video soundtrack。

## §36A Upstream Compatibility

- current branch：`feature/enhanced-audio`
- upstream remote detected：yes（`ruashots/open-h3-ir`）
- upstream/main compared：yes
- commits behind upstream/main：**0**
- files overlapping upstream recent changes：无（upstream 无新提交）
- merge conflicts encountered：无
- compatibility decisions made：全部改动集中在 `h3ir/audio/`、`services/audio_worker/` 新增目录，及对 `analyse.py`/`plan.py`/`prose.py`/`compile.py`/`models.py`/`validate.py` 的加法式修改；未改 upstream 语义区域（§36A.7）

## §30 性能目标

规格定位为非硬性目标。Cache hit 路径为一次本地 HTTP round trip + JSON 读取（observer 注释记录压在 100ms 预算内）；真实硬件上的延迟数字未测量，属部署期验证项。

## 汇总

- 规格 §28 九项测试要求：9/9 ✅
- §29 完成条件：v1 9/9、v2 8/8、fallback 7/7、v3 3/4（AV alignment 为规格自定延后项）
- 已知偏离两处，均有记录：**§19 不合成 `<Audio N>` 标签**（遵守 runtime 契约）；**§25 A0 用 log warning 而非 Finding**（待裁决）
- 已知限制：真实模型权重下未做端到端验证；性能数字未实测
