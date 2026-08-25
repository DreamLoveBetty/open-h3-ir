# OpenH3-IR Enhanced Audio Context-IR 开发规格

**目标仓库：** `DreamLoveBetty/open-h3-ir`  
**基线分支：** `main`  
**目标：** 在现有 OpenH3-IR 基础上新增真正的本地音频理解能力，使 Audio Reference 不再只依赖用户 `note` / 外部 transcript，而能从音频字节中提取语音、说话人、情绪、音频事件、音乐、节拍、声学特征及时间关系，并把这些事实安全地投影到 MiniMax H3 Context-IR。  
**主 Context Planner：** Qwen3.8-27B（沿用 OpenAI-compatible endpoint / LM Studio 等）  
**音频主分析链：** SenseVoiceSmall + FSMN-VAD + CAM++ + DSP + CLAP  
**完整语义 fallback：** Qwen2.5-Omni-3B，仅在规则判定主分析链不足时调用  
**兼容要求：** 音频增强关闭或 Audio Worker 不可用时，现有非音频功能和现有 IR 行为不得被破坏。

---

## 1. 背景与当前代码状态

当前 OpenH3-IR 已经具有比较成熟的：

- Asset intake
- Image / sampled-video AssetCard
- Mode inference
- Manifest
- Role / retention
- deterministic Plan
- beat sheet / shot planning
- deterministic render
- validator / repair
- CLI / HTTP / ComfyUI 集成

当前音频路径则是刻意的“deaf mode”：

1. `h3ir/analyse.py::analyse_audio()` 不读取音频文件内容，不调用音频模型。
2. 音频事实来自：
   - `Role`
   - 用户 `note`
   - duration
   - 外部传入的 transcript
3. `AssetCard` 已预留：
   - `transcript`
   - `language`
   - `timbre`
   - `music`
   - `characterisation`
4. 当前 AudioCard 不缓存，因为这些字段不是由音频 bytes 决定，而是由 request 参数决定。
5. `build_manifest()` 对音频的 `ManifestEntry.characterisation` 当前主要来自 `AssetRef.note`。
6. `render_subject_definitions()` 最终又从 `ManifestEntry.characterisation` 生成 `<Audio N>` 定义。
7. `plan.py` 已经支持：
   - `VOICE_TIMBRE`
   - `BGM`
   - `MUSIC_STYLE`
   - `BEAT_REFERENCE`
   - `SFX`
   - `audio reuse`
   - `audio reference`
   - `split_sound(sync vs ambient)`

因此本次开发不应推翻现有 Planner / Renderer / Validator，而应重点增强：

> `Audio bytes -> AudioObservation -> Role-aware Audio Projection -> Manifest / Plan / Timeline -> Context-IR`

---

# 2. 核心设计原则

## 2.1 Observation 和 Intent 必须分离

音频分析器只回答：

> 音频里客观存在什么？

不要让分析器决定：

> 用户想怎么使用这段音频？

例如同一个音乐文件可以分别作为：

- `bgm`
- `music_style`
- `beat_reference`

音频 Observation 应当相同，但最终 Context-IR 投影不同。

---

## 2.2 音频事实优先结构化，不优先自由文本

禁止把核心链路设计成：

```text
audio.wav
→ Audio LLM
→ 一大段自然语言描述
→ Qwen3.8 再解释
```

优先设计为：

```text
audio.wav
→ 多个专门分析器
→ AudioObservation JSON
→ Role-aware deterministic projection
→ Qwen3.8 只负责高层规划 / 语言组织
```

---

## 2.3 确定性事实不交给 LLM 猜

以下内容优先由程序 / 专门模型获得：

- duration
- sample rate
- channel count
- speech segment timestamps
- transcript
- language
- speaker IDs
- BPM
- beat timestamps
- onset timestamps
- silence
- loudness
- peak timing
- 音频事件的时间窗
- confidence

Qwen3.8 / Qwen2.5-Omni 不得覆盖高置信度确定性结果。

---

## 2.4 Qwen2.5-Omni-3B 是 fallback，不是默认主路径

默认：

```text
SenseVoice + VAD + CAM++ + DSP + CLAP
```

只有当规则系统判断信息不足，才调用：

```text
Qwen2.5-Omni-3B
```

目的：

- 降低显存占用
- 降低延迟
- 避免所有音频都进行昂贵自由语义推理
- 保持结果可解释

---

## 2.5 保留 OpenH3-IR 的“structure is compiled, prose is generated”

以下内容继续由代码决定：

- `<Audio N>` label
- wiring
- role
- retention marker
- task type
- shot timestamps
- 是否 copy/reference
- beat snapping
- sound event placement
- validator 规则

模型不得擅自改变这些结构性事实。

---

# 3. 总体架构

```text
                              User Request
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
                Visual Assets                Audio Assets
                    │                           │
                    ▼                           ▼
             Existing Analyse             Audio Observer
                    │                           │
                    │          ┌────────────────┼────────────────┐
                    │          │                │                │
                    │          ▼                ▼                ▼
                    │     SenseVoice        DSP Layer          CLAP
                    │       + VAD            ffmpeg/           AED /
                    │       + CAM++          librosa           semantics
                    │          │                │                │
                    │          └────────────────┼────────────────┘
                    │                           ▼
                    │                   AudioObservation
                    │                           │
                    │                           ▼
                    │                   Confidence Router
                    │                           │
                    │             ┌─────────────┴────────────┐
                    │             │                          │
                    │          sufficient                 insufficient
                    │             │                          │
                    │             │                          ▼
                    │             │                Qwen2.5-Omni-3B
                    │             │                    fallback
                    │             │                          │
                    │             └─────────────┬────────────┘
                    │                           ▼
                    │                Merged AudioObservation
                    │                           │
                    │                           ▼
                    │                Role-aware Projector
                    │                           │
                    └──────────────┬────────────┘
                                   ▼
                          AssetCard / Context Facts
                                   │
                                   ▼
                          Existing Mode / Planner
                                   │
                            Audio-aware Timeline
                                   │
                                   ▼
                              Qwen3.8-27B
                         Director / prose planning
                                   │
                                   ▼
                         Existing Render / Validate
                                   │
                                   ▼
                             H3 Context-IR
```

