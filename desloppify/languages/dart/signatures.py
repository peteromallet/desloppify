"""Declaration-only Dart extraction for signature analysis.

The general Dart extractor also supplies callback bodies to other detectors.
Keep that input unchanged: signature analysis needs actual declared names and
formal parameters, rather than the names and arguments of enclosing calls.
"""

from __future__ import annotations

from pathlib import Path

from desloppify.base.discovery.file_paths import resolve_path
from desloppify.engine.detectors.base import FunctionInfo
from desloppify.languages._framework.base.types import SignatureExtractionUnavailable
from desloppify.languages._framework.treesitter import PARSE_INIT_ERRORS
from desloppify.languages._framework.treesitter.imports.cache import get_or_parse_tree
from desloppify.languages.dart.extractors import find_dart_files

_SIGNATURE_TYPES = {
    "function_signature",
    "constructor_signature",
    "constant_constructor_signature",
    "factory_constructor_signature",
    "setter_signature",
}
_COMMENTS = {"comment", "documentation_comment"}


def _get_parser():
    try:
        from tree_sitter_language_pack import get_parser

        return get_parser("dart")
    except PARSE_INIT_ERRORS as error:
        raise SignatureExtractionUnavailable(
            "Dart signature analysis requires an available tree-sitter Dart grammar."
        ) from error


def _declaration_name(signature) -> str | None:
    if signature.type == "function_signature" or signature.type == "setter_signature":
        name = signature.child_by_field_name("name")
        if name is None:
            name = next(
                (
                    child
                    for child in signature.named_children
                    if child.type == "identifier"
                ),
                None,
            )
        return name.text.decode() if name is not None else None
    identifiers = [
        child.text.decode()
        for child in signature.named_children
        if child.type == "identifier"
    ]
    return ".".join(identifiers) if identifiers else None


def _parameter_name(parameter) -> str | None:
    name = parameter.child_by_field_name("name")
    if name is not None:
        return name.text.decode()
    for child in parameter.named_children:
        if child.type == "identifier":
            # Legacy function-typed parameters name the callback before its
            # nested formal_parameter_list; inner argument names are not ours.
            return child.text.decode()
        if child.type in {"constructor_param", "super_formal_parameter"}:
            identifiers = [
                item for item in child.named_children if item.type == "identifier"
            ]
            if identifiers:
                return identifiers[-1].text.decode()
    return None


def _parameter_names(signature) -> list[str]:
    parameters = signature.child_by_field_name("parameters")
    if parameters is None:
        parameters = next(
            (
                child
                for child in signature.named_children
                if child.type == "formal_parameter_list"
            ),
            None,
        )
    names: list[str] = []
    if parameters is None:
        return names

    def visit(container):
        for child in container.named_children:
            if child.type == "formal_parameter":
                name = _parameter_name(child)
                if name is not None:
                    names.append(name)
            elif child.type == "optional_formal_parameters":
                visit(child)

    visit(parameters)
    return names


def _declarations(root):
    pending = [root]
    while pending:
        node = pending.pop()
        # A recovered ERROR subtree is not evidence of a declaration. Valid
        # siblings remain useful even when unsupported syntax appears elsewhere.
        if node.type == "ERROR":
            continue
        if node.type in _SIGNATURE_TYPES and not node.has_error:
            yield node
        pending.extend(reversed(node.named_children))


def extract_signature_functions(path: Path) -> list[FunctionInfo]:
    """Extract implemented declarations, excluding expressions and callbacks.

    Missing parser support is explicit and never falls back to call-derived
    signatures. The phase records that failure as reduced detector coverage.
    """
    parser = _get_parser()
    functions: list[FunctionInfo] = []
    for filepath in find_dart_files(path):
        absolute = resolve_path(filepath)
        cached = get_or_parse_tree(absolute, parser, "dart")
        if cached is None:
            continue
        source, tree = cached
        for signature in _declarations(tree.root_node):
            name = _declaration_name(signature)
            if name is None:
                continue
            declaration = signature
            if signature.parent.type == "method_signature":
                declaration = signature.parent
            body = declaration.next_named_sibling
            while body is not None and body.type in _COMMENTS:
                body = body.next_named_sibling
            if body is None or body.type != "function_body":
                continue
            line = declaration.start_point[0] + 1
            end_line = body.end_point[0] + 1
            functions.append(
                FunctionInfo(
                    name=name,
                    file=absolute,
                    line=line,
                    end_line=end_line,
                    loc=end_line - line + 1,
                    body=source[declaration.start_byte : body.end_byte].decode(
                        errors="replace"
                    ),
                    params=_parameter_names(signature),
                )
            )
    return functions
