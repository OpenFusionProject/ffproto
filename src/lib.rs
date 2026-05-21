//! FusionFall over-the-wire protocol structs, generated from the IR
//! JSON files under `structs/` by `build.rs` at compile time.
//!
//! Each protocol version lives in its own module (`v0104`, `v0728`,
//! `v1013`, ...). The `0104` version is additionally re-exported at
//! the crate root.
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