---

# 4. 模型与组件职责

## 4.1 Qwen3.8-27B

职责：

- 用户 Intent 理解
- Image / Video 视觉理解（沿用当前主 VLM）
- Reference reasoning
- Director
- shot semantics
- Context-IR prose
- 音频结构化事实的高层整合

不负责：

- 原始音频 ASR
- BPM 检测
- VAD
- diarization
- 精确 event timestamp

---

## 4.2 SenseVoiceSmall

默认常驻 Audio Worker。

负责：

- ASR
- language
- coarse emotion
- coarse audio event detection

输出必须保留 confidence（若底层接口提供）。

---

## 4.3 FSMN-VAD

负责：

- speech / non-speech segmentation
- 长音频切分
- 减少 SenseVoice 对整段音频的无效计算

---

## 4.4 CAM++

负责：

- speaker embedding
- speaker clustering / diarization
- `SPK_0`, `SPK_1` 等稳定 speaker ID

不要把 CAM++ 的 speaker ID 当做人类身份。

---

## 4.5 DSP Layer

优先使用 `ffmpeg/ffprobe` + `librosa`，必要时可选 Essentia。

负责：

- duration
- sample rate
- channel layout
- RMS / loudness
- silence regions
- onset
- tempo BPM
- beat timestamps
- pitch statistics
- dynamic range
- peak positions

DSP 是事实层，不生成叙事性语言。

---

## 4.6 CLAP

负责补充：

- 环境声
- SFX 类别
- music / non-music
- 大类乐器 / 音乐语义
- 音频 texture 的 zero-shot 分类

不要只对整段音频做一次分类。

至少支持：

```text
sliding window
+
onset-driven windows
```

输出：

- label
- start
- end
- confidence

---

## 4.7 Qwen2.5-Omni-3B fallback

用途：

- 复杂开放式 Audio Caption
- 主分析链无法解释的混合声场
- 音乐类型 / 配器信息不足
- 声音叙事关系
- 多声源复杂重叠
- 用户明确要求“详细分析声音”
- 低 confidence 结果修补

禁止：

- 默认每段音频都调用
- 覆盖已有高置信度 transcript / beat / timestamp
- 自行改变用户指定 Role
- 生成不存在于输入中的精确时间戳

---

# 5. 新增核心数据模型

建议在 `h3ir/models.py` 增加以下 dataclass。

```python
@dataclass
class TimedSpeech:
    start_s: float
    end_s: float
    text: str
    language: str = ""
    speaker_id: str = ""
    emotion: str = ""
    confidence: float | None = None


@dataclass
class AudioEvent:
    start_s: float
    end_s: float
    label: str
    confidence: float | None = None
    source: str = ""


@dataclass
class AudioVoiceProfile:
    speaker_count: int = 0
    pitch_class: str = ""
    energy: str = ""
    pace: str = ""
    delivery: str = ""
    emotions: list[str] = field(default_factory=list)


@dataclass
class AudioMusicProfile:
    present: bool = False
    genres: list[str] = field(default_factory=list)
    instruments: list[str] = field(default_factory=list)
    mood: list[str] = field(default_factory=list)
    tempo_bpm: float | None = None
    rhythmic_feel: str = ""
    tonal_character: str = ""


@dataclass
class AudioRhythm:
    tempo_bpm: float | None = None
    confidence: float | None = None
    beat_times_s: list[float] = field(default_factory=list)
    downbeat_times_s: list[float] = field(default_factory=list)
    strong_onsets_s: list[float] = field(default_factory=list)


@dataclass
class AudioSignalFacts:
    duration_s: float = 0.0
    sample_rate: int | None = None
    channels: int | None = None
    avg_loudness_db: float | None = None
    peak_time_s: float | None = None
    dynamic_range_db: float | None = None
    silence_regions: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class AudioObservation:
    sha256: str
    signal: AudioSignalFacts
    speech: list[TimedSpeech] = field(default_factory=list)
    events: list[AudioEvent] = field(default_factory=list)
    voice: AudioVoiceProfile = field(default_factory=AudioVoiceProfile)
    music: AudioMusicProfile = field(default_factory=AudioMusicProfile)
    rhythm: AudioRhythm = field(default_factory=AudioRhythm)

    # 自由语义 fallback 仅补充本字段，不替换确定性事实
    semantic_summary: str = ""
    semantic_facts: list[str] = field(default_factory=list)

    analyzer_version: str = "audio-1"
    model_ids: dict[str, str] = field(default_factory=dict)
    confidence: float | None = None
    fallback_used: bool = False

    def hash(self) -> str:
        ...
```

---

# 6. AssetCard 改造原则

保留现有字段，避免大范围破坏。

建议追加：

```python
@dataclass
class AssetCard:
    ...
    audio_observation: AudioObservation | None = None
```

现有：

```python
transcript
language
timbre
music
characterisation
```

继续保留，作为向后兼容 / renderer-friendly projection。

规则：

```text
AudioObservation = 原始事实
AssetCard.audio_observation = 完整结构化事实
AssetCard.transcript/timbre/music = 从 Observation 派生的兼容摘要
ManifestEntry.characterisation = Role-aware projection
```

禁止：

```text
AudioObservation 直接存最终 H3 prose
```

---

# 7. 新目录结构

建议新增：

```text
h3ir/
├── audio/
│   ├── __init__.py
│   ├── models.py
│   ├── observer.py
│   ├── client.py
│   ├── dsp.py
│   ├── clap.py
│   ├── router.py
│   ├── fallback.py
│   ├── projector.py
│   ├── cache.py
│   └── merge.py
```

职责：

### `audio/observer.py`

总入口：

```python
observe_audio(ref, config) -> AudioObservation
```

---

### `audio/client.py`

调用独立 Audio Worker：

```text
SenseVoice
FSMN-VAD
CAM++
```

OpenH3-IR Core 不直接依赖 torch / funasr。

---

### `audio/dsp.py`

本地轻量 DSP。

---

### `audio/clap.py`

可支持两种模式：

1. Audio Worker 内运行
2. 独立 CLAP endpoint

