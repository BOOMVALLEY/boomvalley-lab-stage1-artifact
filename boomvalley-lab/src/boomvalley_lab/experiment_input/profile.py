"""The execution profile `bvl-execution-profile-1` and its code binding (§7.2, §15).

    { "schema": "bvl-execution-profile-1",
      "adapter": {"kind": "local", "model_identity": S, "adapter_provenance": S},
      "request_builder": {"id": "boomvalley-lab-record-coordinates-1"} }

    adapter kind "ollama" (a local Ollama server, `runtime/adapters/ollama.py`)
    carries one more member, all of it explicit:

      "adapter": {"kind": "ollama", "model_identity": S, "adapter_provenance": S,
                  "ollama": {"endpoint": "http://127.0.0.1:11434", "model": S,
                             "timeout_seconds": N, "options": {...},
                             "prompt": {"template": S, "system": S}}}   prompt optional

    #146, both optional (absent = the #144 behaviour):
      "seed_strategy": "fixed" | "paired_replicate", "base_seed": N
          paired_replicate: seed = base_seed + replicate (options carries no seed)
      "prompt": {..., "level_blocks": {name: {"factor": F, "levels": {level: S}}}}
          `{name}` in the template takes the record's level text; at `bvl run`
          every block must name a declared factor and cover exactly its levels

    model_identity / adapter_provenance are the identity the run intends
    (`ollama_identity`: "<model>@sha256:<digest>",
    "boomvalley-lab-ollama-1;ollama=<version>"); the server reports what
    actually answered on every call.

    #176: the intended identity must be in the adapter kind's namespace
    (`runtime/adapters/namespace.py`): local -> "boomvalley-lab-local-1" and no
    pinned "@sha256:" model; ollama -> the forms above, <model> = ollama.model.

The profile is the ONLY source of the adapter configuration at run and resume;
no CLI flag contributes. It has no implicit defaults.

`binding` (outside EII, bound through the exact input.json digest) records the
product and the `bvl-code-digest-1` digest of the files that implement the
builder id and the adapter kind, so a resume under different code is refused.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from boomvalley_lab.core.digest import sha256_bytes, sha256_document
from boomvalley_lab.core.versions import PACKAGE_VERSION
from boomvalley_lab.experiment_input.errors import InputRefusal
from boomvalley_lab.runtime.builders import BUILDERS, RECORD_COORDINATES

PROFILE_SCHEMA = "bvl-execution-profile-1"
CODE_DIGEST_METHOD = "bvl-code-digest-1"
PRODUCT_NAME = "boomvalley-lab"

#: IR-08: the files (POSIX, relative to the `boomvalley_lab` package root) that
#: implement each builder id and adapter kind.
CODE_REGISTRY: dict[str, tuple[str, ...]] = {
    f"builder:{RECORD_COORDINATES}": ("runtime/builders.py", "runtime/adapter.py"),
    "adapter:local": ("runtime/adapters/local.py", "runtime/adapter.py"),
    "adapter:ollama": ("runtime/adapters/ollama.py", "runtime/adapter.py"),
}

#: the adapter kinds a profile may name, and the members each one's adapter has
ADAPTER_MEMBERS = {
    "local": frozenset({"kind", "model_identity", "adapter_provenance"}),
    "ollama": frozenset({"kind", "model_identity", "adapter_provenance", "ollama"}),
}
OLLAMA_REQUIRED = frozenset({"endpoint", "model", "timeout_seconds", "options"})
OLLAMA_MEMBERS = OLLAMA_REQUIRED | {"prompt", "seed_strategy", "base_seed"}

#: exactly the code points Python's str.isspace() is true for (§7.2 W)
_W = frozenset(
    [chr(c) for c in (*range(0x09, 0x0E), *range(0x1C, 0x21), 0x85, 0xA0, 0x1680,
                      *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000)]
)


def _refuse(code: str, detail: str, path: str, klass: str = "SCHEMA_ERROR") -> InputRefusal:
    return InputRefusal(klass, code, detail, layer="I3", path=path)


def _non_empty(value: Any) -> bool:
    return (isinstance(value, str) and any(ch not in _W for ch in value)
            and value[0] not in _W and value[-1] not in _W)


def _nulls(value: Any, pointer: str) -> str | None:
    if value is None:
        return pointer
    if isinstance(value, dict):
        for key in sorted(value):
            found = _nulls(value[key], f"{pointer}/{key}")
            if found is not None:
                return found
    if isinstance(value, list):
        for index, item in enumerate(value):
            found = _nulls(item, f"{pointer}/{index}")
            if found is not None:
                return found
    return None


def check_profile(document: Any, selector: str, *, parity: bool = True) -> dict:
    """I3(b), in the fixed order of §20.2.

    `parity` (#176): the adapter's intended identity is in its kind's provenance
    namespace (`runtime.adapters.namespace`) - a local adapter cannot state an
    Ollama provenance or a pinned model digest. The Input Lock verifier reads a
    persisted profile with `parity=False` and reports the same rule as ILV-15,
    under its own code."""
    where = f"{selector}#"
    null_at = _nulls(document, "")
    if null_at is not None:
        raise _refuse("NULL_NOT_ALLOWED", f"null at {null_at or '/'}", f"{selector}#{null_at}")
    if not isinstance(document, dict) or document.get("schema") != PROFILE_SCHEMA:
        raise _refuse("UNSUPPORTED_SCHEMA", f"a profile's schema is {PROFILE_SCHEMA!r}", where)
    if set(document) != {"schema", "adapter", "request_builder"}:
        raise _refuse("PROFILE_UNKNOWN_FIELD", "members are exactly schema, adapter, "
                      f"request_builder (got {sorted(document)})", where)
    adapter, builder = document["adapter"], document["request_builder"]
    kind = adapter.get("kind") if isinstance(adapter, dict) else None
    kind = kind if isinstance(kind, str) else None
    members = ADAPTER_MEMBERS.get(kind, ADAPTER_MEMBERS["local"])
    if not isinstance(adapter, dict) or set(adapter) != members:
        raise _refuse("PROFILE_UNKNOWN_FIELD",
                      f"adapter is exactly {{{', '.join(sorted(members))}}}", where)
    if not isinstance(builder, dict) or set(builder) != {"id"}:
        raise _refuse("PROFILE_UNKNOWN_FIELD", "request_builder is exactly {id}", where)
    if kind not in ADAPTER_MEMBERS:
        raise _refuse("ADAPTER_NOT_IN_V1", f"adapter kind {adapter['kind']!r}", where,
                      klass="OUT_OF_MVP")
    for name in ("model_identity", "adapter_provenance"):
        if not _non_empty(adapter[name]):
            raise _refuse("NON_EMPTY_STRING_INVALID", f"adapter.{name}", where)
    if kind == "ollama":
        _check_ollama(adapter["ollama"], selector)
    if parity:
        from boomvalley_lab.runtime.adapters.namespace import intended_problems

        problems = intended_problems(adapter)
        if problems:
            code, detail = problems[0]
            raise _refuse(code, detail, f"{selector}#/adapter")
    if builder["id"] not in BUILDERS:
        raise _refuse("REQUEST_BUILDER_UNKNOWN", f"request builder {builder['id']!r}", where)
    return document


def _check_ollama(config: Any, selector: str) -> None:
    """The `adapter.ollama` member: every setting explicit, nothing defaulted."""
    from boomvalley_lab.runtime.adapters.ollama import (
        OPTION_NAMES,
        PROMPT_MEMBERS,
        SEED_MAX,
        SEED_STRATEGIES,
        level_block_problems,
    )

    where = f"{selector}#/adapter/ollama"
    if not isinstance(config, dict) or not OLLAMA_REQUIRED <= set(config) <= OLLAMA_MEMBERS:
        raise _refuse("PROFILE_UNKNOWN_FIELD", "adapter.ollama is {endpoint, model, "
                      "timeout_seconds, options} and optionally prompt, seed_strategy, "
                      "base_seed", where)
    for name in ("endpoint", "model"):
        if not _non_empty(config[name]):
            raise _refuse("NON_EMPTY_STRING_INVALID", f"adapter.ollama.{name}", where)
    if not config["endpoint"].startswith(("http://", "https://")):
        raise _refuse("FIELD_INVALID", "adapter.ollama.endpoint is an http(s) URL",
                      where)
    timeout = config["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0:
        raise _refuse("FIELD_INVALID", "adapter.ollama.timeout_seconds is a positive "
                      "number", where)
    options = config["options"]
    if not isinstance(options, dict) or set(options) - OPTION_NAMES or any(
            isinstance(v, bool) or not isinstance(v, int | float) for v in options.values()):
        raise _refuse("FIELD_INVALID", "adapter.ollama.options maps "
                      f"{sorted(OPTION_NAMES)} to numbers", where)
    prompt = config.get("prompt", {})
    if not isinstance(prompt, dict) or set(prompt) - PROMPT_MEMBERS or not all(
            _non_empty(v) for k, v in prompt.items() if k != "level_blocks"):
        raise _refuse("FIELD_INVALID", "adapter.ollama.prompt is {template, system}, "
                      "each a non-empty string, and optionally level_blocks", where)
    if "level_blocks" in prompt:
        problems = level_block_problems(prompt["level_blocks"], prompt.get("template"))
        if problems:
            raise _refuse("FIELD_INVALID", f"adapter.ollama.prompt.level_blocks: {problems[0]}",
                          f"{where}/prompt/level_blocks")
    strategy = config.get("seed_strategy", "fixed")
    if strategy not in SEED_STRATEGIES:
        raise _refuse("FIELD_INVALID", f"adapter.ollama.seed_strategy is one of "
                      f"{list(SEED_STRATEGIES)}", where)
    base_seed = config.get("base_seed")
    if strategy == "paired_replicate":
        if isinstance(base_seed, bool) or not isinstance(base_seed, int) \
                or not 0 <= base_seed <= SEED_MAX:
            raise _refuse("FIELD_INVALID", "seed_strategy paired_replicate needs base_seed, "
                          f"an integer in 0..{SEED_MAX}", where)
        if "seed" in options:
            raise _refuse("FIELD_INVALID", "seed_strategy paired_replicate derives the seed: "
                          "adapter.ollama.options must not carry one", where)
    elif base_seed is not None:
        raise _refuse("FIELD_INVALID", "base_seed belongs to seed_strategy "
                      "paired_replicate only", where)


def level_block_combination(document: Mapping, factors: list[Mapping]) -> str | None:
    """Can this profile's level blocks render every record of `factors`? (None = yes)"""
    config = document["adapter"].get("ollama") or {}
    blocks = (config.get("prompt") or {}).get("level_blocks") or {}
    declared = {factor["name"]: list(factor["levels"]) for factor in factors}
    reserved = {"cell", "replicate", *declared}
    for name, block in sorted(blocks.items()):
        if name in reserved:
            return f"level block {name!r} shadows a request payload member"
        if block["factor"] not in declared:
            return f"level block {name!r} names {block['factor']!r}, which is not a factor"
        if sorted(block["levels"]) != sorted(declared[block["factor"]]):
            return (f"level block {name!r} covers {sorted(block['levels'])}, the factor "
                    f"{block['factor']!r} declares {sorted(declared[block['factor']])}")
    return None


def profile_digest(document: Mapping) -> str:
    return str(sha256_document(document))


def code_digest(key: str) -> str:
    """`bvl-code-digest-1` of the installed files registered for `key`."""
    root = Path(__file__).resolve().parent.parent
    files = [{"path": relative, "sha256": str(sha256_bytes((root / relative).read_bytes()))}
             for relative in sorted(CODE_REGISTRY[key])]
    return str(sha256_document({"files": files}))


def binding(document: Mapping) -> dict:
    """The installation this profile executes under (outside EII)."""
    builder_id = document["request_builder"]["id"]
    return {
        "product": {"name": PRODUCT_NAME, "version": PACKAGE_VERSION},
        "code_digest_method": CODE_DIGEST_METHOD,
        "request_builder": {"id": builder_id, "code_digest": code_digest(f"builder:{builder_id}")},
        "adapter": {"kind": document["adapter"]["kind"],
                    "code_digest": code_digest(f"adapter:{document['adapter']['kind']}")},
    }


def adapter_for(document: Mapping):
    adapter = document["adapter"]
    if adapter["kind"] == "ollama":
        from boomvalley_lab.runtime.adapters.ollama import OllamaAdapter

        config = adapter["ollama"]
        return OllamaAdapter(adapter["model_identity"], adapter["adapter_provenance"],
                             endpoint=config["endpoint"], model=config["model"],
                             timeout_seconds=config["timeout_seconds"],
                             options=config["options"], prompt=config.get("prompt"),
                             seed_strategy=config.get("seed_strategy", "fixed"),
                             base_seed=config.get("base_seed"))
    from boomvalley_lab.runtime.adapters.local import LocalAdapter

    return LocalAdapter(adapter["model_identity"], adapter["adapter_provenance"])


def builder_for(document: Mapping):
    return BUILDERS[document["request_builder"]["id"]]
