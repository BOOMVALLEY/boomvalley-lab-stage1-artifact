"""Locale-aware presentation of human-readable messages.

Business logic raises `message_key + params`; this module turns them into
text. Codes, CLI syntax, JSON members and every machine-readable value stay
English and locale-independent. A missing or broken translation falls back to
en-US and then to the bare key: presentation can never change a verdict.

Locale precedence (first set wins): explicit `--locale` > config > the
GNDCRW_LOCALE environment variable > en-US.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_LOCALE = "en-US"
SUPPORTED_LOCALES = ("en-US", "ko-KR")
LOCALE_ENV = "GNDCRW_LOCALE"

EN_US: dict[str, str] = {
    # CLI usage (exit 2)
    "usage.mixed_mode": "{option}: legacy subject flags cannot be combined with a manifest",
    "usage.option_unknown": "{option}: not a manifest-mode option",
    "usage.option_repeated": "{option} given twice",
    "usage.option_needs_value": "{option} needs a value",
    "usage.option_takes_no_value": "{option} takes no value",
    "usage.argument_count": "expected exactly one manifest, got {count}",
    "usage.stdin": "the manifest must be a file path",
    "usage.format_value": "--format {value!r}: expected text or json",
    "usage.overwrite_without_output": "--overwrite requires --output",
    "usage.capabilities_args": "capabilities takes no arguments",
    "usage.locale_value": "--locale {value!r}: expected one of {supported}",
    # output (exit 6)
    "output.exists": "{path} exists; pass --overwrite",
    "output.write_failed": "cannot write the report: {error}",
    "output.is_manifest": "--output {path} is the manifest",
    "output.is_input": "--output {path} is an input file",
    # manifest parse (exit 3)
    "manifest.yaml": "{name}: YAML is not a manifest carrier",
    "manifest.not_json": "{name}: the manifest file name must end in .json",
    "manifest.too_large": "{size} bytes > {limit}",
    "manifest.bom": "the manifest starts with a byte-order mark",
    "manifest.invalid_utf8": "{error}",
    "manifest.json_error": "{detail}",
    "manifest.too_deep": "nesting deeper than {limit}",
    "manifest.not_object": "the manifest top level must be an object",
    "manifest.version_missing": "manifest_version is required",
    "manifest.version_unsupported": "manifest_version {version!r}; supported: {supported}",
    "manifest.unknown_member": "unknown member {member!r}",
    "manifest.unknown_member_at": "{where}: unknown member {member!r}",
    "manifest.expected_object": "{where}: expected an object",
    "manifest.missing_member": "{where}: missing member {member!r}",
    "manifest.path_invalid": "subjects.{role}.path {path!r}",
    "manifest.field_invalid": "{field}",
    "manifest.size_invalid": "subjects.{role}.size must be an integer 1..{limit}",
    "manifest.duplicate_path": "two roles name the same path",
    # subject references (exit 3)
    "ref.no_such_directory": "{ref}: no such directory",
    "ref.no_such_file": "{ref}: no such file",
    "ref.link": "{ref}: link",
    "ref.link_or_reparse": "{ref}: link or reparse point",
    "ref.link_or_not_directory": "{ref}: link or not a directory",
    "ref.not_directory": "{ref}: not a directory",
    "ref.not_readable": "{ref}: not readable",
    "ref.not_regular_file": "{ref}: not a regular file",
    "ref.cannot_open": "{ref}: cannot open (error {error})",
    "ref.os_error": "{ref}: {error}",
    "ref.case": "{ref}: name differs in case",
    "ref.name_differs": "{ref}: name differs",
    "ref.hardlinks": "{ref}: {links} hard links",
    "ref.alias": "{role}: the same file as another input",
    "ref.size_mismatch": "{role}: declared {declared} bytes, read {read}",
    "ref.digest_mismatch": "{role}: declared {declared}, read {read}",
    "base.cannot_open": "cannot open directory {path}",
    "base.cannot_open_error": "cannot open directory: {error}",
    "platform.no_safe_open": "this platform offers no no-follow, handle-relative open",
    # subjects (exit 3)
    "subject.contract_invalid": "{detail}",
    "external.not_in_surface": "{side}: provenance.input_digests[{scheme!r}] is {recorded!r}, "
                               "not {digest}",
    # internal (exit 5)
    "internal.code_digest": "cannot compute the tool code digest: {error}",
    "internal.unexpected": "{exc_type}: {error}",
    # legacy mode (CLI_SPEC v0.1). `{detail}` is a frozen English v0.1 message (GM-15).
    "legacy.usage": "{detail}",
    "legacy.unknown_command": "unknown command {command!r}",
    "legacy.input_not_found": "{role}: file not found: {path} (D-27.5)",
    "legacy.input_unreadable": "{role}: cannot read {path}: {error} (D-27.5)",
    "legacy.input_invalid": "{detail}",
    "legacy.provider_failed": "{detail}",
    "legacy.output_exists": "{path} exists; pass --overwrite to replace it",
    "legacy.output_write_failed": "cannot write {path}: {error}",
    "legacy.output_is_input": "--output {path} is the --{role} input; refusing to overwrite "
                              "an input",
    "legacy.output_failed": "{detail}",
    "legacy.internal": "{detail}",
}

KO_KR: dict[str, str] = {
    "usage.mixed_mode": "{option}: 레거시 subject 플래그는 manifest와 함께 쓸 수 없습니다",
    "usage.option_unknown": "{option}: manifest 모드에서 지원하지 않는 옵션입니다",
    "usage.option_repeated": "{option} 옵션이 두 번 주어졌습니다",
    "usage.option_needs_value": "{option} 옵션에는 값이 필요합니다",
    "usage.option_takes_no_value": "{option} 옵션은 값을 받지 않습니다",
    "usage.argument_count": "manifest는 정확히 하나여야 합니다 (받은 개수: {count})",
    "usage.stdin": "manifest는 파일 경로여야 합니다",
    "usage.format_value": "--format {value!r}: text 또는 json 이어야 합니다",
    "usage.overwrite_without_output": "--overwrite는 --output과 함께만 쓸 수 있습니다",
    "usage.capabilities_args": "capabilities는 인자를 받지 않습니다",
    "usage.locale_value": "--locale {value!r}: 다음 중 하나여야 합니다: {supported}",
    "output.exists": "{path} 이(가) 이미 있습니다. 덮어쓰려면 --overwrite를 주십시오",
    "output.write_failed": "보고서를 쓸 수 없습니다: {error}",
    "output.is_manifest": "--output {path} 은(는) manifest 자체입니다",
    "output.is_input": "--output {path} 은(는) 입력 파일입니다",
    "manifest.yaml": "{name}: YAML은 manifest 형식이 아닙니다",
    "manifest.not_json": "{name}: manifest 파일 이름은 .json 으로 끝나야 합니다",
    "manifest.too_large": "{size} 바이트 > {limit}",
    "manifest.bom": "manifest가 바이트 순서 표시(BOM)로 시작합니다",
    "manifest.invalid_utf8": "UTF-8이 아닙니다: {error}",
    "manifest.json_error": "JSON 오류: {detail}",
    "manifest.too_deep": "중첩 깊이가 {limit}을(를) 넘습니다",
    "manifest.not_object": "manifest 최상위는 객체여야 합니다",
    "manifest.version_missing": "manifest_version 이 필요합니다",
    "manifest.version_unsupported": "manifest_version {version!r} 은(는) 지원하지 않습니다. "
                                    "지원: {supported}",
    "manifest.unknown_member": "알 수 없는 멤버 {member!r}",
    "manifest.unknown_member_at": "{where}: 알 수 없는 멤버 {member!r}",
    "manifest.expected_object": "{where}: 객체여야 합니다",
    "manifest.missing_member": "{where}: 필수 멤버 {member!r} 이(가) 없습니다",
    "manifest.path_invalid": "subjects.{role}.path {path!r} 은(는) 허용되지 않는 경로입니다",
    "manifest.field_invalid": "{field} 값이 잘못되었습니다",
    "manifest.size_invalid": "subjects.{role}.size 는 1..{limit} 범위의 정수여야 합니다",
    "manifest.duplicate_path": "두 역할이 같은 경로를 가리킵니다",
    "ref.no_such_directory": "{ref}: 디렉터리가 없습니다",
    "ref.no_such_file": "{ref}: 파일이 없습니다",
    "ref.link": "{ref}: 링크입니다",
    "ref.link_or_reparse": "{ref}: 링크 또는 reparse point 입니다",
    "ref.link_or_not_directory": "{ref}: 링크이거나 디렉터리가 아닙니다",
    "ref.not_directory": "{ref}: 디렉터리가 아닙니다",
    "ref.not_readable": "{ref}: 읽을 수 없습니다",
    "ref.not_regular_file": "{ref}: 일반 파일이 아닙니다",
    "ref.cannot_open": "{ref}: 열 수 없습니다 (오류 {error})",
    "ref.os_error": "{ref}: {error}",
    "ref.case": "{ref}: 이름의 대소문자가 다릅니다",
    "ref.name_differs": "{ref}: 이름이 다릅니다",
    "ref.hardlinks": "{ref}: 하드 링크가 {links}개 있습니다",
    "ref.alias": "{role}: 다른 입력과 같은 파일입니다",
    "ref.size_mismatch": "{role}: 선언 {declared} 바이트, 실제 {read} 바이트",
    "ref.digest_mismatch": "{role}: 선언 {declared}, 실제 {read}",
    "base.cannot_open": "디렉터리를 열 수 없습니다: {path}",
    "base.cannot_open_error": "디렉터리를 열 수 없습니다: {error}",
    "platform.no_safe_open": "이 플랫폼은 링크를 따르지 않는 핸들 기준 열기를 제공하지 않습니다",
    "subject.contract_invalid": "subject가 v0.1 계약 검증에 실패했습니다: {detail}",
    "external.not_in_surface": "{side}: provenance.input_digests[{scheme!r}] 값이 {recorded!r} "
                               "이며 {digest} 가 아닙니다",
    "internal.code_digest": "도구 code digest를 계산할 수 없습니다: {error}",
    "internal.unexpected": "예기치 않은 내부 오류 {exc_type}: {error}",
    "legacy.usage": "명령행 사용법이 잘못되었습니다: {detail}",
    "legacy.unknown_command": "알 수 없는 명령 {command!r}",
    "legacy.input_not_found": "{role}: 파일이 없습니다: {path} (D-27.5)",
    "legacy.input_unreadable": "{role}: {path} 을(를) 읽을 수 없습니다: {error} (D-27.5)",
    "legacy.input_invalid": "입력이 v0.1 계약 검증에 실패했습니다: {detail}",
    "legacy.provider_failed": "provider 입력 획득에 실패했습니다: {detail}",
    "legacy.output_exists": "{path} 이(가) 이미 있습니다. 덮어쓰려면 --overwrite를 주십시오",
    "legacy.output_write_failed": "{path} 에 쓸 수 없습니다: {error}",
    "legacy.output_is_input": "--output {path} 은(는) --{role} 입력입니다. 입력을 덮어쓰지 "
                              "않습니다",
    "legacy.output_failed": "보고서를 쓸 수 없습니다: {detail}",
    "legacy.internal": "내부 오류: {detail}",
}

CATALOGS: dict[str, dict[str, str]] = {"en-US": EN_US, "ko-KR": KO_KR}


def translate(key: str, params: Mapping[str, Any] | None = None,
              locale: str = DEFAULT_LOCALE) -> str:
    """Render `key` in `locale`; fall back to en-US, then to the bare key. Never raises."""
    params = dict(params or {})
    for name in dict.fromkeys((locale, DEFAULT_LOCALE)):
        template = CATALOGS.get(name, {}).get(key)
        if template is None:
            continue
        try:
            return template.format_map(params)
        except Exception:  # a broken template is a presentation defect, never a verdict
            continue
    try:
        return key + ("" if not params else " " + repr(sorted(params.items())))
    except Exception:
        return key


def resolve_locale(cli: str | None = None, config: str | None = None,
                   environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    """(locale, source). An explicit CLI value must be supported (the caller checks);
    an unsupported config or environment value is ignored."""
    if cli is not None:
        return cli, "cli"
    if config in SUPPORTED_LOCALES:
        return config, "config"
    env = (environ or {}).get(LOCALE_ENV)
    if env in SUPPORTED_LOCALES:
        return env, "environment"
    return DEFAULT_LOCALE, "default"