默认推荐 Audio Worker 内运行，Core 只拿 JSON。

---

### `audio/router.py`

判断是否调用 Qwen2.5-Omni-3B。

---

### `audio/fallback.py`

Qwen2.5-Omni-3B client。

---

### `audio/projector.py`

把：

```text
AudioObservation + Role + User Note
```

变成：

```text
RoleAudioProjection
```

---

### `audio/cache.py`

只缓存由 bytes 决定的 Observation。

---

### `audio/merge.py`

合并 deterministic analyser 和 Omni fallback。

---

# 8. Audio Worker API

建议把重音频依赖放在独立进程，而不是塞入 `open-h3-ir` 核心依赖。

## Endpoint

```http
POST /v1/audio/analyze
Content-Type: multipart/form-data
```

字段：

```text
file
enable_diarization=true
enable_clap=true
enable_dsp=true
```

返回：

```json
{
  "version": "audio-worker-1",
  "duration_s": 8.52,
  "speech": [
    {
      "start_s": 1.30,
      "end_s": 3.46,
      "speaker_id": "SPK_0",
      "text": "Don't move.",
      "language": "en",
      "emotion": "fearful",
      "confidence": 0.93
    }
  ],
  "events": [
    {
      "start_s": 4.73,
      "end_s": 5.04,
      "label": "metallic impact",
      "confidence": 0.87,
      "source": "clap"
    }
  ],
  "music": {
    "present": true,
    "genres": ["dark ambient", "cinematic"],
    "instruments": ["synth pad", "low strings"],
    "mood": ["tense"],
    "tempo_bpm": 72.4
  },
  "rhythm": {
    "tempo_bpm": 72.4,
    "confidence": 0.91,
    "beat_times_s": [0.81, 1.64, 2.47],
    "downbeat_times_s": [],
    "strong_onsets_s": [4.73]
  },
  "signal": {
    "sample_rate": 48000,
    "channels": 2,
    "avg_loudness_db": -18.7,
    "peak_time_s": 4.75,
    "dynamic_range_db": 11.3,
    "silence_regions": []
  }
}
```

---

# 9. 配置设计

在 `h3ir/config.py` 新增：

```python
@dataclass(frozen=True)
class AudioConfig:
    enabled: bool
    base_url: str
    api_key: str
    timeout_s: float

    diarization: bool
    clap_enabled: bool
    dsp_enabled: bool

    fallback_enabled: bool
    fallback_base_url: str
    fallback_model: str
    fallback_api_key: str
    fallback_timeout_s: float

    confidence_threshold: float
    event_confidence_threshold: float
    cache_enabled: bool
```

环境变量建议：

```bash
H3IR_AUDIO_ENABLED=1
H3IR_AUDIO_URL=http://127.0.0.1:50000
H3IR_AUDIO_KEY=not-needed
H3IR_AUDIO_TIMEOUT=120

H3IR_AUDIO_DIARIZATION=1
H3IR_AUDIO_CLAP=1
H3IR_AUDIO_DSP=1

H3IR_AUDIO_FALLBACK=1
H3IR_AUDIO_FALLBACK_URL=http://127.0.0.1:8001/v1
H3IR_AUDIO_FALLBACK_MODEL=Qwen2.5-Omni-3B
H3IR_AUDIO_FALLBACK_KEY=not-needed
H3IR_AUDIO_FALLBACK_TIMEOUT=180

H3IR_AUDIO_CONFIDENCE_THRESHOLD=0.65
H3IR_AUDIO_EVENT_CONFIDENCE_THRESHOLD=0.55
H3IR_AUDIO_CACHE=1
```

`Config`：

```python
@dataclass(frozen=True)
class Config:
    llm: LLMConfig
    audio: AudioConfig
    comfy: ComfyConfig
    ...
```

---

# 10. Fallback Router

Qwen2.5-Omni-3B 不应由一个单一 confidence 决定是否调用。

建议实现规则评分。

```python
@dataclass
class FallbackDecision:
    use_fallback: bool
    reasons: list[str]
```

## 强制 fallback 条件

满足任意一个：

1. 用户明确要求：
   - detailed sound description
   - acoustic environment
   - instrumentation details
   - exact sound character
2. Role 为 `MUSIC_STYLE`，但：
   - `music.present == True`
   - `genres` 和 `instruments` 都为空
3. Role 为 `VOICE_TIMBRE`，有 speech 但 voice profile 基本为空。
4. Role 为 `SFX`，CLAP 只有低 confidence / unknown。
5. 音频存在明显复杂混合：
   - speech + music + 多事件重叠
   - 但结构化分析无法给出足够解释。
6. Audio Worker 返回 incomplete / partial。
7. 平均语义 confidence < threshold。

## 不应 fallback 的情况

- 纯 ASR 已经清楚
- 纯 beat reference 且 BPM / beat timestamps 可靠
- 纯 BGM copy 且无需描述风格
- 用户只需要复制信号
- 只有 duration / sync 需求

---

# 11. Qwen2.5-Omni-3B fallback 输出协议

Omni 只允许输出补充事实：

```json
{
  "semantic_summary": "",
  "voice_delivery": [],
  "music_style": [],
  "instrumentation": [],
  "soundscape": [],
  "event_descriptions": [
    {
      "approx_start_s": null,
      "approx_end_s": null,
      "description": ""
    }
  ],
  "confidence": 0.0
}
```

System Prompt 必须包含：

```text
You are a fallback acoustic observer.

You may supplement semantic descriptions, but you must not overwrite:
- transcript text
- speaker segment boundaries
- BPM
- beat timestamps
- exact event timestamps
- duration
- user-declared role

If you are uncertain, omit the fact.
Do not invent precise timestamps.
Do not infer story or intent.
Return JSON only.
```

---

# 12. Merge Policy

`merge.py` 必须使用明确优先级。

```text
Tier 1: ffprobe / DSP exact facts
Tier 2: VAD / ASR / CAM++ / CLAP high-confidence facts
Tier 3: Qwen2.5-Omni semantic supplements
Tier 4: user note
```

注意：

用户 `note` 不是“低优先级事实”。

