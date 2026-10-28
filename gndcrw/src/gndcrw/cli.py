"""`gndcrw` command line (CLI_SPEC v0.1 legacy mode; CLI_SPEC_V0_2 manifest mode).

The CLI acquires inputs, invokes the core and renders the Result Contract. It
does not redefine truth. The process exit code reports whether the tool ran
(§11); with --gate it additionally reports the workflow outcome (§12).

    gndcrw check <manifest.json> [...]      manifest mode, gndcrw-result/v0.2 (normative)
    gndcrw check --declaration F ... [...]  legacy mode, gndcrw-result/v0.1 (compatibility)
    gndcrw capabilities                     machine-readable capability listing

    0   valid VerificationResult produced (any outcome, report mode)
    2   invalid CLI usage
    3   parse / contract-invalid input
    4   provider/adapter acquisition failure
    5   internal GNDCRW runtime error
    6   output/report write failure
    10  --gate and outcome BLOCK
    11  --gate and outcome UNVERIFIABLE

Every refusal prints `gndcrw: error: <CODE>: <detail>` as the first stderr line.
Manifest mode uses the closed CLI_SPEC_V0_2 §5 codes; legacy mode uses
`codes.LEGACY_ERROR_EXIT` (the §5 member where the meaning is the same).

    gndcrw --locale ko-KR <command> ...     human-readable detail in ko-KR (en-US default)

Only the human detail is localized: codes, exit codes, CLI syntax and stdout
are identical in every locale. Locale precedence: leading `--locale` > config
> GNDCRW_LOCALE > en-US. Diagnostics go to the `gndcrw` logger (`gndcrw.log`),
never to stdout; on stderr they follow the error line.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from gndcrw import log
from gndcrw import manifest as manifest_mode
from gndcrw.codes import Error
from gndcrw.core.engine import verify
from gndcrw.core.vocabulary import BLOCK, TOOL_VERSION, UNVERIFIABLE
from gndcrw.errors import CodedError, GndcrwError, InternalError, OutputError, UsageError
from gndcrw.i18n import SUPPORTED_LOCALES, resolve_locale, translate
from gndcrw.jsonio import canonical_json
from gndcrw.load import normalize, read_documents
from gndcrw.render import render_json, render_text

GATE_EXIT = {BLOCK: 10, UNVERIFIABLE: 11}
LEGACY_ROLES = ("declaration", "catalog", "base", "candidate", "pair")
LEGACY_FLAGS = tuple(f"--{role}" for role in LEGACY_ROLES)
MODE_MANIFEST, MODE_LEGACY = "manifest", "legacy"
MANIFEST_OPTIONS = {"--format": True, "--gate": False, "--output": True, "--overwrite": False}
LOCALE_OPTION = "--locale"
LOG = log.get_logger("cli")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # usage errors are exit 2, not a traceback
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="gndcrw", description="Computational experiment preflight.")
    parser.add_argument("--version", action="version", version=f"gndcrw {TOOL_VERSION}")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    check = commands.add_parser("check", help="check one assembled comparison before execution")
    check.add_argument("--declaration", required=True, type=Path)
    check.add_argument("--catalog", required=True, type=Path)
    check.add_argument("--base", required=True, type=Path)
    check.add_argument("--candidate", required=True, type=Path)
    check.add_argument("--pair", required=True, type=Path)
    check.add_argument("--format", choices=("text", "json"), default="text")
    check.add_argument("--gate", action="store_true",
                       help="exit 10 on BLOCK, 11 on UNVERIFIABLE")
    check.add_argument("--output", type=Path, help="write the report here instead of stdout")
    check.add_argument("--overwrite", action="store_true")
    commands.add_parser("capabilities", help="print the machine-readable capability listing")
    return parser


# --------------------------------------------------------------------------- legacy mode

def _write(text: str, output: Path | None, overwrite: bool) -> None:
    # Bytes, not text: the normative JSON must be identical on every platform,
    # so no newline translation (\n -> \r\n on Windows) and no locale encoding.
    data = text.encode("utf-8")
    if output is None:
        sys.stdout.flush()
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return
    try:
        mode = "wb" if overwrite else "xb"
        with output.open(mode) as handle:
            handle.write(data)
    except FileExistsError:
        raise OutputError(code=Error.OUTPUT_EXISTS, message_key="legacy.output_exists",
                          path=output) from None
    except OSError as exc:
        raise OutputError(code=Error.OUTPUT_WRITE_FAILED,
                          message_key="legacy.output_write_failed", path=output,
                          error=exc) from None


def _guard_output(args: argparse.Namespace) -> None:
    """Report writing must never replace an input (CLI §15, D-26.7)."""
    if args.output is None:
        return
    target = args.output.resolve()
    for name in LEGACY_ROLES:
        if getattr(args, name).resolve() == target:
            raise OutputError(code=Error.OUTPUT_IS_INPUT, message_key="legacy.output_is_input",
                              path=args.output, role=name)


def check(args: argparse.Namespace) -> int:
    _guard_output(args)
    docs = read_documents(args.declaration, args.catalog, args.base, args.candidate, args.pair)
    result = verify(normalize(docs))
    text = render_json(result) if args.format == "json" else render_text(result)
    _write(text, args.output, args.overwrite)
    exit_code = GATE_EXIT.get(result["outcome"], 0) if args.gate else 0
    _completed(result, MODE_LEGACY, args.format, args.gate, exit_code)
    return exit_code


def _completed(result: dict, mode: str, fmt: str, gate: bool, exit_code: int) -> None:
    log.event(LOG, logging.INFO, "cli.check_completed", status=result["outcome"], mode=mode,
              result_version=result["result_version"], format=fmt, gate=gate,
              finding_count=len(result["findings"]), exit_code=exit_code)


# --------------------------------------------------------------------------- manifest mode

def _usage(code: Error, message_key: str, **params: object) -> CodedError:
    return CodedError(code, message_key, **params)


def _positionals(tokens: list[str]) -> list[str]:
    """Positional tokens after `check`, skipping option values (legacy prefixes included)."""
    known = (*LEGACY_FLAGS, *MANIFEST_OPTIONS)
    takes_value = {*LEGACY_FLAGS, "--format", "--output"}
    out, skip = [], False
    for token in tokens:
        if skip:
            skip = False
            continue
        if token.startswith("--"):
            name = token.split("=", 1)[0]
            matches = [option for option in known if option.startswith(name)]
            option = name if name in known else (matches[0] if len(matches) == 1 else None)
            skip = option in takes_value and "=" not in token
        elif token == "-" or not token.startswith("-"):
            out.append(token)
    return out


def parse_manifest_args(tokens: list[str]) -> dict:
    """Exact CLI_SPEC_V0_2 §2 parsing: no prefix abbreviation, no repetition, no mixing."""
    options: dict = {}
    positionals: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token.startswith("--"):
            name, eq, value = token.partition("=")
            if any(flag.startswith(name) for flag in LEGACY_FLAGS):
                raise _usage(Error.MIXED_MODE, "usage.mixed_mode", option=name)
            if name not in MANIFEST_OPTIONS:
                raise _usage(Error.OPTION_NOT_SUPPORTED, "usage.option_unknown", option=name)
            if name in options:
                raise _usage(Error.OPTION_REPEATED, "usage.option_repeated", option=name)
            if MANIFEST_OPTIONS[name]:
                if not eq:
                    if index >= len(tokens):
                        raise _usage(Error.OPTION_NOT_SUPPORTED, "usage.option_needs_value",
                                     option=name)
                    value = tokens[index]
                    index += 1
                options[name] = value
            else:
                if eq:
                    raise _usage(Error.OPTION_NOT_SUPPORTED, "usage.option_takes_no_value",
                                 option=name)
                options[name] = True
        elif token.startswith("-") and token != "-":
            raise _usage(Error.OPTION_NOT_SUPPORTED, "usage.option_unknown", option=token)
        else:
            positionals.append(token)
    if len(positionals) != 1:
        raise _usage(Error.MANIFEST_ARGUMENT_COUNT, "usage.argument_count",
                     count=len(positionals))
    if positionals[0] == "-":
        raise _usage(Error.STDIN_NOT_SUPPORTED, "usage.stdin")
    fmt = options.get("--format", "text")
    if fmt not in ("text", "json"):
        raise _usage(Error.OPTION_NOT_SUPPORTED, "usage.format_value", value=fmt)
    if "--overwrite" in options and "--output" not in options:
        raise _usage(Error.OPTION_NOT_SUPPORTED, "usage.overwrite_without_output")
    return {"manifest": Path(positionals[0]), "format": fmt, "gate": "--gate" in options,
            "output": Path(options["--output"]) if "--output" in options else None,
            "overwrite": "--overwrite" in options}


def _write_manifest_mode(text: str, output: Path | None, overwrite: bool) -> None:
    data = text.encode("utf-8")
    try:
        if output is None:
            sys.stdout.flush()
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
            return
        with output.open("wb" if overwrite else "xb") as handle:
            handle.write(data)
    except FileExistsError:
        raise CodedError(Error.OUTPUT_EXISTS, "output.exists", path=output) from None
    except (OSError, AttributeError, ValueError) as exc:
        raise CodedError(Error.OUTPUT_WRITE_FAILED, "output.write_failed", error=exc) from None


def check_manifest(tokens: list[str]) -> int:
    args = parse_manifest_args(tokens)
    path, output = args["manifest"], args["output"]
    if output is not None and output.resolve() == path.resolve():          # guard A
        raise CodedError(Error.OUTPUT_IS_INPUT, "output.is_manifest", path=output)
    manifest_mode.check_suffix(path.name)
    tool_code_digest = manifest_mode.compute_code_digest()
    loaded = manifest_mode.load(path)
    if output is not None and output.exists():                               # guard B
        info = os.stat(output)
        if (info.st_dev, info.st_ino) in loaded.identities:
            raise CodedError(Error.OUTPUT_IS_INPUT, "output.is_input", path=output)
    result = manifest_mode.evaluate(loaded, tool_code_digest)
    text = render_json(result) if args["format"] == "json" else render_text(result)
    _write_manifest_mode(text, output, args["overwrite"])
    exit_code = GATE_EXIT.get(result["outcome"], 0) if args["gate"] else 0
    _completed(result, MODE_MANIFEST, args["format"], args["gate"], exit_code)
    return exit_code


def capabilities(tokens: list[str]) -> int:
    if tokens:
        raise _usage(Error.OPTION_NOT_SUPPORTED, "usage.capabilities_args")
    _write_manifest_mode(canonical_json(manifest_mode.capabilities()) + "\n", None, False)
    return 0


# --------------------------------------------------------------------------- entry

def split_locale(argv: list[str]) -> tuple[str | None, list[str]]:
    """A leading global `--locale X` / `--locale=X`; the subcommand grammars are untouched."""
    if not argv or argv[0].split("=", 1)[0] != LOCALE_OPTION:
        return None, argv
    name, eq, value = argv[0].partition("=")
    rest = argv[1:]
    if not eq:
        if not rest:
            raise _usage(Error.OPTION_NOT_SUPPORTED, "usage.option_needs_value", option=name)
        value, rest = rest[0], rest[1:]
    if value not in SUPPORTED_LOCALES:
        raise _usage(Error.OPTION_NOT_SUPPORTED, "usage.locale_value", value=value,
                     supported=", ".join(SUPPORTED_LOCALES))
    return value, rest


def _stderr(line: str) -> None:
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:  # an unwritable stderr never changes the exit code
        pass


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(list(sys.argv[1:] if argv is None else argv))
    finally:
        log.release()               # held stderr diagnostics follow the error line


def _main(argv: list[str]) -> int:
    log.configure(os.environ)
    locale, source = resolve_locale(None, None, os.environ)
    mode = MODE_MANIFEST            # manifest mode, capabilities and global options
    try:
        explicit, argv = split_locale(argv)
        if explicit is not None:
            locale, source = explicit, "cli"
        log.event(LOG, logging.DEBUG, "cli.started", locale=locale, locale_source=source)
        if argv[:1] == ["check"]:
            tokens = argv[1:]
            has_legacy = any(token.split("=", 1)[0] in LEGACY_FLAGS
                             or any(flag.startswith(token.split("=", 1)[0])
                                    for flag in LEGACY_FLAGS)
                             for token in tokens if token.startswith("--"))
            if _positionals(tokens) or not has_legacy:
                return check_manifest(tokens)
        if argv[:1] == ["capabilities"]:
            return capabilities(argv[1:])
        mode = MODE_LEGACY
        args = build_parser().parse_args(argv)
        if args.command == "check":
            return check(args)
        raise UsageError(message_key="legacy.unknown_command", command=args.command)
    except GndcrwError as exc:      # CodedError (manifest) and the legacy families
        _stderr(f"gndcrw: error: {exc.code}: {exc.render(locale)}")
        role = exc.params.get("role")
        roles = manifest_mode.ROLES if mode == MODE_MANIFEST else LEGACY_ROLES
        log.event(LOG, logging.WARNING, "cli.refused", error=exc.code, exit_code=exc.exit_code,
                  mode=mode, **({"role": role} if role in roles else {}))
        return exc.exit_code
    except Exception as exc:  # an escaped exception is a verifier bug, never a verdict
        detail = translate("internal.unexpected", {"exc_type": type(exc).__name__, "error": exc},
                           locale)
        _stderr(f"gndcrw: error: {Error.INTERNAL_ERROR}: {detail}")
        log.event(LOG, logging.ERROR, "cli.internal_error", error=Error.INTERNAL_ERROR,
                  exit_code=InternalError.exit_code, mode=mode, exc_info=True)
        return InternalError.exit_code


def run() -> None:
    sys.exit(main())
