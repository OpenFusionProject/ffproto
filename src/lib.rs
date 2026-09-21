//! FusionFall over-the-wire protocol structs, generated from the IR
//! JSON files under `structs/` by `build.rs` at compile time.
//!
//! Each protocol version lives in its own module (`v0104`, `v0728`,
//! `v1013`, ...). `v0104` is the base and defines every struct; it is
//! additionally re-exported at the crate root. The other version
//! modules only contain the structs whose layout differs from the base
//! — for anything else, use the base/crate-root definition.
//!
//! The IR JSON files are the source of truth; do not edit the
//! generated structs directly.

#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(dead_code)]

use std::fmt::Debug;

/// Marker trait for types that can appear on the wire as a packet body
/// (or be embedded inside one). All generated structs implement this.
pub trait FFPacket: Debug {}

include!(concat!(env!("OUT_DIR"), "/ffstructs.rs"));
