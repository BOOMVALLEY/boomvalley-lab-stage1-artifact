"""Reading a declaration from disk: JSON, or YAML as a serialization only.

A declaration has one meaning. JSON and YAML are two ways of typing the same
document, and both must produce the *same* Python document, hence the same
canonical bytes, hence the same identities. Anything YAML can express that
JSON cannot is therefore refused rather than interpreted:

    duplicate keys        refused (the last one silently winning is a defect,
                          not a convenience)
    anchors / aliases     refused — evidence is written out, not referenced
    merge keys (<<)       refused (they need aliases anyway)
    yes/no/on/off         refused: only `true` and `false` are booleans; quote
                          the string if that is what you meant
    dates / timestamps    refused: quote it, or use a declared factor level
    non-string keys       refused: a mapping key is a name
    tags (!!set, !!binary…) refused: the declaration model has six types
    several documents     refused: a file declares one experiment

`null` and an omitted key both arrive as "not there", exactly as in JSON: the
canonical form omits None, so the two have one representation (canonical-json-1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boomvalley_lab.core.errors import DeclarationError
from boomvalley_lab.core.strict_json import MalformedJSON, loads

YAML_SUFFIXES = (".yaml", ".yml")
_TYPES = (dict, list, str, int, float, bool)


def read_declaration(path: str | Path) -> Any:
    """The declaration document, whatever format it was typed in."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as error:
        raise DeclarationError(f"cannot read declaration {path}: {error}") from error
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DeclarationError(f"{path} is not UTF-8 text: {error}") from error
    if path.suffix.lower() in YAML_SUFFIXES:
        return _read_yaml(text, path)
    try:
        return loads(text)
    except MalformedJSON as error:
        raise DeclarationError(f"{path} is not readable JSON: {error}") from error


def _read_yaml(text: str, path: Path) -> Any:
    try:
        import yaml
    except ModuleNotFoundError as error:  # pragma: no cover - packaging guard
        raise DeclarationError(
            "YAML input needs the optional `yaml` extra "
            "(pip install 'boomvalley-lab[yaml]'); a JSON declaration needs nothing"
        ) from error

    class StrictLoader(yaml.SafeLoader):
        """YAML restricted to what a declaration document can mean."""

    _restrict(StrictLoader, yaml)
    try:
        documents = list(yaml.load_all(text, Loader=StrictLoader))
    except yaml.YAMLError as error:
        raise DeclarationError(f"{path} is not readable YAML: {error}") from error
    if len(documents) != 1:
        raise DeclarationError(
            f"{path} holds {len(documents)} YAML documents; a file declares one experiment"
        )
    return _only_declaration_types(documents[0], path, "the document")


def _restrict(loader: type, yaml) -> None:
    """Remove the implicit conversions YAML does and JSON does not."""
    resolvers: dict[str, list] = {}
    for character, rules in yaml.SafeLoader.yaml_implicit_resolvers.items():
        kept = [(tag, regexp) for tag, regexp in rules
                if tag not in ("tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:bool")]
        resolvers[character] = kept
    loader.yaml_implicit_resolvers = resolvers
    for character in "tTfF":
        loader.yaml_implicit_resolvers.setdefault(character, [])
        loader.yaml_implicit_resolvers[character] = [
            ("tag:yaml.org,2002:bool", __import__("re").compile(r"^(?:true|false|True|False)$")),
            *loader.yaml_implicit_resolvers[character],
        ]

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise DeclarationError(
                    f"line {key_node.start_mark.line + 1}: a mapping key is a name, got {key!r}"
                )
            if key == "<<":
                raise DeclarationError(
                    f"line {key_node.start_mark.line + 1}: YAML merge keys are not supported; "
                    "write the declaration out"
                )
            if key in mapping:
                raise DeclarationError(
                    f"line {key_node.start_mark.line + 1}: {key!r} is declared twice; a "
                    "declaration may not depend on which one wins"
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping

    loader.construct_mapping = construct_mapping

    def compose_node(self, parent, index):
        event = self.peek_event()
        if isinstance(event, yaml.events.AliasEvent):
            raise DeclarationError(
                f"line {event.start_mark.line + 1}: YAML aliases are not supported; "
                "a declaration says everything it means"
            )
        if getattr(event, "anchor", None) is not None:
            raise DeclarationError(
                f"line {event.start_mark.line + 1}: YAML anchors are not supported"
            )
        return yaml.SafeLoader.compose_node(self, parent, index)

    loader.compose_node = compose_node


def _only_declaration_types(value: Any, path: Path, where: str) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, dict):
        return {key: _only_declaration_types(item, path, f"{where}.{key}")
                for key, item in value.items()}
    if isinstance(value, list):
        return [_only_declaration_types(item, path, f"{where}[{index}]")
                for index, item in enumerate(value)]
    raise DeclarationError(
        f"{path}: {where} is a {type(value).__name__}, which a declaration cannot express "
        f"(allowed: {', '.join(t.__name__ for t in _TYPES)}, null)"
    )
