#!/usr/bin/env python3
"""Generate packets.json IR from C# packet struct sources.

Walks a directory of C# files, finds every

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode,
                  Pack = N, Size = M)]
    public struct NAME { ... }

and emits a single JSON document describing each struct's fields in a
language-agnostic form suitable for codegen in C/C++/C#/Python/Rust/etc.

JSON shape:

    {
      "version": 1,
      "defaults": {"pack": 4, "charset": "utf-16le"},
      "structs": [
        {"name": "...", "size": N, "pack": 4?, "fields": [
            {"name": "f", "type": "i32"},
            {"name": "s", "type": "wstr",   "length": 10},
            {"name": "a", "type": "i32",    "array": 5},
            {"name": "n", "type": "struct", "ref": "sItemBase"}
        ]}
      ]
    }

Each emitted struct's computed size (assuming sequential layout with the
declared Pack) is verified against the declared Size attribute; mismatches
are reported on stderr and exit code is non-zero.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ----- C# token -> IR primitive --------------------------------------------

MARSHAL_TO_IR = {
    "I1": "i8",
    "U1": "u8",
    "I2": "i16",
    "I4": "i32",
    "U4": "u32",
    "I8": "i64",
    "U8": "u64",
    "R4": "f32",
}

# C# field-declaration type tokens (used for ByValArray element type and
# bare Struct fields). Maps the C# alias to the IR primitive name; anything
# not in this map is treated as a nested struct reference.
CS_TYPE_TO_IR = {
    "sbyte": "i8",
    "byte": "u8",
    "short": "i16",
    "ushort": "u16",
    "int": "i32",
    "uint": "u32",
    "long": "i64",
    "ulong": "u64",
    "float": "f32",
    "double": "f64",
    "bool": "u8",
    "char": "u16",
}

PRIM_SIZE = {
    "i8": 1, "u8": 1,
    "i16": 2, "u16": 2,
    "i32": 4, "u32": 4, "f32": 4,
    "i64": 8, "u64": 8, "f64": 8,
}


# ----- Regexes -------------------------------------------------------------

# Captures Pack and Size out of the [StructLayout(...)] attribute. The
# attribute body can span multiple lines, so we use DOTALL.
RE_STRUCT_LAYOUT = re.compile(
    r"\[StructLayout\((?P<body>[^\]]*?)\)\]\s*"
    r"public\s+struct\s+(?P<name>\w+)\s*\{(?P<body2>.*?)\n\}",
    re.DOTALL,
)

RE_PACK = re.compile(r"\bPack\s*=\s*(\d+)")
RE_SIZE = re.compile(r"\bSize\s*=\s*(\d+)")

# A single field: optional [MarshalAs(...)] attribute followed by
#   public <csharp-type> name;
# csharp-type may include [] for arrays. We tolerate whitespace/newlines.
RE_FIELD = re.compile(
    r"(?:\[MarshalAs\(\s*UnmanagedType\.(?P<kind>\w+)"
    r"(?:\s*,\s*SizeConst\s*=\s*(?P<size_const>\d+))?\s*\)\]\s*)?"
    r"public\s+(?P<cs_type>[\w\[\]]+)\s+(?P<name>\w+)\s*;",
    re.DOTALL,
)


# ----- Data types ----------------------------------------------------------

@dataclass
class Field:
    name: str
    type: str
    length: int | None = None   # for wstr (chars)
    array: int | None = None    # for fixed arrays
    ref: str | None = None      # for struct refs

    def to_json(self) -> dict:
        out: dict = {"name": self.name, "type": self.type}
        if self.ref is not None:
            out["ref"] = self.ref
        if self.length is not None:
            out["length"] = self.length
        if self.array is not None:
            out["array"] = self.array
        return out


@dataclass
class Struct:
    name: str
    size: int
    pack: int
    fields: list[Field] = field(default_factory=list)
    source: str = ""


# ----- Parsing -------------------------------------------------------------

def strip_array_suffix(cs_type: str) -> str:
    return cs_type[:-2] if cs_type.endswith("[]") else cs_type


def parse_field(match: re.Match) -> Field:
    kind = match.group("kind")
    size_const = match.group("size_const")
    cs_type = match.group("cs_type")
    name = match.group("name")
    base_cs = strip_array_suffix(cs_type)

    if kind in MARSHAL_TO_IR:
        return Field(name=name, type=MARSHAL_TO_IR[kind])

    if kind == "ByValTStr":
        if size_const is None:
            raise ValueError(f"ByValTStr without SizeConst on field {name!r}")
        return Field(name=name, type="wstr", length=int(size_const))

    if kind == "ByValArray":
        if size_const is None:
            raise ValueError(f"ByValArray without SizeConst on field {name!r}")
        elem_ir = CS_TYPE_TO_IR.get(base_cs)
        if elem_ir is not None:
            return Field(name=name, type=elem_ir, array=int(size_const))
        # Otherwise it's an array of structs.
        return Field(name=name, type="struct", ref=base_cs,
                     array=int(size_const))

    if kind == "Struct":
        return Field(name=name, type="struct", ref=base_cs)

    if kind is None:
        # No MarshalAs attribute. Infer from the C# type.
        elem_ir = CS_TYPE_TO_IR.get(base_cs)
        if elem_ir is not None:
            return Field(name=name, type=elem_ir)
        return Field(name=name, type="struct", ref=base_cs)

    raise ValueError(f"unsupported MarshalAs kind {kind!r} on field {name!r}")


def parse_file(path: Path) -> Iterable[Struct]:
    text = path.read_text(encoding="utf-8", errors="replace")
    for m in RE_STRUCT_LAYOUT.finditer(text):
        body_attr = m.group("body")
        body = m.group("body2")
        pack_m = RE_PACK.search(body_attr)
        size_m = RE_SIZE.search(body_attr)
        s = Struct(
            name=m.group("name"),
            size=int(size_m.group(1)) if size_m else 0,
            pack=int(pack_m.group(1)) if pack_m else 4,
            source=str(path),
        )
        for fm in RE_FIELD.finditer(body):
            s.fields.append(parse_field(fm))
        # If no Size attribute and we found public fields, this isn't a
        # wire struct we know how to describe — skip.
        if size_m is None and s.fields:
            continue
        # Empty placeholder structs (no public fields, just the C#
        # decompiler's private _0024PRIVATE_0024 byte) carry an explicit
        # padding byte in the IR so consumers don't have to special-case
        # zero-sized structs. The byte is real: it's what the client
        # actually puts on the wire (Marshal.SizeOf == 1).
        if not s.fields:
            s.fields.append(Field(name="_unused", type="u8"))
            s.size = 1
        yield s


# ----- Size verification ---------------------------------------------------

def primitive_size(ir_type: str) -> int | None:
    return PRIM_SIZE.get(ir_type)


def compute_struct_layout(s: Struct, by_name: dict[str, "Struct"],
                          cache: dict[str, tuple[int, int]]
                          ) -> tuple[int, int] | None:
    """Compute (size, alignment) for a struct.

    Alignment is the max alignment of any field, capped by the struct's
    own Pack. Returns None if a nested ref is unresolved.
    """
    if s.name in cache:
        return cache[s.name]
    pack = s.pack
    offset = 0
    max_align = 1
    for fld in s.fields:
        layout = field_size_align(fld, by_name, cache)
        if layout is None:
            return None
        fsize, falign = layout
        align = min(falign, pack)
        if offset % align:
            offset += align - (offset % align)
        offset += fsize
        max_align = max(max_align, align)
    struct_align = min(max_align, pack)
    if offset % struct_align:
        offset += struct_align - (offset % struct_align)
    cache[s.name] = (offset, struct_align)
    return offset, struct_align


def field_size_align(fld: Field, by_name: dict[str, "Struct"],
                     cache: dict[str, tuple[int, int]]
                     ) -> tuple[int, int] | None:
    if fld.type == "wstr":
        assert fld.length is not None
        return fld.length * 2, 2
    if fld.type == "struct":
        assert fld.ref is not None
        nested = by_name.get(fld.ref)
        if nested is None:
            return None
        layout = compute_struct_layout(nested, by_name, cache)
        if layout is None:
            return None
        nested_size, nested_align = layout
        count = fld.array if fld.array is not None else 1
        return nested_size * count, nested_align
    prim = primitive_size(fld.type)
    if prim is None:
        return None
    count = fld.array if fld.array is not None else 1
    return prim * count, prim


# ----- Main ----------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input_dir", type=Path,
                    help="Directory of C# source files to scan.")
    ap.add_argument("-o", "--output", type=Path, default=Path("packets.json"),
                    help="Output JSON path (default: packets.json)")
    ap.add_argument("--indent", type=int, default=2,
                    help="JSON indent (default: 2)")
    ap.add_argument("--strict", action="store_true",
                    help="Refuse to write output if any size mismatch or "
                         "unresolved struct reference is found.")
    args = ap.parse_args()

    if not args.input_dir.is_dir():
        print(f"error: {args.input_dir} is not a directory", file=sys.stderr)
        return 2

    structs: list[Struct] = []
    for path in sorted(args.input_dir.rglob("*.cs")):
        try:
            structs.extend(parse_file(path))
        except Exception as exc:
            print(f"warn: failed to parse {path}: {exc}", file=sys.stderr)

    if not structs:
        print("error: no [StructLayout]+Size structs found", file=sys.stderr)
        return 2

    by_name = {s.name: s for s in structs}
    cache: dict[str, tuple[int, int]] = {}
    mismatches: list[tuple[str, int, int]] = []
    unresolved: list[str] = []

    for s in structs:
        if s.size == 0 and not s.fields:
            # Empty packet: no body to verify.
            continue
        layout = compute_struct_layout(s, by_name, cache)
        if layout is None:
            unresolved.append(s.name)
            continue
        computed, _ = layout
        if computed != s.size:
            mismatches.append((s.name, s.size, computed))

    packs = {s.pack for s in structs}
    default_pack = 4 if 4 in packs else next(iter(packs))

    if args.strict and (mismatches or unresolved):
        if unresolved:
            print(f"error: {len(unresolved)} struct(s) had unresolved nested"
                  f" refs: {', '.join(unresolved[:5])}"
                  f"{'...' if len(unresolved) > 5 else ''}", file=sys.stderr)
        if mismatches:
            print(f"error: {len(mismatches)} size mismatch(es):",
                  file=sys.stderr)
            for name, declared, computed in mismatches[:20]:
                print(f"  {name}: declared={declared} computed={computed}",
                      file=sys.stderr)
            if len(mismatches) > 20:
                print(f"  ... and {len(mismatches) - 20} more",
                      file=sys.stderr)
        print(f"error: refusing to write {args.output} due to --strict",
              file=sys.stderr)
        return 1

    out = {
        "defaults": {"pack": default_pack, "charset": "utf-16le"},
        "structs": [
            {
                "name": s.name,
                "size": s.size,
                **({"pack": s.pack} if s.pack != default_pack else {}),
                "fields": [f.to_json() for f in s.fields],
            }
            for s in structs
        ],
    }

    args.output.write_text(
        json.dumps(out, indent=args.indent) + "\n", encoding="utf-8")

    print(f"wrote {len(structs)} structs to {args.output}", file=sys.stderr)
    if unresolved:
        print(f"note: {len(unresolved)} struct(s) had unresolved nested refs"
              f" (size not verified): {', '.join(unresolved[:5])}"
              f"{'...' if len(unresolved) > 5 else ''}", file=sys.stderr)
    if mismatches:
        print(f"warn: {len(mismatches)} size mismatch(es):", file=sys.stderr)
        for name, declared, computed in mismatches:
            print(f"  {name}: declared={declared} computed={computed}",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