它应单独保存为：

```text
caller_description
```

因为用户可能是在声明“怎么使用”，而不是在描述“实际听到什么”。

冲突必须保留，并生成 Finding。

---

# 13. Audio Note 冲突处理

例如：

用户 note：

```text
low male whisper
```

Analyzer：

```text
high-pitched female speech
```

不能静默覆盖。

新增 Finding：

```text
A1-audio-note-discrepancy
```

示例：

```python
Finding(
    "A1-audio-note-discrepancy",
    "WARN",
    "<Audio 1> is described by the caller as a low male whisper, "
    "while the acoustic analyser reports a substantially different vocal profile."
)
```

原则：

- Role：用户为准
- 原始声学事实：Analyzer 为准
- 创作意图：用户为准
- 冲突：显式 warning
- 不自动猜测用户“真正想要哪个”

---

# 14. Role-aware Audio Projector

新增：

```python
@dataclass
class RoleAudioProjection:
    role: Role
    characterisation: str
    planner_facts: list[str]
    timeline_constraints: list[dict]
    findings: list[Finding]
```

入口：

```python
project_audio(
    observation: AudioObservation,
    role: Role,
    caller_note: str,
) -> RoleAudioProjection
```

---

## 14.1 VOICE_TIMBRE

使用：

- speaker count
- language
- pitch
- energy
- pace
- emotion
- delivery
- transcript 仅作为 dialogue-content fact，不当作 timbre

示例：

```text
a soft, low-energy English voice reference with a slow, tense delivery
```

不要写：

```text
a voice saying "Don't move"
```

来替代 timbre 描述。

---

## 14.2 BGM

重点：

- 这是 signal reuse
- duration
- music presence
- broad music character
- synchronization

不要错误转换成：

```text
music-style reference
```

---

## 14.3 MUSIC_STYLE

只投影：

- genre
- instrumentation
- tempo
- mood
- rhythmic feel
- tonal character

必须明确：

```text
newly generated score
```

不要暗示原音频信号被复制。

---

## 14.4 BEAT_REFERENCE

重点：

- BPM
- strong beats
- downbeats
- salient onset
- edit/action synchronization

characterisation 示例：

```text
a rhythmic reference with an approximately 128 BPM pulse and prominent accents around 1.90s, 3.80s and 5.70s
```

但不要往 prose 塞数十个 beat timestamp。

只选择 planner 需要的 salient beats。

---

## 14.5 SFX

使用：

- event label
- texture
- timing
- attack / decay（如果有可靠信息）

例如：

```text
a sharp metallic impact sound-texture reference
```

Role 是 `SFX` 时 retention 仍必须是 `reference`，不能因为检测到真实 signal 就改成 copy。

---

# 15. 修改 `analyse.py`

当前：

```python
analyse_audio(ref, transcript, duration_s)
```

改造建议：

```python
def analyse_audio(
    ref: AssetRef,
    transcript: str = "",
    *,
    duration_s: float | None = None,
    audio_backend: AudioBackend | None = None,
    use_cache: bool = True,
) -> AssetCard:
```

流程：

```text
if audio disabled:
    existing legacy path

elif no file path / inaccessible:
    legacy metadata path + Finding

else:
    load AudioObservation cache
        ↓ miss
    Audio Worker analyse
        ↓
    fallback router
        ↓ optional Qwen2.5-Omni
    merge
        ↓
    save Observation cache
        ↓
    project compatibility fields
        ↓
    AssetCard
```

---

# 16. Audio Cache 重构

当前“AudioCard 不缓存”的设计在旧逻辑下是正确的。

新增音频分析后必须改为：

> 缓存 `AudioObservation`，不缓存 request-specific projection。

Cache Key：

```text
sha256(audio bytes)
+
AUDIO_ANALYZER_VERSION
+
SenseVoice model id
+
CAM++ model id
+
CLAP model id
+
DSP version
+
fallback model/version when fallback_used
```

不要加入：

- Role
- user note
- H3 target duration
- user prompt

因为这些属于 Projection。

目录建议：

```text
~/.local/share/h3ir/cache/audio/
```

示例：

```text
cache/audio/<key>.json
```

---

# 17. `plan.py` 集成

当前顺序大致：

```python
target = Target.build(...)
manifest = build_manifest(...)
subjects = build_subjects(...)
...
```

建议：

```python
target = Target.build(...)
manifest = build_manifest(...)
audio_ctx = hydrate_audio_manifest(manifest, cards, brief.assets)
subjects = build_subjects(...)
...
```

新增：

```python
def hydrate_audio_manifest(
    manifest: list[ManifestEntry],
    cards: dict[str, AssetCard],
    refs: list[AssetRef],
) -> AudioPlanContext:
    ...
```

该函数负责：

1. 找到 Audio `ManifestEntry`
2. 找到对应 `AssetCard.audio_observation`
3. 根据 `Role` 做 projection
4. 写入：
   - `ManifestEntry.characterisation`
5. 收集：
   - timeline constraints
   - sound events
   - findings
   - salient beat timestamps

---

# 18. Timeline Audio 增强

这是本次开发最有价值的部分之一。

## 18.1 Beat snapping

当前模型提出：

```text
cut = 3.67s
```

如果存在：

```text
Role.BEAT_REFERENCE
strong beats = [1.90, 3.80, 5.70]
```

允许：

```text
3.67 → 3.80
```

但需要设置最大 snap window：

```python
MAX_BEAT_SNAP_MS = 250
```

只有：

```text
abs(proposed - beat) <= MAX_BEAT_SNAP_MS
```

才 snap。

不能为了跟拍把镜头结构大幅改掉。

---

## 18.2 SFX → Shot mapping

对：

```json
{
  "start_s": 4.23,
  "label": "metallic impact"
}
```

根据 shot span 找到对应 Shot：

```text
Shot 2 = 3.8–6.4
```

转成：

```python
sound_events = [{
    "shot": 2,
    "layer": "sync",
    "text": "a sharp metallic impact"
}]
```

继续使用现有 `split_sound()`。

---

## 18.3 Ambient detection

持续长时间事件例如：

```text
rain
crowd ambience
engine hum
wind
```

