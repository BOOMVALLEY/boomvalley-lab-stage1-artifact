"""A local Ollama adapter — one real model call per request, over plain HTTP.

    OllamaAdapter(model_identity, adapter_provenance, *, endpoint, model,
                  timeout_seconds, options, prompt)

`model_identity` / `adapter_provenance` are what the runner INTENDS to call
(journaled in the intent). What ANSWERED is read off the server at call time,
for every request, and returned as the actual execution identity:

    model_identity       "<model>@sha256:<digest>"   the digest `/api/tags` lists
                                                     for the requested model
    adapter_provenance   "boomvalley-lab-ollama-1;ollama=<version>"
                                                     `/api/version`

`ollama_identity(model, digest, version)` builds exactly these two strings, so a
profile can pin them (#176: it must - `runtime/adapters/namespace.py`). Before
every `POST /api/chat` the server is resolved and compared with the pinned
identity: another digest or version is refused with `OLLAMA_IDENTITY_MISMATCH`
and no chat is sent (`check_identity`; `bvl run` / `resume` also ask it once
before a run is created or continued). A chat answer that names another model is
recorded as such, and the Input Lock verifier refuses it (ILV-15) - nothing is
corrected, nothing is retried.

The request is one `/api/chat` call, `stream: false`, with exactly the declared
`options` (e.g. temperature 0, a fixed seed, num_ctx <= 4096). The user message
is `prompt.template` with `{name}` replaced by the payload member `name` (the
record's coordinates), or, with no template, the canonical JSON of the payload.
Fixed options make a call repeatable as far as Ollama and the model are — they
do not make it bitwise deterministic across hardware, drivers or versions.

Two opt-in per-record rules (#146); absent, the #144 behaviour is unchanged:

    seed_strategy "fixed"             options.seed (if any) is sent as declared,
                                      for every record (the default)
    seed_strategy "paired_replicate"  seed = base_seed + payload["replicate"]
                                      (`SEED_RULE`); options carries no seed. Every
                                      cell's replicate r gets the same seed, so the
                                      factor arms of replicate r are a
                                      common-random-number pair and replicates differ.

    prompt.level_blocks {name: {"factor": F, "levels": {level: text}}}
                                      `{name}` in the template takes the text for the
                                      record's level of F, so each arm reads only its
                                      own block, never the other levels' text.

The content persisted per record is the canonical JSON of what was sent and
what came back (`RESPONSE_SCHEMA`): endpoint, model, messages, the options sent
(with the resolved seed), how the seed was resolved, the rendered prompt's
digests (and the level each block placeholder took), the resolved digest and
server version, the response text and the server's token counts. Timing
members are left out; they are not part of the answer.

Every failure (timeout, connection, HTTP status, model not found, a body that
is not the expected JSON, an empty answer) is an `OllamaError` with a closed
`code` and a short, single-line message: no traceback, no HTML, no raw server
body beyond a bounded, whitespace-collapsed excerpt.

Standard library only (`urllib`), no provider library. `max_attempts` is 1 and
nothing here retries.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.digest import sha256_bytes, sha256_document
from boomvalley_lab.runtime.adapter import AdapterRequest, AdapterResponse

OLLAMA_PROVENANCE = "boomvalley-lab-ollama-1"
RESPONSE_SCHEMA = "boomvalley-lab-ollama-response-2"
DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_OPTIONS: Mapping[str, Any] = {"temperature": 0, "num_ctx": 4096}

#: the generation options an adapter may send (a closed set: an option the
#: evidence cannot name is not sent)
OPTION_NAMES = frozenset({"temperature", "seed", "num_ctx", "num_predict", "top_k", "top_p",
                          "repeat_penalty"})
PROMPT_MEMBERS = frozenset({"template", "system", "level_blocks"})
SEED_STRATEGIES = ("fixed", "paired_replicate")
#: the one derivation `paired_replicate` uses: an explicit integer sum, never hash()
SEED_RULE = "boomvalley-lab-seed-base-plus-replicate-1"
SEED_MAX = 2**31 - 1

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.-]*)\}")
_EXCERPT = 160


class OllamaError(Exception):
    """A call that did not produce an answer. `code` is closed; the message is
    one line and carries no traceback, HTML or unbounded server text."""

    CODES = ("OLLAMA_TIMEOUT", "OLLAMA_UNREACHABLE", "OLLAMA_HTTP_ERROR",
             "OLLAMA_MODEL_NOT_FOUND", "OLLAMA_INVALID_RESPONSE", "OLLAMA_EMPTY_RESPONSE",
             "OLLAMA_PROMPT_INVALID", "OLLAMA_SEED_INVALID", "OLLAMA_IDENTITY_MISMATCH")

    def __init__(self, code: str, message: str) -> None:
        if code not in self.CODES:
            raise ValueError(f"unregistered Ollama error code {code!r}")
        super().__init__(f"{code}: {message}")
        self.code = code

    def __repr__(self) -> str:
        return f"OllamaError({self.args[0]!r})"


def ollama_identity(model: str, digest: str, version: str) -> dict[str, str]:
    """The execution identity an Ollama server answers with."""
    return {"model_identity": f"{model}@sha256:{digest}",
            "adapter_provenance": f"{OLLAMA_PROVENANCE};ollama={version}"}


def level_block_problems(blocks: Any, template: str | None) -> list[str]:
    """What is wrong with a `prompt.level_blocks` member (empty = nothing)."""
    if not isinstance(blocks, dict) or not blocks:
        return ["level_blocks maps block names to {factor, levels}"]
    if template is None:
        return ["level_blocks needs a template to place the blocks in"]
    placeholders = set(_PLACEHOLDER.findall(template))
    problems = []
    for name, block in sorted(blocks.items()):
        if not _PLACEHOLDER.fullmatch("{" + name + "}"):
            problems.append(f"level block name {name!r} is not a placeholder name")
        elif name not in placeholders:
            problems.append(f"level block {name!r} is not placed in the template")
        if not isinstance(block, dict) or set(block) != {"factor", "levels"} \
                or not isinstance(block["factor"], str) or not block["factor"] \
                or not isinstance(block["levels"], dict) or not block["levels"] \
                or not all(isinstance(level, str) and level and isinstance(text, str)
                           and text.strip() for level, text in block["levels"].items()):
            problems.append(f"level block {name!r} is exactly {{factor, levels}}: a factor "
                            "name and a non-empty text per level")
    return problems


def render_prompt(template: str | None, payload: Mapping[str, Any],
                  level_blocks: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    """The user message for `payload`: the template with `{name}` filled from the
    payload (or, for a level block, with the text for the payload's level of the
    block's factor), or the payload's canonical JSON when there is no template."""
    if template is None:
        return canonical_bytes(dict(payload)).decode("utf-8")
    blocks = level_blocks or {}
    names = set(_PLACEHOLDER.findall(template))
    clash = sorted(names & set(blocks) & set(payload))
    if clash:
        raise OllamaError("OLLAMA_PROMPT_INVALID",
                          f"{clash} name both a level block and a payload member")
    missing = sorted(name for name in names if name not in payload and name not in blocks)
    if missing:
        raise OllamaError("OLLAMA_PROMPT_INVALID",
                          f"the prompt template names {missing}, which the request payload "
                          f"does not carry (it has {sorted(payload)})")
    for name in sorted(names & set(blocks)):
        factor = blocks[name]["factor"]
        if payload.get(factor) not in blocks[name]["levels"]:
            raise OllamaError("OLLAMA_PROMPT_INVALID",
                              f"level block {name!r} has no text for {factor}="
                              f"{payload.get(factor)!r}")

    def fill(match: re.Match) -> str:
        name = match.group(1)
        if name in blocks:
            return blocks[name]["levels"][payload[blocks[name]["factor"]]]
        return str(payload[name])

    return _PLACEHOLDER.sub(fill, template)


def resolve_seed(options: Mapping[str, Any], strategy: str, base_seed: int | None,
                 payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(the options to send, how their seed was resolved) for one record."""
    sent = dict(options)
    if strategy == "fixed":
        return sent, ({"strategy": "fixed", "seed": sent["seed"]} if "seed" in sent
                      else {"strategy": "fixed"})
    replicate = payload.get("replicate")
    if isinstance(replicate, bool) or not isinstance(replicate, int) or replicate < 0:
        raise OllamaError("OLLAMA_SEED_INVALID",
                          "paired_replicate needs an integer payload member 'replicate' "
                          f"(got {replicate!r})")
    seed = base_seed + replicate
    if seed > SEED_MAX:
        raise OllamaError("OLLAMA_SEED_INVALID", f"derived seed {seed} exceeds {SEED_MAX}")
    sent["seed"] = seed
    return sent, {"strategy": "paired_replicate", "rule": SEED_RULE, "base_seed": base_seed,
                  "replicate": replicate, "seed": seed}


def _excerpt(raw: bytes | str) -> str:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    text = " ".join(text.split())
    if text.lstrip().startswith("<"):
        return f"<non-JSON markup, {len(text)} chars>"
    return text if len(text) <= _EXCERPT else text[:_EXCERPT] + "..."


def _server_error(raw: bytes) -> str:
    """The server's own `{"error": ...}` text, bounded; else a bounded excerpt."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _excerpt(raw)
    if isinstance(document, dict) and isinstance(document.get("error"), str):
        return _excerpt(document["error"])
    return _excerpt(raw)


class OllamaAdapter:
    def __init__(self, model_identity: str, adapter_provenance: str, *,
                 model: str, endpoint: str = DEFAULT_ENDPOINT,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                 options: Mapping[str, Any] | None = None,
                 prompt: Mapping[str, Any] | None = None,
                 seed_strategy: str = "fixed", base_seed: int | None = None) -> None:
        options = dict(DEFAULT_OPTIONS if options is None else options)
        unknown = sorted(set(options) - OPTION_NAMES)
        if unknown:
            raise ValueError(f"unsupported Ollama options {unknown} "
                             f"(supported: {sorted(OPTION_NAMES)})")
        prompt = dict(prompt or {})
        if set(prompt) - PROMPT_MEMBERS:
            raise ValueError(f"prompt members are {sorted(PROMPT_MEMBERS)}")
        if "level_blocks" in prompt:
            problems = level_block_problems(prompt["level_blocks"], prompt.get("template"))
            if problems:
                raise ValueError("; ".join(problems))
        if seed_strategy not in SEED_STRATEGIES:
            raise ValueError(f"seed_strategy is one of {list(SEED_STRATEGIES)}")
        if seed_strategy == "paired_replicate":
            if isinstance(base_seed, bool) or not isinstance(base_seed, int) \
                    or not 0 <= base_seed <= SEED_MAX:
                raise ValueError(f"paired_replicate needs a base_seed in 0..{SEED_MAX}")
            if "seed" in options:
                raise ValueError("paired_replicate derives the seed; options must not "
                                 "carry one")
        elif base_seed is not None:
            raise ValueError("base_seed belongs to seed_strategy paired_replicate only")
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError(f"endpoint must be an http(s) URL: {endpoint!r}")
        if not timeout_seconds or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.intended = {"model_identity": model_identity,
                         "adapter_provenance": adapter_provenance}
        self.max_attempts = 1
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.options = options
        self.prompt = prompt
        self.seed_strategy = seed_strategy
        self.base_seed = base_seed

    # ------------------------------------------------------------ transport
    def _http(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        """One HTTP exchange. Returns the parsed JSON body; raises OllamaError."""
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint + path, data=data, method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        where = f"{method} {path}"
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as reply:
                raw = reply.read()
        except urllib.error.HTTPError as error:
            raw = error.read() if error.fp is not None else b""
            text = _server_error(raw)
            if error.code == 404 and "not found" in text.lower():
                raise OllamaError("OLLAMA_MODEL_NOT_FOUND",
                                  f"{where}: model {self.model!r} is not available on "
                                  f"{self.endpoint} ({text})") from None
            raise OllamaError("OLLAMA_HTTP_ERROR",
                              f"{where}: HTTP {error.code} ({text})") from None
        except TimeoutError:
            raise OllamaError("OLLAMA_TIMEOUT", f"{where}: no answer within "
                              f"{self.timeout_seconds}s from {self.endpoint}") from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise OllamaError("OLLAMA_TIMEOUT", f"{where}: no answer within "
                                  f"{self.timeout_seconds}s from {self.endpoint}") from None
            raise OllamaError("OLLAMA_UNREACHABLE", f"{where}: cannot reach {self.endpoint} "
                              f"({_excerpt(str(error.reason))})") from None
        except (ConnectionError, OSError) as error:
            raise OllamaError("OLLAMA_UNREACHABLE", f"{where}: cannot reach {self.endpoint} "
                              f"({type(error).__name__})") from None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise OllamaError("OLLAMA_INVALID_RESPONSE",
                              f"{where}: the body is not JSON ({_excerpt(raw)})") from None

    # ------------------------------------------------------------- identity
    def resolve(self) -> dict[str, str]:
        """{model, digest, version} of what this server would answer with, now."""
        version = self._http("GET", "/api/version")
        if not isinstance(version, dict) or not isinstance(version.get("version"), str) \
                or not version["version"].strip():
            raise OllamaError("OLLAMA_INVALID_RESPONSE", "GET /api/version: no version")
        tags = self._http("GET", "/api/tags")
        models = tags.get("models") if isinstance(tags, dict) else None
        if not isinstance(models, list):
            raise OllamaError("OLLAMA_INVALID_RESPONSE", "GET /api/tags: no models list")
        found = [m for m in models if isinstance(m, dict)
                 and self.model in (m.get("name"), m.get("model"))]
        if not found:
            raise OllamaError("OLLAMA_MODEL_NOT_FOUND",
                              f"model {self.model!r} is not installed on {self.endpoint}")
        digest = found[0].get("digest")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise OllamaError("OLLAMA_INVALID_RESPONSE",
                              f"GET /api/tags: model {self.model!r} has no sha256 digest")
        return {"model": self.model, "digest": digest, "version": version["version"]}

    def check_identity(self) -> dict[str, str]:
        """#176 (BVVH #174 MINOR-1): resolve the server, and refuse - before any
        `POST /api/chat` - when what it would answer with is not the pinned intended
        identity (`OLLAMA_IDENTITY_MISMATCH`). Returns the resolved {model, digest,
        version}. The server's own statement is all this reads (NE-1)."""
        resolved = self.resolve()
        found = ollama_identity(resolved["model"], resolved["digest"], resolved["version"])
        if found != self.intended:
            raise OllamaError("OLLAMA_IDENTITY_MISMATCH",
                              f"the server resolves {found['model_identity']} / "
                              f"{found['adapter_provenance']}; the profile pins "
                              f"{self.intended['model_identity']} / "
                              f"{self.intended['adapter_provenance']}")
        return resolved

    # ----------------------------------------------------------------- call
    def messages(self, payload: Mapping[str, Any]) -> list[dict[str, str]]:
        messages = []
        if self.prompt.get("system"):
            messages.append({"role": "system", "content": self.prompt["system"]})
        messages.append({"role": "user",
                         "content": render_prompt(self.prompt.get("template"), payload,
                                                  self.prompt.get("level_blocks"))})
        return messages

    def prompt_facts(self, payload: Mapping[str, Any],
                     messages: list[dict[str, str]]) -> dict[str, Any]:
        """The rendered prompt's digests, and the level each block placeholder took."""
        facts: dict[str, Any] = {
            "messages_digest": str(sha256_document(messages)),
            "user_digest": str(sha256_bytes(messages[-1]["content"].encode("utf-8")))}
        blocks = self.prompt.get("level_blocks") or {}
        if blocks:
            facts["level_blocks"] = {
                name: {"factor": block["factor"], "level": payload[block["factor"]],
                       "digest": str(sha256_bytes(
                           block["levels"][payload[block["factor"]]].encode("utf-8")))}
                for name, block in sorted(blocks.items())}
        return facts

    def call(self, request: AdapterRequest) -> AdapterResponse:
        messages = self.messages(request.payload)
        options, seed = resolve_seed(self.options, self.seed_strategy, self.base_seed,
                                     request.payload)
        prompt = self.prompt_facts(request.payload, messages)
        resolved = self.check_identity()           # #176: no chat under another identity
        answer = self._http("POST", "/api/chat", {
            "model": self.model, "messages": messages, "stream": False,
            "options": options})
        if not isinstance(answer, dict):
            raise OllamaError("OLLAMA_INVALID_RESPONSE", "POST /api/chat: not a JSON object")
        if isinstance(answer.get("error"), str):
            raise OllamaError("OLLAMA_HTTP_ERROR",
                              f"POST /api/chat: {_excerpt(answer['error'])}")
        message = answer.get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise OllamaError("OLLAMA_INVALID_RESPONSE", "POST /api/chat: no message content")
        if not text.strip():
            raise OllamaError("OLLAMA_EMPTY_RESPONSE", "POST /api/chat: the answer is empty")
        answered = answer.get("model") if isinstance(answer.get("model"), str) else None
        identity = ollama_identity(answered or self.model, resolved["digest"],
                                   resolved["version"])
        document = {
            "schema": RESPONSE_SCHEMA,
            "record": request.record,
            "request": {"endpoint": self.endpoint, "model": self.model,
                        "messages": messages, "options": options, "seed": seed,
                        "prompt": prompt},
            "resolved": resolved,
            "response": {
                "text": text,
                "model": answered or "",
                **{name: answer[name] for name in ("done_reason", "prompt_eval_count",
                                                   "eval_count")
                   if isinstance(answer.get(name), (str, int))
                   and not isinstance(answer.get(name), bool)},
            },
        }
        return AdapterResponse(
            content=canonical_bytes(document),
            model_identity=identity["model_identity"],
            adapter_provenance=identity["adapter_provenance"],
            metadata={"adapter": "ollama", "endpoint": self.endpoint,
                      "ollama_version": resolved["version"], "model_digest": resolved["digest"],
                      "options": options, "seed": seed, "prompt": prompt},
        )
