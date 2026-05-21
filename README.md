# ffproto

Intermediate representation specification for the FusionFall wire protocol in JSON.

## Overview

Each struct has a name, size, padding (can be omitted and inherited from defaults), and a list of fields. Each field has a name, type, and optionally length (for strings) or array (for arrays). The type can be a primitive type (i32, i64, f32, f64, wstr) or a reference to another struct.

## Example

```json
{
  "name": "sP_CL2FE_REQ_PC_SEND_EMAIL",
  "size": 1164,
  "fields": [
    {
      "name": "iTo_PCUID",
      "type": "i64"
    },
    {
      "name": "szSubject",
      "type": "wstr",
      "length": 32
    },
    {
      "name": "szContent",
      "type": "wstr",
      "length": 512
    },
    {
      "name": "aItem",
      "type": "struct",
      "ref": "sEmailItemInfoFromCL",
      "array": 4
    },
    {
      "name": "iCash",
      "type": "i32"
    }
  ]
}
```

## Tools

This repo includes a Python script `gen_from_cs.py` that can be pointed to a folder of FF structs defined in C# to generate a JSON file containing the intermediate representation (IR) of those structs. The script uses regular expressions to parse the C# code and extract the relevant information about each struct and its fields.

`gen_cs.py` does the opposite, taking a JSON file in the IR format and generating C# struct definitions from it. This is used to ensure that the generated C# code matches the original struct definitions exactly.

`gen_cpp.py` generatese a C++ header file containing struct definitions based on the JSON IR.

## Rust Crate

This repo also includes a Rust crate `ffproto` that generates Rust struct definitions for the types in the JSON IR **at compile time**, with one module per JSON.