如果覆盖视频主体时间范围，应进入：

```text
overall_soundscape
```

而不是每个 shot 重复。

建议规则：

```text
event duration / audio duration >= 0.45
→ candidate ambient
```

最终仍结合 event class。

---

# 19. Video 内嵌音频

第二阶段必须支持 reference video 的 soundtrack。

当前已有：

```text
paired_video_sha256
paired_with=<Video N>
```

在 analyse video 时新增：

```text
ffmpeg extract audio
```

例如：

```bash
ffmpeg -i input.mp4 -vn -ac 1 -ar 16000 extracted.wav
```

然后：

```text
Video
├── sampled frames → existing VLM
└── extracted audio → Audio Observer
```

最终保持两个逻辑 Asset：

```text
<Video N>
<Audio N>
```

不要把 Audio facts 混入 Video AssetCard 的 visual fields。

---

# 20. Audio-Visual Temporal Association（后续增强）

在已有 visual sampled frame 基础上，可以逐步新增：

```text
visual event @ time
↔
audio event @ time
```

例如：

```text
4.20s: visual door closes
4.24s: impact sound
```

形成：

```json
{
  "type": "av_sync",
  "time_s": 4.22,
  "visual": "door closure",
  "audio": "door impact",
  "confidence": 0.86
}
```

该功能属于 v3，不阻塞 Audio v1/v2。

---

# 21. `render.py` 改造

当前 renderer 从：

```python
ManifestEntry.characterisation
```

写 `<Audio N>`。

保留这个接口。

但 characterisation 应从：

```text
Role-aware projection
```

获得，而不是仅来自 `note`。

这样可以最大限度减少 renderer 修改。

必须继续保证：

- Role 决定定义语义
- `BGM` 是 reuse
- `VOICE_TIMBRE/MUSIC_STYLE/BEAT_REFERENCE/SFX` 是 reference
- renderer 不自行改变 retention marker

---

# 22. `prose.py` / Qwen3.8 输入增强

给 Planner / Composer 增加结构化 audio facts，但不要直接扔完整 raw Observation。

构造一个压缩版：

```json
{
  "<Audio 1>": {
    "role": "beat_reference",
    "characterisation": "...",
    "tempo_bpm": 128.0,
    "salient_beats_s": [1.9, 3.8, 5.7],
    "events": []
  }
}
```

对于 voice：

```json
{
  "<Audio 1>": {
    "role": "voice_timbre",
    "language": "en",
    "speaker_count": 1,
    "delivery": "soft, tense, slow",
    "transcript_available": true
  }
}
```

不要把 100+ 个 beat timestamps 塞给 Planner。

---

# 23. Validator 新规则

建议在 `validate.py` 增加：

## A20 — audio role/projection consistency

`MUSIC_STYLE` 不得描述为 copied signal。

---

## A21 — beat reference must not claim signal reuse

`BEAT_REFERENCE` 必须是 reference。

---

## A22 — voice timbre must not be inferred from transcript alone

若 `timbre` 的唯一来源是 transcript，则 WARN/ERROR。

---

## A23 — audio event time in range

所有 event：

```text
0 <= start <= end <= asset duration
```

---

## A24 — beat times monotonic

```text
beat[i] < beat[i+1]
```

---

## A25 — audio source traceability

IR 中出现明确音频声学事实时，应能追踪至：

- analyser
- caller note
- fallback

---

## A26 — fallback may not overwrite deterministic timing

如果 provenance 表示 Omni 修改了：

- duration
- ASR timestamp
- beat timestamp

则 ERROR。

---

## A27 — note discrepancy is visible

存在高置信度 caller/analyser 冲突时必须存在 Finding。

---

# 24. Provenance

增强 `IRDocument.provenance`：

```json
{
  "audio": {
    "<Audio 1>": {
      "observation_hash": "...",
      "audio_worker": "audio-worker-1",
      "sensevoice_model": "...",
      "speaker_model": "...",
      "clap_model": "...",
      "fallback_used": true,
      "fallback_model": "Qwen2.5-Omni-3B",
      "projection_role": "music_style"
    }
  }
}
```

目标：

> 每一句音频 Context-IR 都应该能解释“它为什么这么写”。

---

# 25. 降级策略

必须支持三种运行状态。

## FULL

```text
Audio Worker available
+ optional Omni fallback available
```

---

## PARTIAL

```text
Audio Worker available
Omni fallback unavailable
```

仍正常编译。

记录：

```text
fallback unavailable
```

但不应失败。

---

## LEGACY

```text
Audio enhancement disabled
或 Audio Worker unreachable
```

可配置：

```text
strict
legacy
```

建议默认：

```text
legacy
```

即恢复现在的：

```text
Role + note + transcript + duration
```

但生成 WARN：

```text
A0-audio-analysis-degraded
```

若用户配置：

```bash
H3IR_AUDIO_REQUIRED=1
```

则 Audio Worker 不可用时拒绝请求。

---

# 26. 不要引入的重依赖

OpenH3-IR 当前核心依赖很轻。

不要直接把以下放进主 `dependencies`：

- torch
- transformers
- funasr
- librosa
- clap
- modelscope

优先保持 Core：

```text
HTTP client
+
JSON schemas
+
light local code
```

重模型放 Audio Worker。

可以增加 optional extra：

```toml
[project.optional-dependencies]
audio-local = [
  "librosa",
  "numpy"
]
```

但默认安装不拉重模型。

---

# 27. Audio Worker 项目形式

可先放在同仓库：

```text
services/
└── audio_worker/
    ├── app.py
    ├── models.py
    ├── sensevoice_backend.py
    ├── clap_backend.py
    ├── dsp_backend.py
    ├── requirements.txt
    └── README.md
```

后续稳定后再拆仓库。

---

# 28. 测试要求

当前仓库已经有 Audio 相关测试，因此必须修改旧假设，不要简单删除测试。

至少新增：

```text
tests/test_audio_observation.py
tests/test_audio_cache.py
tests/test_audio_projection.py
tests/test_audio_fallback_router.py
tests/test_audio_merge.py
tests/test_audio_timeline.py
tests/test_audio_findings.py
tests/test_audio_degraded_mode.py
tests/test_video_audio_pairing.py
```

