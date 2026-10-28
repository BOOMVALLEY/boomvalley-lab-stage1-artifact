"""An OpenAI-compatible chat-completions provider (T4-010).

    bvl.openai-chat-adapter:1    ADAPTER    one ``POST {endpoint}/chat/completions``
                                            per request-2, over plain HTTP(S)

The provider is a transport and nothing else.  Everything scientific about the
call is already in the request-2 the kernel prepared and persisted before the
intent: the adapter sends exactly that and reports what came back.

    request-2                    wire body
    ---------------------------  ------------------------------------------
    model_identity               ``model``
    messages (role / content)    ``messages``, in order, unchanged
    resolved_seed                ``seed``
    options                      the members of ``OPTIONS`` below, as declared
                                 (``response_format`` as ``{"type": ...}``)
    -                            ``stream: false``, ``n: 1``

Nothing else is sent: a request that carries an option outside ``OPTIONS`` or a
message that is not a role and a content string is refused before any network
event.  The answer is the first (only) choice's message content, returned as
its UTF-8 bytes - the proposal parser the study declares reads it, not this
module.  The model identity is the ``model`` member of the server's answer, so
the kernel's intended-model rule (BVL-ACTOR-007) is decided on the server's own
statement; the adapter provenance is this plugin's identity, with the server's
``system_fingerprint`` when it states one.

Plugin config (the study's ``plugin_config``, bound by digest into the run's
PluginSetIdentity):

    endpoint          the API base, e.g. ``http://127.0.0.1:8080/v1``
    api_key_env       optional: the NAME of the environment variable holding
                      the bearer token.  The token is read at call time, sent
                      as ``Authorization`` and written nowhere.  Over plain
                      http it is accepted for a loopback endpoint only.
    timeout_seconds   optional, default 120

``OPTIONS`` is the plugin's ERF: the profile options that can change execution,
each of which the P09 coverage contract enumerates.  ``require_profile`` holds a
profile to the config and to the option domains before a run exists.

One attempt, no retry, no redirect (a redirect would carry the token to
another host) and no streaming.  Every failure is a ``ProviderError`` with a
closed code and one bounded line: no traceback, no markup, no unbounded server
text, never the token.  Standard library only (``urllib``).
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from boomvalley_lab.core.errors import DeclarationError, ExecutionError
from boomvalley_lab.kernel.adapter2 import ActorResponseV2
from boomvalley_lab.kernel.request import RequestV2

OPENAI_CHAT_ADAPTER = "bvl.openai-chat-adapter:1"
CHAT_PATH = "/chat/completions"
DEFAULT_TIMEOUT_SECONDS = 120
RESPONSE_FORMATS = ("text", "json_object")
CONFIG_MEMBERS = frozenset({"endpoint", "api_key_env", "timeout_seconds"})

UNCONFIGURED = "PROVIDER_UNCONFIGURED"
CREDENTIAL_MISSING = "PROVIDER_CREDENTIAL_MISSING"
REQUEST_UNSUPPORTED = "PROVIDER_REQUEST_UNSUPPORTED"
TIMEOUT = "PROVIDER_TIMEOUT"
UNREACHABLE = "PROVIDER_UNREACHABLE"
HTTP_ERROR = "PROVIDER_HTTP_ERROR"
INVALID_RESPONSE = "PROVIDER_INVALID_RESPONSE"
PROVIDER_CODES = (
    UNCONFIGURED,
    CREDENTIAL_MISSING,
    REQUEST_UNSUPPORTED,
    TIMEOUT,
    UNREACHABLE,
    HTTP_ERROR,
    INVALID_RESPONSE,
)

_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FINGERPRINT = re.compile(r"[A-Za-z0-9_.:\-]{1,64}")
_LOOPBACK_NAMES = frozenset({"localhost"})
_EXCERPT = 160


class ProviderError(ExecutionError):
    """A call that produced no answer. ``reason`` is closed; the message is one line."""

    def __init__(self, reason: str, detail: str) -> None:
        if reason not in PROVIDER_CODES:
            raise ValueError(f"unregistered provider error code {reason!r}")
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


def _number(low: float, high: float, *, open_low: bool = False):
    def check(value: Any) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return (low < value if open_low else low <= value) and value <= high

    return check


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


#: the profile options this provider consumes (its ERF): name -> (domain, check)
OPTIONS: Mapping[str, tuple[str, Any]] = {
    "temperature": ("a number in [0, 2]", _number(0, 2)),
    "top_p": ("a number in (0, 1]", _number(0, 1, open_low=True)),
    "max_tokens": ("a positive integer", _positive_integer),
    "frequency_penalty": ("a number in [-2, 2]", _number(-2, 2)),
    "presence_penalty": ("a number in [-2, 2]", _number(-2, 2)),
    "response_format": (f"one of {list(RESPONSE_FORMATS)}", RESPONSE_FORMATS.__contains__),
}


def option_problems(options: Mapping[str, Any]) -> list[str]:
    """What is wrong with a profile's options for this provider (empty = nothing)."""

    problems = []
    for name in sorted(options):
        if name not in OPTIONS:
            problems.append(f"option {name!r} is not one of {sorted(OPTIONS)}")
            continue
        domain, check = OPTIONS[name]
        value = options[name]
        if not check(value):
            problems.append(f"option {name!r} is {domain}, not {value!r}")
    return problems


