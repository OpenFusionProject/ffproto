#!/usr/bin/env python3
"""Generate a Python module of ctypes.Structure classes from a packets.json
IR file.

The output module looks like:

    import ctypes as _c

    class sItemBase(_c.Structure):
        _pack_ = 4
        _fields_ = [
            ("iType", _c.c_int16),
            ("iID",   _c.c_int16),
            ...
        ]

    assert _c.sizeof(sItemBase) == 8
    ...

Each generated struct can be round-tripped through bytes via the standard
ctypes API: ``bytes(instance)`` serializes, ``Cls.from_buffer_copy(buf)``
deserializes, and nested structs / fixed-size arrays work out of the box.

Structs are emitted in topological order so any struct used as a field
appears before its users.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# IR primitive -> ctypes type (referenced as "_c.<name>" in output).
PRIM_TO_CTYPES = {
    "i8":  "c_int8",
    "u8":  "c_uint8",
    "i16": "c_int16",
    "u16": "c_uint16",
    "i32": "c_int32",
    "u32": "c_uint32",
    "i64": "c_int64",
    "u64": "c_uint64",
    "f32": "c_float",
    "f64": "c_double",
}


def render_field(fld: dict) -> str:
    name = fld["name"]
    ty = fld["type"]
    array = fld.get("array")
    length = fld.get("length")
    ref = fld.get("ref")

    if ty == "wstr":
        assert length is not None
        # Wire format is UTF-16LE (per IR defaults). Use c_uint16 rather
        # than c_wchar because c_wchar's width is platform-dependent
        # (2 bytes on Windows, 4 on Linux) and would corrupt the layout.
        return f"        ({name!r}, _c.c_uint16 * {length}),"

    if ty == "struct":
        assert ref is not None
        if array is not None:
            return f"        ({name!r}, {ref} * {array}),"
        return f"        ({name!r}, {ref}),"

    ct = PRIM_TO_CTYPES.get(ty)
    if ct is None:
        raise ValueError(f"unsupported IR type {ty!r} on field {name!r}")
    if array is not None:
        return f"        ({name!r}, _c.{ct} * {array}),"
    return f"        ({name!r}, _c.{ct}),"


def render_struct(s: dict, default_pack: int) -> str:
    pack = s.get("pack", default_pack)
    lines = [
        f"class {s['name']}(_c.Structure):",
        f"    _pack_ = {pack}",
        "    _fields_ = [",
    ]
    for f in s["fields"]:
        lines.append(render_field(f))
    lines.append("    ]")
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

    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in emitted or name not in by_name:
            return
        if name in visiting:
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


def render_module(doc: dict) -> str:
    structs = doc["structs"]
    default_pack = doc.get("defaults", {}).get("pack", 4)
    ordered = topo_sort(structs)

    parts: list[str] = []
    parts.append("# generated from packets.json by gen_py.py -- DO NOT EDIT\n")
    parts.append("import ctypes as _c\n")
    parts.append("\n")
    for s in ordered:
        parts.append(render_struct(s, default_pack))
        parts.append("\n")
    parts.append("# Runtime size assertions catch IR drift.\n")
    for s in ordered:
        name = s["name"]
        size = s.get("size")
        if size is None:
            continue
        parts.append(f"assert _c.sizeof({name}) == {size}\n")
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path, help="packets.json path")
    ap.add_argument("-o", "--output", type=Path,
                    help="Output .py path (default: stdout)")
    args = ap.parse_args()

    doc = json.loads(args.input.read_text(encoding="utf-8"))

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

    text = render_module(doc)
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {len(doc['structs'])} structs to {args.output}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
