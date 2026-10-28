"""The experiment input: `bvl-experiment-2` -> Input Lock -> INPUT_LOCKED run.

    envelope    I0/I1  strict JSON and the closed envelope grammar
    resolve     I2     reference resolution, read once into a private snapshot
    profile     I3(b)  the execution profile, its builder/adapter code binding
    gndcrw      I4/I6  the external GNDCRW gate over a BVL-generated manifest
    lockdoc     I5/I7  EII v2, normalized input, preflight record, input.json
    verify      PC/IL  post-create comparison and Input Lock verification (ILV)
    pipeline           validate / check / run / status / resume orchestration

GNDCRW is an external executable. Nothing here imports it, re-implements its
normalization or re-serializes its output.
"""
