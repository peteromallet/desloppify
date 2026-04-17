"""Shared Rust detector helpers and parsing utilities."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desloppify.base.discovery.file_paths import rel, resolve_path
from desloppify.languages.rust import tools as rust_tools
from desloppify.languages.rust.support import (
    describe_rust_file,
    find_rust_files,
    read_text_or_none,
    strip_rust_comments,
)

_USE_STATEMENT_RE = re.compile(
    r"(?ms)^\s*(?:pub(?:\([^)]*\))?\s+)?use\s+(.+?);"
)
_PUB_FN_RE = re.compile(
    r'(?m)^\s*pub\s+(?:(?:async|const|unsafe)\s+)*(?:extern\s+"[^"]+"\s+)?fn\s+([A-Za-z_]\w*)\b'
)
_ASYNC_FN_RE = re.compile(
    r'(?m)^\s*(?:pub(?:\([^)]*\))?\s+)?(?:(?:const|unsafe)\s+)*(?:extern\s+"[^"]+"\s+)?async\s+fn\s+([A-Za-z_]\w*)\b'
)
_PUBLIC_TYPE_RE = re.compile(
    r"(?m)^\s*pub\s+(struct|enum)\s+([A-Za-z_]\w*)\b"
)
_DROP_IMPL_RE = re.compile(r"(?m)^\s*impl(?:\s*<[^>{}]+>)?\s+Drop\s+for\s+([A-Za-z_]\w*)\b")
_DROP_FN_RE = re.compile(r"(?m)^\s*fn\s+drop\s*\(\s*&mut\s+self\b")
_FEATURE_REF_RE = re.compile(r'feature\s*=\s*"([^"\n]+)"')
_README_RUST_FENCE_RE = re.compile(
    r"(?ms)^```(?:rust|no_run|ignore|compile_fail|should_panic)\b.*?^```"
)
_RUST_DOC_FENCE_ALLOWED_TAGS = {"", "rust", "no_run", "ignore", "compile_fail", "should_panic"}
_GETTER_RE = re.compile(r"^get_[A-Za-z_]\w*$")
_INTO_RE = re.compile(r"^into_[A-Za-z_]\w*$")
_WRAPPER_GETTER_NAMES = {"get_ref", "get_mut"}
_PUBLIC_ERROR_RE = re.compile(
    r"\b(?:anyhow|eyre|color_eyre)::Result\b"
    r"|Box\s*<\s*dyn\s+(?:std::error::)?Error\b"
    r"|Result\s*<[^>]*\b(?:anyhow|eyre|color_eyre)::Error\b",
    re.DOTALL,
)
_NON_EXHAUSTIVE_RE = re.compile(r"#\s*\[\s*non_exhaustive\s*\]")
_PUBLIC_FIELD_RE = re.compile(r"(?m)^\s*pub\s+[A-Za-z_]\w*\s*:")
_PUBLIC_FIELD_DECL_RE = re.compile(r"(?m)^\s*pub\s+([A-Za-z_]\w*)\s*:\s*([^,\n]+)")
_ENUM_VARIANT_RE = re.compile(r"(?m)^\s*[A-Z][A-Za-z0-9_]*\s*(?:\(|\{|,)")
_THREAD_ASSERT_RE = re.compile(
    r"\b(?:Send|Sync|assert_send|assert_sync|assert_impl_all|static_assertions)\b"
)
_STD_SYNC_LOCK_IMPORT_RE = re.compile(
    r"\bstd::sync::(?:Mutex|RwLock)\b"
    r"|use\s+std::sync::(?:Mutex|RwLock)\b"
    r"|use\s+std::sync::\{[^}]*\b(?:Mutex|RwLock)\b",
    re.DOTALL,
)
_BLOCKING_LOCK_CALL_RE = re.compile(r"\.\s*(?:lock|read|write)\s*\(\s*\)(?!\s*\.await)")
_AWAIT_RE = re.compile(r"\bawait\b")
_STD_GUARD_ACQUIRE_RE = re.compile(
    r"\blet\s+(?:mut\s+)?(?P<guard>[A-Za-z_]\w*)\s*=\s*.*?"
    r"\.\s*(?:lock|read|write)\s*\(\s*\)\s*"
    r"(?:\.\s*(?:unwrap|expect)\s*\([^)]*\)|\?)\s*;",
    re.DOTALL,
)
_ASYNC_GUARD_ACQUIRE_RE = re.compile(
    r"\blet\s+(?:mut\s+)?(?P<guard>[A-Za-z_]\w*)\s*=\s*.*?"
    r"\.\s*(?:lock|read|write)\s*\(\s*\)\s*\.await\s*;",
    re.DOTALL,
)
_DROP_PANIC_RE = re.compile(r"\bpanic!\s*\(")
_DROP_UNWRAP_RE = re.compile(r"\.\s*(?:unwrap|expect)\s*\(")
_INFALLIBLE_LAYOUT_UNWRAP_RE = re.compile(
    r"Layout::from_size_align\(\s*[^,\n]+\s*,\s*(?:1|2|4|8|16|32|64|128|256|512|1024)\s*\)"
    r"\s*\.\s*(?:unwrap|expect)\s*\([^)]*\)"
)
_SAFETY_COMMENT_RE = re.compile(r"(?i)\bsafety\s*:")
_UTF8_RATIONALE_RE = re.compile(
    r"(?i)(valid(?:ated)? utf-?8|invalid utf-?8|utf-?8 guarantee)"
)
_VEC_REBUILD_RATIONALE_RE = re.compile(
    r"(?i)(safely reconstruct a vec|without leaking memory|rebuild vec)"
)
_REPR_TRANSPARENT_STRUCT_RE = re.compile(
    r"(?ms)#\s*\[\s*repr\s*\(\s*transparent\s*\)\s*\]\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)\b"
)
_UNSAFE_API_PATTERNS: tuple[tuple[str, re.Pattern[str], str, int, str], ...] = (
    (
        "transmute",
        re.compile(r"\b(?:std::mem::|mem::)?transmute(?:\s*::\s*<[^>]+>)?\s*\("),
        "Rust code uses `transmute`; prefer a checked conversion or document the layout invariants locally",
        3,
        "high",
    ),
    (
        "unreachable_unchecked",
        re.compile(r"\b(?:std::hint::|core::hint::)?unreachable_unchecked\s*\("),
        "Rust code uses `unreachable_unchecked`; this is UB if reached and needs airtight invariants",
        3,
        "high",
    ),
    (
        "unwrap_unchecked",
        re.compile(r"\.\s*unwrap_unchecked\s*\("),
        "Rust code uses `unwrap_unchecked`; keep it behind a proven invariant or replace it with checked handling",
        3,
        "high",
    ),
    (
        "from_utf8_unchecked",
        re.compile(r"\b(?:std::str::|std::string::String::)?from_utf8_unchecked\s*\("),
        "Rust code uses `from_utf8_unchecked`; prefer checked UTF-8 decoding unless invariants are explicit",
        2,
        "high",
    ),
    (
        "get_unchecked",
        re.compile(r"\.\s*get_unchecked(?:_mut)?\s*\("),
        "Rust code uses unchecked indexing; prove the bounds locally or switch to checked access",
        2,
        "high",
    ),
    (
        "from_raw_parts",
        re.compile(
            r"\b(?:std::slice::|core::slice::|slice::|Vec::|std::vec::Vec::|alloc::vec::Vec::)"
            r"from_raw_parts(?:_mut)?\s*\("
            r"|(?<!::)\bfrom_raw_parts(?:_mut)?\s*\("
        ),
        "Rust code builds slices from raw parts; validate pointer, length, and aliasing invariants close to the call",
        3,
        "high",
    ),
    (
        "zeroed",
        re.compile(r"\b(?:std::mem::|core::mem::|mem::)zeroed(?:::<[^>]+>)?\s*\("),
        "Rust code uses `mem::zeroed`; replace it with a safe initializer unless all-zero bytes are guaranteed valid",
        3,
        "high",
    ),
    (
        "uninitialized",
        re.compile(
            r"\b(?:std::mem::|core::mem::|mem::)uninitialized(?:::<[^>]+>)?\s*\("
        ),
        "Rust code uses `mem::uninitialized`; replace it with `MaybeUninit` and explicit initialization",
        3,
        "high",
    ),
)


@dataclass(frozen=True)
class PublicFnBlock:
    """Best-effort extracted Rust public function or method block."""

    name: str
    line: int
    attrs: str
    signature: str
    body: str
    receiver: str | None


@dataclass(frozen=True)
class FunctionBlock:
    """Best-effort extracted Rust function block."""

    name: str
    line: int
    attrs: str
    signature: str
    body: str


@dataclass(frozen=True)
class PublicTypeBlock:
    """Best-effort extracted Rust public type block."""

    kind: str
    name: str
    line: int
    attrs: str
    preamble: str
    body: str


def _group_files_by_manifest(path: Path) -> dict[Path, list[str]]:
    grouped: dict[Path, list[str]] = {}
    for filepath in find_rust_files(path):
        absolute = Path(resolve_path(filepath))
        context = describe_rust_file(absolute)
        grouped.setdefault(context.manifest_dir, []).append(filepath)
    return grouped


def _declared_features(manifest_path: Path) -> set[str]:
    text = read_text_or_none(manifest_path)
    if text is None:
        return set()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return set()
    declared: set[str] = set()
    features = data.get("features")
    if isinstance(features, dict):
        declared.update(str(name) for name in features)
    for section_name in (
        "dependencies",
        "build-dependencies",
        "target",
        "workspace.dependencies",
    ):
        declared.update(_optional_dependency_features(data, section_name))
    target = data.get("target")
    if isinstance(target, dict):
        for section in target.values():
            if not isinstance(section, dict):
                continue
            for dependency_group in ("dependencies", "build-dependencies"):
                declared.update(_optional_dependency_features(section, dependency_group))
    return declared


def _is_internal_module(context) -> bool:
    try:
        relative = context.source_file.relative_to(context.manifest_dir)
    except ValueError:
        return False
    parts = relative.parts
    if not parts:
        return False
    if parts[0] != "src":
        return False
    if relative == Path("src/main.rs"):
        return False
    if parts[:2] == ("src", "bin"):
        return False
    return True


def _is_library_api_file(context) -> bool:
    return _is_internal_module(context) and (context.manifest_dir / "src" / "lib.rs").is_file()


def _is_runtime_source_file(context) -> bool:
    try:
        relative = context.source_file.relative_to(context.manifest_dir)
    except ValueError:
        return False
    parts = relative.parts
    return bool(parts) and parts[0] == "src"


def _iter_public_functions(content: str) -> list[PublicFnBlock]:
    blocks: list[PublicFnBlock] = []
    for match in _PUB_FN_RE.finditer(content):
        body_start = _find_block_start(content, match.end())
        if body_start is None:
            continue
        body_end = _find_matching_brace(content, body_start)
        if body_end is None:
            continue
        attrs = _preceding_metadata(content, match.start())
        signature = content[match.start() : body_start].strip()
        body = content[body_start : body_end + 1]
        blocks.append(
            PublicFnBlock(
                name=match.group(1),
                line=_line_number(content, match.start()),
                attrs=attrs,
                signature=signature,
                body=body,
                receiver=_receiver_from_signature(signature),
            )
        )
    return blocks


def _iter_async_functions(content: str) -> list[FunctionBlock]:
    blocks: list[FunctionBlock] = []
    for match in _ASYNC_FN_RE.finditer(content):
        body_start = _find_block_start(content, match.end())
        if body_start is None:
            continue
        body_end = _find_matching_brace(content, body_start)
        if body_end is None:
            continue
        blocks.append(
            FunctionBlock(
                name=match.group(1),
                line=_line_number(content, match.start()),
                attrs=_preceding_metadata(content, match.start()),
                signature=content[match.start() : body_start].strip(),
                body=content[body_start : body_end + 1],
            )
        )
    return blocks


def _iter_public_types(content: str) -> list[PublicTypeBlock]:
    blocks: list[PublicTypeBlock] = []
    for match in _PUBLIC_TYPE_RE.finditer(content):
        body_start = _find_block_start(content, match.end())
        if body_start is None:
            continue
        body_end = _find_matching_brace(content, body_start)
        if body_end is None:
            continue
        preamble = _preceding_metadata(content, match.start())
        blocks.append(
            PublicTypeBlock(
                kind=match.group(1),
                name=match.group(2),
                line=_line_number(content, match.start()),
                attrs=_preceding_attributes(content, match.start()),
                preamble=preamble,
                body=content[body_start + 1 : body_end],
            )
        )
    return blocks


def _iter_drop_methods(content: str) -> list[tuple[str, int, str]]:
    methods: list[tuple[str, int, str]] = []
    function_spans = _function_body_spans(content)
    for match in _DROP_IMPL_RE.finditer(content):
        if _offset_within_spans(match.start(), function_spans):
            continue
        impl_body_start = _find_block_start(content, match.end())
        if impl_body_start is None:
            continue
        impl_body_end = _find_matching_brace(content, impl_body_start)
        if impl_body_end is None:
            continue

        type_name = match.group(1)
        impl_body = content[impl_body_start + 1 : impl_body_end]
        for drop_match in _DROP_FN_RE.finditer(impl_body):
            method_body_start = _find_block_start(impl_body, drop_match.end())
            if method_body_start is None:
                continue
            method_body_end = _find_matching_brace(impl_body, method_body_start)
            if method_body_end is None:
                continue
            absolute_start = impl_body_start + 1 + drop_match.start()
            methods.append(
                (
                    type_name,
                    _line_number(content, absolute_start),
                    impl_body[method_body_start : method_body_end + 1],
                )
            )
    return methods


def _has_readme_doctest_harness(content: str) -> bool:
    return 'include_str!("../README.md")' in content or "cfg(doctest)" in content


def _has_inline_rust_doc_examples(content: str) -> bool:
    in_fence = False
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not (stripped.startswith("///") or stripped.startswith("//!")):
            continue
        payload = stripped[3:].strip()
        if not payload.startswith("```"):
            continue
        if in_fence:
            in_fence = False
            continue
        tag = payload[3:].strip()
        if _is_rust_doc_fence_tag(tag):
            return True
        in_fence = True
    return False


def _is_test_content(filepath: Path, content: str) -> bool:
    normalized = rel(filepath)
    return normalized.startswith("tests/") or "#[cfg(test)]" in content or "#[test]" in content


def _receiver_from_signature(signature: str) -> str | None:
    open_index = signature.find("(")
    if open_index == -1:
        return None
    close_index = _find_matching_delimiter(signature, open_index, "(", ")")
    if close_index is None:
        return None
    params = signature[open_index + 1 : close_index]
    first = params.split(",", 1)[0].strip()
    return first or None


def _starts_with_same_crate_import(statement: str, crate_name: str) -> bool:
    normalized = statement.lstrip()
    return normalized == crate_name or normalized.startswith(f"{crate_name}::")


def _function_body_spans(content: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"\bfn\s+[A-Za-z_]\w*\b", content):
        body_start = _find_block_start(content, match.end())
        if body_start is None:
            continue
        body_end = _find_matching_brace(content, body_start)
        if body_end is None:
            continue
        spans.append((body_start, body_end))
    return spans


def _offset_within_spans(offset: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= offset <= end for start, end in spans)


def _find_block_start(content: str, index: int) -> int | None:
    paren_depth = 0
    bracket_depth = 0
    angle_depth = 0
    cursor = index
    while cursor < len(content):
        char = content[cursor]
        if content.startswith("//", cursor):
            cursor = rust_tools._line_end(content, cursor)
            continue
        if content.startswith("/*", cursor):
            cursor = rust_tools._block_comment_end(content, cursor)
            continue
        if char == '"':
            cursor = rust_tools._quoted_string_end(content, cursor, '"')
            continue
        if char == "'" and rust_tools._looks_like_char_literal_start(content, cursor):
            cursor = rust_tools._quoted_string_end(content, cursor, "'")
            continue
        if char == "r" and rust_tools._looks_like_raw_string_start(content, cursor):
            cursor = rust_tools._raw_string_end(content, cursor)
            continue
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth = max(0, paren_depth - 1)
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif char == "<":
            angle_depth += 1
        elif char == ">":
            angle_depth = max(0, angle_depth - 1)
        elif char == ";" and paren_depth == bracket_depth == angle_depth == 0:
            return None
        elif char == "{" and paren_depth == bracket_depth == angle_depth == 0:
            return cursor
        cursor += 1
    return None


def _find_matching_brace(text: str, start_index: int) -> int | None:
    return rust_tools._find_matching_delimiter(text, start_index, "{", "}")


def _find_matching_delimiter(text: str, start_index: int, opening: str, closing: str) -> int | None:
    return rust_tools._find_matching_delimiter(text, start_index, opening, closing)


def _preceding_attributes(content: str, start: int) -> str:
    return "\n".join(
        line
        for line in _preceding_metadata(content, start).splitlines()
        if line.strip().startswith("#[")
    )


def _preceding_metadata(content: str, start: int) -> str:
    lines = content[:start].splitlines()
    attrs: list[str] = []
    index = len(lines) - 1
    while index >= 0:
        stripped = lines[index].strip()
        if not stripped:
            if attrs:
                break
            index -= 1
            continue
        if stripped.startswith("#[") or stripped.startswith("///") or stripped.startswith("//!"):
            attrs.append(stripped)
            index -= 1
            continue
        break
    return "\n".join(reversed(attrs))


def _optional_dependency_features(data: dict, section_name: str) -> set[str]:
    section = data.get(section_name)
    if not isinstance(section, dict):
        return set()
    features: set[str] = set()
    for dep_name, dep_value in section.items():
        if isinstance(dep_value, dict) and dep_value.get("optional") is True:
            features.add(str(dep_name))
    return features


def _has_python_binding_attrs(attrs: str) -> bool:
    return any(token in attrs for token in ("#[getter", "#[setter", "#[pymethods", "#[pyfunction"))


def _argument_count(signature: str) -> int:
    open_index = signature.find("(")
    if open_index == -1:
        return 0
    close_index = _find_matching_delimiter(signature, open_index, "(", ")")
    if close_index is None:
        return 0
    params = [chunk.strip() for chunk in signature[open_index + 1 : close_index].split(",")]
    return len([param for param in params if param])


def _looks_like_plain_getter(block: PublicFnBlock) -> bool:
    return block.receiver in {"&self", "&mut self"} and _argument_count(block.signature) == 1


def _has_public_panic_path(body: str) -> bool:
    stripped = strip_rust_comments(body)
    if re.search(r"\b(?:panic|todo|unimplemented)!\s*\(", stripped):
        return True
    return bool(re.search(r"\.\s*(?:lock|read|write)\s*\(\)\s*\.\s*(?:unwrap|expect)\s*\(", stripped))


def _should_skip_future_proofing(content: str, block: PublicTypeBlock) -> bool:
    preamble = block.preamble.lower()
    attrs = block.attrs.lower()
    if any(token in attrs for token in ("repr(c)", "non_exhaustive", "pyclass", "doc(hidden)")):
        return True
    if any(token in preamble for token in ("unstable", "internal", "not part of the stable api")):
        return True
    if _looks_like_public_error_type(content, block.name):
        return True
    if block.kind == "struct" and _looks_like_small_scalar_record(block.body):
        return True
    if block.kind == "enum" and _has_doc_comments(block.preamble):
        return True
    return False


def _looks_like_ffi_surface(block: PublicTypeBlock) -> bool:
    attrs = block.attrs.lower()
    return "repr(c)" in attrs or "no_mangle" in attrs


def _has_manual_thread_contract(content: str, type_name: str) -> bool:
    return bool(
        re.search(
            rf"unsafe\s+impl(?:\s*<[^>]+>)?\s+(?:Send|Sync)\s+for\s+{re.escape(type_name)}\b",
            content,
        )
    )


def _has_thread_assertion(corpus: str, type_name: str) -> bool:
    if type_name not in corpus:
        return False
    if not _THREAD_ASSERT_RE.search(corpus):
        return False
    return bool(
        re.search(rf"\b{re.escape(type_name)}\b.*\b(?:Send|Sync)\b", corpus, re.DOTALL)
        or re.search(rf"\b(?:Send|Sync)\b.*\b{re.escape(type_name)}\b", corpus, re.DOTALL)
    )


def _uses_std_sync_locks(content: str) -> bool:
    stripped = strip_rust_comments(content)
    return bool(_STD_SYNC_LOCK_IMPORT_RE.search(stripped))


def _looks_like_public_error_type(content: str, type_name: str) -> bool:
    if not type_name.endswith("Error"):
        return False
    display_impl = re.search(
        rf"impl(?:\s*<[^>]+>)?\s+(?:core::fmt::Display|std::fmt::Display)\s+for\s+{re.escape(type_name)}\b",
        content,
    )
    error_impl = re.search(
        rf"impl(?:\s*<[^>]+>)?\s+(?:std::error::Error|core::error::Error)\s+for\s+{re.escape(type_name)}\b",
        content,
    )
    return bool(display_impl or error_impl)


def _has_fallible_drop_unwrap(body: str) -> bool:
    sanitized = _INFALLIBLE_LAYOUT_UNWRAP_RE.sub("layout_ok()", body)
    return bool(_DROP_UNWRAP_RE.search(sanitized))


def _is_rust_doc_fence_tag(tag: str) -> bool:
    normalized = tag.strip()
    if not normalized:
        return True
    head = re.split(r"[\s,]", normalized, maxsplit=1)[0]
    return head in _RUST_DOC_FENCE_ALLOWED_TAGS


def _looks_like_small_scalar_record(body: str) -> bool:
    fields = list(_PUBLIC_FIELD_DECL_RE.findall(body))
    if not 2 <= len(fields) <= 3:
        return False
    return all(_is_scalar_public_field_type(field_type) for _, field_type in fields)


def _is_scalar_public_field_type(field_type: str) -> bool:
    normalized = re.sub(r"\s+", "", field_type)
    return normalized in {
        "bool",
        "char",
        "usize",
        "isize",
        "u8",
        "u16",
        "u32",
        "u64",
        "u128",
        "i8",
        "i16",
        "i32",
        "i64",
        "i128",
        "f32",
        "f64",
    }


def _has_doc_comments(metadata: str) -> bool:
    return "///" in metadata or "//!" in metadata


def _should_skip_unsafe_api_match(detector_name: str, content: str, offset: int) -> bool:
    if _looks_like_function_definition_token(content, offset):
        return True
    if _has_local_safety_rationale(content, offset):
        return True
    if detector_name == "transmute" and _looks_like_repr_transparent_cast(content, offset):
        return True
    if detector_name == "from_raw_parts" and _looks_like_from_raw_parts_wrapper_impl(content, offset):
        return True
    if detector_name == "from_raw_parts" and _looks_like_documented_vec_rebuild(content, offset):
        return True
    return False


def _has_local_safety_rationale(content: str, offset: int) -> bool:
    line_start = content.rfind("\n", 0, offset) + 1
    comments = _preceding_comment_block(content[:line_start])
    if not comments:
        return False
    return bool(_SAFETY_COMMENT_RE.search(comments) or _UTF8_RATIONALE_RE.search(comments))


def _preceding_comment_block(prefix: str) -> str:
    lines = prefix.splitlines()
    collected: list[str] = []
    for raw_line in reversed(lines):
        stripped = raw_line.strip()
        if not stripped:
            if collected:
                break
            continue
        if stripped.startswith("//"):
            collected.append(stripped)
            continue
        break
    return "\n".join(reversed(collected))


def _nearby_comment_window(content: str, offset: int, *, max_lines: int) -> str:
    line_start = content.rfind("\n", 0, offset) + 1
    lines = content[:line_start].splitlines()
    window = lines[-max_lines:]
    comments = [line.strip() for line in window if line.strip().startswith("//")]
    return "\n".join(comments)


def _looks_like_repr_transparent_cast(content: str, offset: int) -> bool:
    line_start = content.rfind("\n", 0, offset) + 1
    line_end = content.find("\n", offset)
    if line_end == -1:
        line_end = len(content)
    line = content[line_start:line_end]
    for type_name in _REPR_TRANSPARENT_STRUCT_RE.findall(content):
        if re.search(rf"\b{re.escape(type_name)}\b", line):
            return True
    return False


def _looks_like_from_raw_parts_wrapper_impl(content: str, offset: int) -> bool:
    name = _enclosing_function_name(content, offset)
    return name in {"from_raw_parts", "from_raw_parts_mut"}


def _looks_like_documented_vec_rebuild(content: str, offset: int) -> bool:
    line_start = content.rfind("\n", 0, offset) + 1
    line_end = content.find("\n", offset)
    if line_end == -1:
        line_end = len(content)
    line = content[line_start:line_end]
    if "Vec::from_raw_parts" not in line:
        return False
    comments = _nearby_comment_window(content, offset, max_lines=8)
    return bool(_VEC_REBUILD_RATIONALE_RE.search(comments))


def _enclosing_function_name(content: str, offset: int) -> str | None:
    for match in re.finditer(r"\bfn\s+([A-Za-z_]\w*)\b", content):
        body_start = _find_block_start(content, match.end())
        if body_start is None:
            continue
        body_end = _find_matching_brace(content, body_start)
        if body_end is None:
            continue
        if body_start <= offset <= body_end:
            return match.group(1)
    return None


def _looks_like_function_definition_token(content: str, offset: int) -> bool:
    line_start = content.rfind("\n", 0, offset) + 1
    line_end = content.find("\n", offset)
    if line_end == -1:
        line_end = len(content)
    line = content[line_start:line_end]
    column = offset - line_start
    prefix = line[:column]
    return bool(re.search(r"\bfn\s+$", prefix))


def _holds_lock_guard_across_await(body: str, acquire_re: re.Pattern[str]) -> bool:
    for match in acquire_re.finditer(body):
        guard = match.groupdict().get("guard", "")
        acquire_offset = match.end()

        # Determine the brace depth at the acquisition point so we can detect
        # implicit drops when the enclosing block scope ends.
        acquire_depth = _brace_depth_at(body, acquire_offset)

        tail = body[acquire_offset:]
        await_match = _AWAIT_RE.search(tail)
        if await_match is None:
            continue

        before_await = tail[: await_match.start()]

        # Explicit drop() call before the await → guard is released.
        if guard and re.search(
            rf"\b(?:drop|std::mem::drop)\s*\(\s*{re.escape(guard)}\s*\)",
            before_await,
        ):
            continue

        # Implicit drop via block scope: if the brace depth drops below
        # the acquisition depth before the await, the guard has been
        # dropped by the closing brace of its enclosing block.
        if _scope_exits_before(before_await, acquire_depth):
            continue

        return True
    return False


def _brace_depth_at(text: str, offset: int) -> int:
    """Return the net brace depth at *offset* within *text*."""
    depth = 0
    for i in range(offset):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    return depth


def _scope_exits_before(text: str, acquire_depth: int) -> bool:
    """Return True if brace depth drops below *acquire_depth* anywhere in *text*.

    This means the block that contained the lock acquisition has ended,
    implicitly dropping the guard.
    """
    depth = acquire_depth
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < acquire_depth:
                return True
    return False


def _entry(
    filepath: Path,
    *,
    line: int,
    name: str,
    summary: str,
    tier: int,
    confidence: str,
    detail: dict[str, Any] | None = None,
) -> dict:
    detail_payload = dict(line=line)
    if detail:
        detail_payload.update(detail)
    return dict(
        file=rel(filepath),
        line=line,
        name=name,
        summary=summary,
        detail=detail_payload,
        tier=tier,
        confidence=confidence,
    )


def _line_number(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1
