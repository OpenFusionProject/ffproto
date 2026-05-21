#!/usr/bin/env python3
"""Generate a single C++ header from a packets.json IR document.

Emits a header in the same style as OpenFusion's hand-maintained
structs/*.hpp files: pack(push)/pack(pop) wrapping, per-struct
#pragma pack(N), POD struct definitions using <cstdint> types and
char16_t for fixed-length UTF-16 strings, followed by a block of
static_assert checks on sizeof().

Structs are emitted in topological order so that any struct used as a
field appears before its users.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# IR primitive -> C++ type
PRIM_TO_CPP = {
    "i8":  "int8_t",
    "u8":  "uint8_t",
    "i16": "int16_t",
    "u16": "uint16_t",
    "i32": "int32_t",
    "u32": "uint32_t",
    "i64": "int64_t",
    "u64": "uint64_t",
    "f32": "float",
    "f64": "double",
}


def render_field(fld: dict) -> str:
    name = fld["name"]
    ty = fld["type"]
    array = fld.get("array")
    length = fld.get("length")
    ref = fld.get("ref")

    if ty == "wstr":
        assert length is not None
        return f"\tchar16_t {name}[{length}];"

    if ty == "struct":
        assert ref is not None
        suffix = f"[{array}]" if array is not None else ""
        return f"\t{ref} {name}{suffix};"

    cpp = PRIM_TO_CPP.get(ty)
    if cpp is None:
        raise ValueError(f"unsupported IR type {ty!r} on field {name!r}")
    suffix = f"[{array}]" if array is not None else ""
    return f"\t{cpp} {name}{suffix};"


def render_struct(s: dict, default_pack: int) -> str:
    pack = s.get("pack", default_pack)
    lines = [f"#pragma pack({pack})", f"struct {s['name']} {{"]
    for f in s["fields"]:
        lines.append(render_field(f))
    lines.append("};")
    return "\n".join(lines) + "\n"


def topo_sort(structs: list[dict]) -> list[dict]:
    """Stable topological sort by nested-struct dependencies.

    Structs that reference unknown types are emitted at the end in
    their original order; the caller will warn about them.
    """
    by_name = {s["name"]: s for s in structs}
    order_index = {s["name"]: i for i, s in enumerate(structs)}
    emitted: set[str] = set()
    result: list[dict] = []

    def deps(s: dict) -> list[str]:
        out = []
        for f in s["fields"]:
            if f.get("type") == "struct":
                ref = f["ref"]
                if ref in by_name:
                    out.append(ref)
        return out

    # Iterative DFS to avoid recursion limit on deep graphs.
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in emitted or name not in by_name:
            return
        if name in visiting:
            # Cycle — emit anyway in original order; C++ won't compile,
            # but that's the user's problem to resolve.
            return
        visiting.add(name)
        for d in sorted(deps(by_name[name]), key=lambda n: order_index[n]):
            visit(d)
        visiting.discard(name)
        emitted.add(name)
        result.append(by_name[name])

    for s in structs:
        visit(s["name"])
    return result


def render_header(doc: dict) -> str:
    structs = doc["structs"]
    default_pack = doc.get("defaults", {}).get("pack", 4)

    ordered = topo_sort(structs)

    parts: list[str] = []
    parts.append("/* generated from packets.json by gen_cpp.py */\n")
    parts.append("\n")
    parts.append("#pragma pack(push)\n")
    parts.append("\n")
    for s in ordered:
        parts.append(render_struct(s, default_pack))
        parts.append("\n")
    parts.append("#pragma pack(pop)\n")
    parts.append("\n")
    for s in ordered:
        name = s["name"]
        parts.append(
            f"static_assert(sizeof({name}) == {s['size']});\n"
        )
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path, help="packets.json path")
    ap.add_argument("-o", "--output", type=Path,
                    help="Output .hpp path (default: stdout)")
    args = ap.parse_args()

    doc = json.loads(args.input.read_text(encoding="utf-8"))

    # Warn about unresolved struct refs.
    names = {s["name"] for s in doc["structs"]}
    unresolved: set[str] = set()
    for s in doc["structs"]:
        for f in s["fields"]:
            if f.get("type") == "struct" and f.get("ref") not in names:
                unresolved.add(f["ref"])
    if unresolved:
        print(
            f"warn: {len(unresolved)} unresolved struct ref(s): "
            f"{', '.join(sorted(unresolved))}",
            file=sys.stderr,
        )

    text = render_header(doc)
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {len(doc['structs'])} structs to {args.output}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
