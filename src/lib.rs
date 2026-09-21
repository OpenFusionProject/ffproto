//! FusionFall over-the-wire protocol structs, generated from the IR
//! JSON files under `structs/` by `build.rs` at compile time.
//!
//! Structs whose layout is identical in every protocol version live
//! directly at the crate root. Anything that differs in — or is missing
//! from — even one version is emitted per version instead, into that
//! version's module (`v0104`, `v0728`, `v1013`, ...).
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
