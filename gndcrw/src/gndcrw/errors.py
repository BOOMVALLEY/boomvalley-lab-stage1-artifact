"""Error families.

GNDCRW keeps three layers apart (VERIFICATION_SEMANTICS §3): input/contract
validity, finding truth, workflow outcome. Only the first layer raises. A
known experiment defect is never an exception - it is a finding.

Each class maps to one CLI exit code (CLI_SPEC §11) and a default registered
code (`gndcrw.codes`); a raise site may name a more precise registered code:

    UsageError        2   USAGE_INVALID      invalid CLI usage
    ContractError     3   INPUT_INVALID      parse / contract-invalid input (no VerificationResult)
    ProviderError     4   PROVIDER_FAILED    provider/adapter acquisition failure
    InternalError     5   INTERNAL_ERROR     an invariant of this code broke
    OutputError       6   OUTPUT_WRITE_FAILED report could not be written

The human detail is `message_key + params` (`gndcrw.i18n`). A raise site
that passes only free text (the frozen v0.1 contract messages, GM-15) gets its
family's key with the text as `detail`. `message` is always the en-US rendering.
"""

from __future__ import annotations

from typing import Any

from gndcrw.codes import ERROR_EXIT, LEGACY_ERROR_EXIT, Error, LegacyError
from gndcrw.i18n import translate


class GndcrwError(Exception):
    exit_code = 5
    code: str = Error.INTERNAL_ERROR
    message_key = "legacy.internal"

    def __init__(self, message: str | None = None, *, code: str | None = None,
                 message_key: str | None = None, **params: Any) -> None:
        if message_key is None:
            message_key, params = type(self).message_key, {"detail": message}
        elif message is None:
            message = translate(message_key, params)
        if code is not None:
            if code not in ERROR_EXIT and code not in LEGACY_ERROR_EXIT:
                raise InternalError(f"unregistered error code {code!r}")
            self.code = code
        super().__init__(message)
        self.message = message
        self.message_key = message_key
        self.params = params

    def render(self, locale: str) -> str:
        return translate(self.message_key, self.params, locale)


class UsageError(GndcrwError):
    exit_code = 2
    code = LegacyError.USAGE_INVALID
    message_key = "legacy.usage"


class ContractError(GndcrwError):
    """An input cannot be interpreted as a valid v0.1 contract object."""

    exit_code = 3
    code = LegacyError.INPUT_INVALID
    message_key = "legacy.input_invalid"

    def __init__(self, message: str | None = None, *, pointer: str = "$",
                 **kwargs: Any) -> None:
        super().__init__(None if message is None else f"{pointer}: {message}", **kwargs)
        self.pointer = pointer


class ProviderError(GndcrwError):
    exit_code = 4
    code = LegacyError.PROVIDER_FAILED
    message_key = "legacy.provider_failed"


class InternalError(GndcrwError):
    exit_code = 5


class OutputError(GndcrwError):
    exit_code = 6
    code = Error.OUTPUT_WRITE_FAILED
    message_key = "legacy.output_failed"


class CodedError(GndcrwError):
    """A manifest-mode failure with a normative code (CLI_SPEC_V0_2 §5).

    Carries a registered `codes.Error`, an i18n `message_key` and its `params`;
    the exit code comes from the registry. `message` is the en-US rendering.
    Printed as the first stderr line `gndcrw: error: <CODE>: <detail>`.
    """

    def __init__(self, code: Error, message_key: str, **params: Any) -> None:
        if code not in ERROR_EXIT:
            raise InternalError(f"unregistered error code {code!r}")
        super().__init__(code=Error(code), message_key=message_key, **params)
        self.exit_code = ERROR_EXIT[self.code]