---

## 28.1 Cache 测试

必须证明：

同一 audio bytes：

```text
Role.BGM
Role.MUSIC_STYLE
Role.BEAT_REFERENCE
```

只产生一个 `AudioObservation` cache。

但 projection 必须不同。

---

## 28.2 Role projection 测试

给同一 Observation：

```text
128 BPM electronic track
```

断言：

### BGM

包含：

```text
background music / synchronized audio
```

不得写：

```text
newly generated score
```

### MUSIC_STYLE

包含：

```text
newly generated score
```

不得 claim copy。

### BEAT_REFERENCE

包含：

```text
rhythm / timing / beat
```

不得 claim copy。

---

## 28.3 Omni fallback 测试

Mock Audio Worker 返回低 confidence：

```json
{
  "music": {"present": true, "genres": [], "instruments": []}
}
```

Role：

```text
music_style
```

应触发 fallback。

如果是：

```text
bgm
```

则不一定触发。

---

## 28.4 Merge 测试

Omni 返回：

```text
tempo = 140
```

DSP 返回：

```text
tempo = 128.1
confidence = 0.94
```

最终：

```text
128.1
```

Omni 不得覆盖。

---

## 28.5 Beat snapping 测试

model cut：

```text
3.67
```

beat：

```text
3.80
```

阈值：

```text
250ms
```

结果：

```text
3.80
```

如果最近 beat 是：

```text
4.10
```

不得 snap。

---

## 28.6 No-audio regression

在：

```text
H3IR_AUDIO_ENABLED=0
```

状态下：

- 所有现有 image/video tests 应通过
- deterministic render hash 不应因新增模块发生无关变化
- 非音频 Prompt 不应改变

---

# 29. Acceptance Criteria

Audio v1 完成条件：

- [ ] Audio Worker 可独立运行
- [ ] SenseVoice ASR 接入
- [ ] VAD 接入
- [ ] CAM++ speaker IDs 接入
- [ ] DSP duration/BPM/beats/onsets 接入
- [ ] `AudioObservation` 可序列化
- [ ] Observation cache 正常
- [ ] legacy mode 正常
- [ ] 非音频 tests 无回归

Audio v2 完成条件：

- [ ] CLAP event / sound semantics
- [ ] Role-aware projection
- [ ] Manifest characterisation 使用 projection
- [ ] Beat reference 能影响 timeline
- [ ] SFX 能映射到 shot
- [ ] ambient/sync 能正确分流
- [ ] 新 validator rules
- [ ] caller/analyser discrepancy Finding

Full fallback 完成条件：

- [ ] Qwen2.5-Omni-3B endpoint 配置
- [ ] fallback router
- [ ] strict JSON output
- [ ] merge policy
- [ ] deterministic facts 不被覆盖
- [ ] provenance 记录 fallback
- [ ] fallback 不可用时不破坏 Audio Worker 主路径

v3 完成条件：

- [ ] reference video 自动提取 soundtrack
- [ ] paired audio observation
- [ ] AV event alignment
- [ ] video soundtrack timing 可进入 H3 planning

---

# 30. 性能目标

第一版目标，不作为硬实时要求：

### 无 fallback

10 秒音频：

```text
Audio Observation <= 3s~8s
```

视硬件而定。

### 有 fallback

额外：

```text
Qwen2.5-Omni-3B latency
```

但不得阻塞不需要 fallback 的请求。

### Cache hit

目标：

```text
< 100ms
```

读取 Observation + role projection。

---

# 31. Fallback 加载策略

推荐 Qwen2.5-Omni-3B：

```text
on-demand service
```

而不是长期占用主 Planner 显存。

可支持：

```text
H3IR_AUDIO_FALLBACK_URL
```

用户自己决定由：

- vLLM
- 独立 Python service
- 其他兼容 endpoint

承载。

不要在 OpenH3-IR 内实现 GPU model lifecycle。

---

# 32. 安全与鲁棒性

Audio Worker：

- 限制最大上传尺寸
- 限制最大音频时长
- ffmpeg 调用禁止 shell=True
- 所有路径必须使用现有 asset security policy
- 临时 WAV 必须自动清理
- 模型异常不得返回伪造空成功
- partial response 必须标记 incomplete

---

# 33. 开发阶段与推荐 Commit 顺序

## Commit 1 — audio contracts

只增加：

- `AudioObservation`
- AudioConfig
- serialization
- unit tests

不要接模型。

---

## Commit 2 — audio worker protocol

实现：

- client
- mock server tests
- health check
- degraded path

---

## Commit 3 — SenseVoice / VAD / CAM++

实现 speech layer。

---

## Commit 4 — DSP

实现：

- BPM
- beats
- onset
- signal facts

---

## Commit 5 — Observation cache

修改现有：

```text
test_audio_card_is_not_cached.py
```

不要简单删除。

新语义：

```text
request-specific AudioCard projection 不作为全局 cache
byte-derived AudioObservation 可以 cache
```

---

## Commit 6 — Role projector

实现五种 Role。

---

## Commit 7 — plan/render integration

- hydrate audio manifest
- characterisation
- planner facts

---

## Commit 8 — timeline integration

- beat snapping
- SFX → shot
- ambient/sync

---

## Commit 9 — CLAP

增加 sound semantics。

---

## Commit 10 — Qwen2.5-Omni fallback

最后增加。

原因：

如果基础 Observation / projection 没稳定，先上 Omni 会掩盖架构问题。

---

## Commit 11 — video soundtrack

最后做 video embedded audio。

---

# 34. Codex 开发约束

Codex 在修改仓库时必须遵守：

1. **先阅读当前实现，不凭本文档猜函数签名。**
2. 保留现有 OpenH3-IR 架构：
   - Analyse
   - Plan
   - Render
   - Validate
