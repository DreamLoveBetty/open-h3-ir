"""Local audio understanding for OpenH3-IR.

The pipeline this package is the front of:

    audio bytes
      -> Audio Worker (SenseVoice + FSMN-VAD + CAM++ + DSP + CLAP, over HTTP)
      -> AudioObservation            (structured facts, cached on the bytes)
      -> role-aware projection       (request-specific, never cached)
      -> manifest / plan / timeline  (the existing compiler, untouched in shape)

Submodules land in phases: models / client / cache / observer are the contract phase;
router / fallback / merge / projector follow. Nothing here is imported unless audio is
enabled, so the default install carries the code and never runs it.
"""