def _excerpt(raw: bytes | str) -> str:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    text = " ".join(text.split())
    if text.lstrip().startswith("<"):
        return f"<non-JSON markup, {len(text)} chars>"
    return text if len(text) <= _EXCERPT else text[:_EXCERPT] + "..."


def _server_error(raw: bytes) -> str:
    """The server's own ``{"error": ...}`` text, bounded; else a bounded excerpt."""

    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _excerpt(raw)
    error = document.get("error") if isinstance(document, dict) else None
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return _excerpt(error["message"])
    if isinstance(error, str):
        return _excerpt(error)
    return _excerpt(raw)


def _is_loopback(host: str) -> bool:
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _endpoint(value: Any, *, with_token: bool) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeclarationError(f"{OPENAI_CHAT_ADAPTER} endpoint is a non-empty URL")
    try:
        parts = urllib.parse.urlsplit(value)
        host = parts.hostname
        parts.port  # noqa: B018 - a malformed port raises here
    except ValueError as error:
        raise DeclarationError(f"{OPENAI_CHAT_ADAPTER} endpoint is not a URL: {error}") from None
    if parts.scheme not in ("http", "https") or not host:
        raise DeclarationError(
            f"{OPENAI_CHAT_ADAPTER} endpoint must be an http(s) URL with a host: {value!r}"
        )
    if parts.username is not None or parts.password is not None:
        raise DeclarationError(
            f"{OPENAI_CHAT_ADAPTER} endpoint carries credentials; name the token's "
            "environment variable in api_key_env"
        )
    if parts.query or parts.fragment:
        raise DeclarationError(f"{OPENAI_CHAT_ADAPTER} endpoint has no query or fragment")
    if with_token and parts.scheme == "http" and not _is_loopback(host):
        raise DeclarationError(
            f"{OPENAI_CHAT_ADAPTER} sends a token over plain http to a loopback endpoint "
            f"only; {host!r} needs https"
        )
    return value.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is the server's answer, never a second request."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