3. 不重写整个 `analyse.py`。
4. 新能力优先新增模块。
5. 不把 torch/FunASR/CLAP 加入 core 默认依赖。
6. 不改变非音频行为。
7. 所有 request-specific 数据不得错误进入 content-addressed cache。
8. 所有 byte-derived Observation 必须可缓存。
9. 每个结构性改动必须有 unit test。
10. 不删除现有 validator 来“让新输出通过”。
11. 如果旧 validator 与新增音频事实冲突，应解释语义并新增/修改精确规则。
12. `Role` 仍然是用户声明用途的 ground truth。
13. Omni fallback 不得改变 Role / retention / task type。
14. Omni fallback 不得覆盖 deterministic timing。
15. 所有新增外部 service 必须支持 timeout 和明确错误。
16. Audio enhancement 关闭时必须可恢复 legacy 行为。
17. bump audio analyzer version when Observation contract changes。
18. 不使用 cache 隐藏失败；测试需要覆盖 cold-cache。
19. 每阶段运行完整 pytest。
20. 完成后输出：
    - 改动文件列表
    - 新增环境变量
    - 测试结果
    - 已知限制

---

# 35. Codex 首轮任务建议

不要一次让 Codex 实现全部功能。

第一轮只做：

```text
Phase A:
AudioObservation contracts
+
AudioConfig
+
Audio Worker client abstraction
+
legacy-compatible analyse_audio integration
+
Observation cache skeleton
+
tests
```

要求：

- 暂时用 mock Audio Worker
- 不安装 SenseVoice
- 不装 CLAP
- 不接 Qwen2.5-Omni
- 确认架构和 cache 语义正确

第二轮：

```text
Phase B:
真实 Audio Worker
+
SenseVoice
+
VAD
+
CAM++
+
DSP
```

第三轮：

```text
Phase C:
Role Projector
+
Plan/Render
+
Timeline
```

第四轮：

```text
Phase D:
CLAP
+
Qwen2.5-Omni fallback
```

---

# 36. 首轮 Codex Prompt

可直接交给 Codex：

```text
You are modifying my fork of OpenH3-IR.

Repository:
DreamLoveBetty/open-h3-ir

Goal:
Implement Phase A of the Enhanced Audio Context-IR architecture described in
docs/ENHANCED_AUDIO_CONTEXT_IR.md.

Before editing:
1. Inspect the current main branch.
2. Read at minimum:
   h3ir/models.py
   h3ir/analyse.py
   h3ir/config.py
   h3ir/plan.py
   h3ir/render.py
   h3ir/compile.py
   h3ir/validate.py
   tests/test_audio_card_is_not_cached.py
   tests/test_audio_claims.py
   pyproject.toml
3. Preserve all existing non-audio behaviour.

Implement ONLY Phase A:
- Add structured AudioObservation contracts.
- Add AudioConfig.
- Add an audio client abstraction for an external Audio Worker.
- Integrate the abstraction into analyse_audio while preserving a legacy/degraded path.
- Add a content-addressed AudioObservation cache skeleton.
- Do not implement SenseVoice, CLAP, or Qwen2.5-Omni yet.
- Do not add torch or other heavy ML dependencies to the core package.
- Do not redesign the entire compiler.
- Do not remove validators to make tests pass.

Critical caching rule:
- AudioObservation is derived from audio bytes and may be cached.
- Role/user note/request-specific projection must NOT be stored in the content-derived observation cache.

Compatibility:
- H3IR_AUDIO_ENABLED=0 must preserve the current behaviour.
- If no audio is present, output should remain unchanged.
- External Audio Worker failures must have explicit error/degraded semantics.

Tests:
- Add focused tests for configuration, observation serialization, cache semantics,
  legacy mode, and mock Audio Worker behaviour.
- Update the old audio non-cache test to express the new distinction between
  byte-derived Observation caching and request-specific projection.
- Run the full pytest suite.

Do not start Phase B.

At the end report:
- files changed
- architecture decisions
- environment variables
- test results
- known limitations
```

---


# 36A. Fork / Upstream 同步与分支管理规则

本项目基于原作者仓库的 fork 继续开发，因此必须把“可持续同步 upstream”作为长期维护约束，而不是只考虑当前一次开发。

## 36A.1 远程仓库约定

本地仓库必须同时保留两个 remote：

```bash
origin
```

指向自己的 fork：

```text
https://github.com/DreamLoveBetty/open-h3-ir.git
```

以及：

```bash
upstream
```

指向原作者主仓库：

```text
https://github.com/ruashots/open-h3-ir.git
```

首次配置：

```bash
git remote add upstream https://github.com/ruashots/open-h3-ir.git
git remote -v
```

预期：

```text
origin    → DreamLoveBetty/open-h3-ir
upstream  → ruashots/open-h3-ir
```

---

## 36A.2 `main` 分支原则

**不要长期直接在 `main` 上进行 Enhanced Audio 大规模开发。**

`main` 的职责是：

> 尽可能保持接近原作者 `upstream/main`，作为后续同步和冲突处理的稳定基线。

推荐关系：

```text
upstream/main
      │
      ▼
origin/main
      │
      ▼
feature/enhanced-audio
```

原作者更新后，先同步本地 `main`：

```bash
git fetch upstream
git checkout main
git merge upstream/main
git push origin main
```

如果团队明确使用 rebase 工作流，也可以：

```bash
git fetch upstream
git checkout main
git rebase upstream/main
git push origin main
```

但不要在同一开发周期中频繁混用 merge 与 rebase。

---

## 36A.3 Enhanced Audio 开发分支

主增强功能建议维护在：

```text
feature/enhanced-audio
```

创建：

```bash
git checkout main
git checkout -b feature/enhanced-audio
```

后续 upstream 更新后：

```bash
git checkout main
git fetch upstream
git merge upstream/main
git push origin main

git checkout feature/enhanced-audio
git merge main
```

如果开发分支尚未共享给其他人，也可以在明确需要线性历史时：

```bash
git checkout feature/enhanced-audio
git rebase main
```

但如果分支已经被多人共同使用，优先 `merge main`，避免重写共享历史。

---

## 36A.4 推荐的子功能分支

为了降低后续 upstream 冲突成本，Enhanced Audio 不建议全部堆在一个巨大 commit 中。

推荐按阶段拆分：

```text
feature/audio-contract
feature/audio-worker
feature/audio-observation-cache
feature/audio-projector
feature/audio-timeline
feature/audio-clap
feature/audio-omni-fallback
feature/video-audio-association
```

