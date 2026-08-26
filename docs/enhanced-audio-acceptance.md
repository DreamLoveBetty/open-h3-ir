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

~~一处偏离待维护者裁决~~ **已补齐（验收后修订）**：规格的 LEGACY 要求产生 WARN `A0-audio-analysis-degraded`。初版实现只有 log warning；现已在 `AssetCard.audio_degraded` 打印记、由 `_audio_provenance` 输出 `{degraded: true, reason, projection_role}` 记录——文档读者据此可区分"降级编译"与"分析成功"，且标记落在 provenance 而非 validator finding，不进修复循环（worker 宕机不是 writer 能修的事）。刻意不标记"配置关闭"与"无字节可分析"两种从未尝试分析的情形，使 degraded 不与 disabled 混读。

## §29 Acceptance Criteria

**Audio v1（9 项）**：全部 ✅。Worker 独立运行（`services/audio_worker/`，自身 42 测试）；SenseVoice ASR / FSMN-VAD / CAM++ / DSP 在 `app.py` 接线（VAD→SenseVoice→CAM++ 单次调用链）；AudioObservation 可序列化（磁盘 round-trip 测试）；观测缓存正常；legacy 正常；非音频无回归。
~~*限制：真实权重下的端到端验证是部署环境事项，测试全部走 fake/pure-function 路径。*~~ **已实测（bring-up，见文末附录）**。

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

规格定位为非硬性目标。Cache hit 路径为一次本地 HTTP round trip + JSON 读取（observer 注释记录压在 100ms 预算内）——bring-up 实测：**观测缓存 + fallback 缓存全命中时端到端 47 ms**（CPU, arm64, 2026-08-26），在预算内。冷路径数字见文末附录。

## 汇总

- 规格 §28 九项测试要求：9/9 ✅
- §29 完成条件：v1 9/9、v2 8/8、fallback 7/7、v3 3/4（AV alignment 为规格自定延后项）
- 已知偏离一处，有记录且经维护者确认符合原生设计：**§19 不合成 `<Audio N>` 标签**（遵守 runtime 契约）；~~§25 A0 形态~~ 已补齐为 provenance 降级记录
- ~~已知限制：真实模型权重下未做端到端验证；性能数字未实测~~ **均已实测**，见下

## 附录：真实权重 bring-up（2026-08-26，CPU / arm64 Mac / 96GB）

两个服务真实拉起并端到端跑通：`services/audio_worker`（:50000，dsp/speech/clap 三层 `/health` 全 ok）与新增的 `services/omni_fallback`（:8001，Qwen2.5-Omni-3B Thinker 半边，单文件 FastAPI shim）。模型权重全部落项目内 `models/`（gitignore 已排除）。

实测数字：

| 路径 | 实测 |
|---|---|
| 语音观测冷启动（SenseVoice+VAD+CAM++ 首次加载并分析） | ~14.5 s |
| Omni fallback 热态一次调用（路由触发→返回→严格解析→merge） | ~41 s |
| 观测缓存 + fallback 缓存全命中端到端 | ~47 ms |

Bring-up 抓到并修复四处 fake 测试覆盖不到的真实漂移（commit `9ac9a91`）：ModelScope 上 404 的 CAM++ 默认 id；FunASR 1.4 `infer`→`generate` 改名且 SenseVoice 的 `generate` 不收 `vad_segments`（改为按 VAD 段切临时 wav 逐段喂入，CAM++ 的 1×192 embedding 展平）；transformers 5.x 将 CLAP processor 的 `audios=` 改名 `audio=`；3B fallback 模型在只有 "Return JSON only" 时必发明键名被严格解析器整包拒绝——`FALLBACK_USER_PROMPT` 现带 §11 骨架与严格类型说明，协议版本升至 `audio-fallback-2`，并新增守卫测试钉住骨架键集 == `PROTOCOL_KEYS`（已按仓库纪律证伪：红→恢复→绿）。

实测发现的可控行为（设计内，记录在案）：

- **CLAP 对纯语音的软误报**：真实语音样本上 CLAP 报出 "glass breaking"/"drums" 类事件，置信度 0.34，低于编译器侧 `event_confidence_threshold=0.55`，不会进入卡片——阈值分层按设计生效。
- **DSP 无 librosa 时倍频误读**：自相关 fallback 把 120 BPM 测试音读成 240 BPM（octave error，置信度 0.5 自标低）；装 librosa 后走精确路径，属已知降级档。
- **SenseVoice ITN 粘连**：英文逆文本归一化把 "at six" 合成 "at6"——转写文本原样进卡，不改写用户/模型文字的原则同样适用于 ASR 输出，记为模型行为而非管线缺陷。