@dataclass(frozen=True)
class OpenAIChatAdapterV1:
    """One request-2 -> one chat completion of an OpenAI-compatible server."""

    endpoint: str | None = None
    api_key_env: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    plugin_identity: str = OPENAI_CHAT_ADAPTER

    #: the profile option names the P09 coverage contract enumerates
    ERF: ClassVar[tuple[str, ...]] = tuple(sorted(OPTIONS))
    EXTERNAL_IO: ClassVar[bool] = True
    STOCHASTIC: ClassVar[bool] = True

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> OpenAIChatAdapterV1:
        """The adapter of a study's plugin config; no config is an unconfigured one."""

        if not config:
            return cls()
        unknown = sorted(set(config) - CONFIG_MEMBERS)
        if unknown or "endpoint" not in config:
            raise DeclarationError(
                f"{OPENAI_CHAT_ADAPTER} config is {{'endpoint': URL, 'api_key_env'?: NAME, "
                f"'timeout_seconds'?: seconds}}"
                + (f"; it has {unknown}" if unknown else "; it names no endpoint")
            )
        name = config.get("api_key_env")
        if name is not None and (not isinstance(name, str) or not _ENV_NAME.fullmatch(name)):
            raise DeclarationError(
                f"{OPENAI_CHAT_ADAPTER} api_key_env is the name of an environment variable, "
                "never the token"
            )
        timeout = config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise DeclarationError(f"{OPENAI_CHAT_ADAPTER} timeout_seconds is a positive number")
        return cls(_endpoint(config["endpoint"], with_token=name is not None), name, timeout)

    # -------------------------------------------------------------- pre-run
    def require_profile(self, profile: Any) -> None:
        """Hold an ExecutionProfile to this provider before a run exists."""

        if self.endpoint is None:
            raise DeclarationError(
                f"{UNCONFIGURED}: {OPENAI_CHAT_ADAPTER} has no endpoint; declare it in "
                "plugin_config"
            )
        problems = option_problems(profile.options)
        if problems:
            raise DeclarationError(f"{OPENAI_CHAT_ADAPTER} " + "; ".join(problems))

    # ----------------------------------------------------------------- wire
    def body(self, request: RequestV2) -> dict[str, Any]:
        """The chat-completions body of *request*: request-2 and nothing else."""

        problems = option_problems(request.options)
        if problems:
            raise ProviderError(REQUEST_UNSUPPORTED, "; ".join(problems))
        messages = []
        for message in request.messages:
            if (
                not isinstance(message, Mapping)
                or set(message) != {"role", "content"}
                or not all(isinstance(message[key], str) for key in ("role", "content"))
            ):
                raise ProviderError(
                    REQUEST_UNSUPPORTED, "a message is exactly a role and a content string"
                )
            messages.append({"role": message["role"], "content": message["content"]})
        if not messages:
            raise ProviderError(REQUEST_UNSUPPORTED, "the request carries no message")
        options = dict(request.options)
        if "response_format" in options:
            options["response_format"] = {"type": options["response_format"]}
        return {
            "model": request.model_identity,
            "messages": messages,
            "seed": request.resolved_seed,
            "stream": False,
            "n": 1,
            **options,
        }

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key_env is not None:
            token = os.environ.get(self.api_key_env, "")
            if not token.strip() or any(ch in token for ch in "\r\n"):
                raise ProviderError(
                    CREDENTIAL_MISSING,
                    f"environment variable {self.api_key_env} holds no usable token",
                )
            headers["Authorization"] = f"Bearer {token.strip()}"
        return headers

    def _post(self, body: Mapping[str, Any], headers: Mapping[str, str]) -> Any:
        """One HTTP exchange. Returns the parsed JSON body; raises ProviderError."""

        where = f"POST {CHAT_PATH}"
        exchange = urllib.request.Request(
            f"{self.endpoint}{CHAT_PATH}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers=dict(headers),
        )
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(exchange, timeout=self.timeout_seconds) as reply:
                raw = reply.read()
        except urllib.error.HTTPError as error:
            raw = error.read() if error.fp is not None else b""
            raise ProviderError(
                HTTP_ERROR, f"{where}: HTTP {error.code} ({_server_error(raw)})"
            ) from None
        except TimeoutError:
            raise ProviderError(
                TIMEOUT, f"{where}: no answer within {self.timeout_seconds}s from {self.endpoint}"
            ) from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ProviderError(
                    TIMEOUT,
                    f"{where}: no answer within {self.timeout_seconds}s from {self.endpoint}",
                ) from None
            if isinstance(error.reason, PermissionError):
                raise error.reason from None  # a containment refusal is the kernel's
            raise ProviderError(
                UNREACHABLE,
                f"{where}: cannot reach {self.endpoint} ({type(error.reason).__name__})",
            ) from None
        except PermissionError:
            raise
        except OSError as error:
            raise ProviderError(
                UNREACHABLE, f"{where}: cannot reach {self.endpoint} ({type(error).__name__})"
            ) from None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ProviderError(
                INVALID_RESPONSE, f"{where}: the body is not JSON ({_excerpt(raw)})"
            ) from None

    # ----------------------------------------------------------------- call
    def invoke(self, request: RequestV2) -> ActorResponseV2:
        if self.endpoint is None:
            raise ProviderError(UNCONFIGURED, f"{OPENAI_CHAT_ADAPTER} has no endpoint")
        body = self.body(request)
        answer = self._post(body, self._headers())
        where = f"POST {CHAT_PATH}"
        if not isinstance(answer, dict):
            raise ProviderError(INVALID_RESPONSE, f"{where}: not a JSON object")
        if answer.get("error") is not None:
            raise ProviderError(
                HTTP_ERROR, f"{where}: {_server_error(json.dumps(answer).encode('utf-8'))}"
            )
        choices = answer.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ProviderError(INVALID_RESPONSE, f"{where}: not exactly one choice")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise ProviderError(INVALID_RESPONSE, f"{where}: the choice has no message content")
        finish = choices[0].get("finish_reason")
        if finish != "stop":
            # SV-03: a cut or filtered completion is not the model's answer.  SV-13: nor
            # is one the server does not state finished - null is what an unfinished
            # choice carries, and a cut answer is not told from a whole one by its text
            raise ProviderError(
                INVALID_RESPONSE,
                f"{where}: the completion did not finish (finish_reason {finish!r:.40})",
            )
        model = answer.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ProviderError(INVALID_RESPONSE, f"{where}: the answer names no model")
        fingerprint = answer.get("system_fingerprint")
        stated = isinstance(fingerprint, str) and _FINGERPRINT.fullmatch(fingerprint)
        return ActorResponseV2(
            content=text.encode("utf-8"),
            model_identity=model,
            adapter_provenance=(
                f"{OPENAI_CHAT_ADAPTER};system_fingerprint={fingerprint}"
                if stated
                else OPENAI_CHAT_ADAPTER
            ),
        )