完成后再合入：

```text
feature/enhanced-audio
```

这样当 upstream 同时修改：

```text
analyse.py
models.py
plan.py
render.py
validate.py
```

时，可以更容易判断冲突属于哪个功能阶段。

---

## 36A.5 Codex 的 Upstream 兼容约束

Codex 在实现任何 Enhanced Audio 功能前，必须先检查：

```bash
git status
git remote -v
git branch --show-current
git log --oneline --decorate -n 10
```

如果存在 `upstream`，还应检查：

```bash
git fetch upstream
git log --oneline HEAD..upstream/main
```

目的：

> 确认原作者是否已经更新了当前准备修改的模块，避免在旧代码基础上继续开发。

Codex 不得未经用户明确要求：

- 强制覆盖 `main`
- `git reset --hard upstream/main`
- force push
- 删除用户已有 feature branch
- 自动丢弃冲突中的用户修改
- 自动把自己的 fork 改造成与 upstream 完全一致

---

## 36A.6 Upstream 更新后的冲突处理原则

如果 upstream 与 Enhanced Audio 修改了同一区域：

```text
analyse.py
models.py
plan.py
render.py
validate.py
config.py
```

必须执行“语义合并”，不能简单选择：

```text
ours
```

或：

```text
theirs
```

而应逐项确认：

1. upstream 是否新增了新的数据字段或 contract。
2. upstream 是否修改了 AssetCard / Manifest / Plan 的 invariant。
3. upstream 是否新增 validator rule。
4. upstream 是否改变 Audio Role / retention / task type 定义。
5. upstream 是否改变 cache key / analyzer version。
6. upstream 是否改变 compile stage 顺序。
7. upstream 是否已经实现了与本增强方案重叠的 Audio 功能。

冲突解决完成后必须：

```bash
pytest
```

运行完整测试，而不是只运行新增 Audio 测试。

---

## 36A.7 不应直接修改 upstream 语义的区域

以下区域属于 OpenH3-IR 的核心兼容面，Enhanced Audio 应尽量“扩展而非覆盖”：

```text
Mode
Role
Manifest label ordering
Retention markers
Task types
deterministic render invariants
validator semantics
IRDocument determinism
```

如果 upstream 后续修改了这些定义：

> 以 upstream 当前语义为新的基线，再重新适配 Enhanced Audio。

不要为了维持旧 fork 行为而长期冻结旧 contract。

---

## 36A.8 Upstream 同步后的 Audio 适配检查表

每次同步原作者更新后，至少检查：

- [ ] `h3ir/models.py` 的 `AssetCard` / `ManifestEntry` / `Plan`
- [ ] `h3ir/analyse.py` 的 analyzer contract
- [ ] `h3ir/plan.py` 的 Role / retention / task type
- [ ] `h3ir/render.py` 的 Audio render 规则
- [ ] `h3ir/compile.py` 的 stage order
- [ ] `h3ir/validate.py` 的 Audio validator
- [ ] `h3ir/config.py` 的配置模型
- [ ] Audio 相关旧测试是否增加或改变
- [ ] `pyproject.toml` 的依赖与 package-data
- [ ] ComfyUI/API contract 是否受到影响

---

## 36A.9 Upstream 新增 Audio 功能时的处理方式

如果原作者未来自己实现了：

```text
audio analysis
audio captioning
audio cache
audio timeline
```

不要机械地同时保留两套平行实现。

Codex 应先比较：

```text
upstream implementation
vs
Enhanced Audio implementation
```

按模块决定：

```text
adopt
extend
replace
deprecate
```

原则：

> 优先复用 upstream 新增的稳定 contract，只保留本 fork 真正增强的部分。

例如 upstream 如果已经新增：

```python
AudioObservation
```

则不要继续维护第二个：

```python
EnhancedAudioObservation
```

而应把：

```text
SenseVoice
CLAP
Omni fallback
beat snapping
AV association
```

适配到 upstream 的正式类型上。

---

## 36A.10 推荐维护流程

长期开发建议使用：

```text
1. Sync upstream/main
2. Run baseline tests
3. Merge/rebase into feature branch
4. Resolve conflicts semantically
5. Run full tests
6. Continue Enhanced Audio work
7. Commit small logical changes
8. Push to origin feature branch
```

推荐周期性执行：

```bash
git fetch upstream
```

不要等 Enhanced Audio 完成数月后才第一次同步 upstream。

---

## 36A.11 Codex 每个开发阶段结束时追加报告

Codex 除了原有的：

- files changed
- architecture decisions
- environment variables
- test results
- known limitations

还必须额外报告：

```text
Upstream Compatibility
- current branch
- upstream remote detected: yes/no
- upstream/main compared: yes/no
- commits behind upstream/main
- files overlapping upstream recent changes
- merge conflicts encountered
- compatibility decisions made
```

这样后续每次继续开发时，都能知道当前 fork 与原作者的距离。

---

# 37. 最终目标

完成后，本地 OpenH3-IR 的 Audio 路径应从：

```text
Audio
→ Role + note + transcript
→ Context-IR
```

升级为：

```text
Audio bytes
   │
   ▼
Audio Observation
   │
   ├── speech
   ├── speaker
   ├── emotion
   ├── sound events
   ├── music
   ├── BPM / beats
   ├── acoustic facts
   └── temporal facts
   │
   ▼
Confidence Router
   │
   └── Qwen2.5-Omni-3B fallback when necessary
   │
   ▼
Role-aware Projection
   │
   ├── VOICE_TIMBRE
   ├── BGM
   ├── MUSIC_STYLE
   ├── BEAT_REFERENCE
   └── SFX
   │
   ▼
Audio-aware Timeline / Context Planning
   │
   ▼
Existing OpenH3-IR Compiler + Validator
   │
   ▼
H3 Context-IR
```

核心目标不是让系统“会描述音频”，而是：

> **让音频成为 H3 Context Planning 的一等结构化输入，并正确参与 Reference Binding、Retention、Soundscape、Shot Timeline 和 Audio-Visual Synchronization。**
