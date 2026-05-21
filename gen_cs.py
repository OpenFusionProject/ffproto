#!/usr/bin/env python3
"""Generate C# struct sources from a packets.json IR document.

Inverse of gen_from_cs.py. For each struct entry in the JSON, writes a
file named <Name>.cs into the output directory containing a single
public struct decorated with the original [StructLayout]/[MarshalAs]
attributes. The output is intended to be byte-identical to the
original hand-written C# sources for the FFClient corpus.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# IR primitive -> (UnmanagedType marshal kind, C# type alias)
PRIM_TO_CS = {
    "i8":  ("I1", "sbyte"),
    "u8":  ("U1", "byte"),
    "i16": ("I2", "short"),
    "u16": ("U2", "ushort"),
    "i32": ("I4", "int"),
    "u32": ("U4", "uint"),
    "i64": ("I8", "long"),
    "u64": ("U8", "ulong"),
    "f32": ("R4", "float"),
    "f64": ("R8", "double"),
}


def render_field(fld: dict) -> str:
    name = fld["name"]
    ty = fld["type"]
    array = fld.get("array")
    length = fld.get("length")
    ref = fld.get("ref")

    if ty == "wstr":
        assert length is not None, f"wstr field {name!r} missing length"
        return (f"\t[MarshalAs(UnmanagedType.ByValTStr, SizeConst = {length})]\n"
                f"\tpublic string {name};")

    if ty == "struct":
        assert ref is not None, f"struct field {name!r} missing ref"
        if array is not None:
            return (f"\t[MarshalAs(UnmanagedType.ByValArray, "
                    f"SizeConst = {array})]\n"
                    f"\tpublic {ref}[] {name};")
        return (f"\t[MarshalAs(UnmanagedType.Struct)]\n"
                f"\tpublic {ref} {name};")

    if ty not in PRIM_TO_CS:
        raise ValueError(f"unsupported IR type {ty!r} on field {name!r}")
    kind, cs_alias = PRIM_TO_CS[ty]

    if array is not None:
        return (f"\t[MarshalAs(UnmanagedType.ByValArray, "
                f"SizeConst = {array})]\n"
                f"\tpublic {cs_alias}[] {name};")
    return (f"\t[MarshalAs(UnmanagedType.{kind})]\n"
            f"\tpublic {cs_alias} {name};")


def render_struct(s: dict, default_pack: int) -> str:
    name = s["name"]
    if not s["fields"]:
        # Empty packet: matches the decompiler's output for a C# struct
        # with no marshalled fields. No Pack/Size on the attribute, a
        # single private placeholder byte for body.
        return (
            "using System.Runtime.InteropServices;\n"
            "\n"
            "[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]\n"
            f"public struct {name}\n"
            "{\n"
            "\tprivate byte _0024PRIVATE_0024;\n"
            "}\n"
        )
    size = s["size"]
    pack = s.get("pack", default_pack)
    lines = []
    lines.append("using System.Runtime.InteropServices;")
    lines.append("")
    lines.append(
        f"[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode, "
        f"Pack = {pack}, Size = {size})]"
    )
    lines.append(f"public struct {name}")
    lines.append("{")
    field_blocks = [render_field(f) for f in s["fields"]]
    lines.append("\n\n".join(field_blocks))
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path, help="packets.json path")
    ap.add_argument("-o", "--output-dir", type=Path, required=True,
                    help="Directory to write .cs files into.")
    args = ap.parse_args()

    doc = json.loads(args.input.read_text(encoding="utf-8"))
    default_pack = doc.get("defaults", {}).get("pack", 4)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for s in doc["structs"]:
        text = render_struct(s, default_pack)
        (args.output_dir / f"{s['name']}.cs").write_text(text, encoding="utf-8")

    print(f"wrote {len(doc['structs'])} files to {args.output_dir}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
