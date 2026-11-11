# Rust

Markers: `Cargo.toml`. Lockfile: `Cargo.lock` (expected for binaries; libraries often commit it too since Cargo's 2023 guidance). Toolchain pin: `rust-toolchain.toml`, `rust-toolchain`, `rust-version` in `Cargo.toml`. Workspace: `[workspace]` in the root `Cargo.toml`; treat it as one subproject.

## Environment

`cargo clippy`, `cargo test` and coverage build the project: they run `build.rs` scripts and proc macros (project code) and download crates. They write `target/` into the repo (normally git-ignored). Set `CARGO_TARGET_DIR=<scratch>/target` to keep the build out of the repo, and say a first build can take minutes. `cargo fmt --check` builds nothing.

Cargo subcommands that are not installed (`cargo machete`, `cargo llvm-cov`) need `cargo install`, which installs into `~/.cargo/bin`, outside the project. Ask before installing; otherwise mark "not run: not installed".

## Tools

| tool | category | config | tier 1 command | notes |
|---|---|---|---|---|
| `clippy` | lint | `clippy.toml`, `.clippy.toml`, `[lints.clippy]`, `[workspace.lints.clippy]` | `cargo clippy --workspace --all-targets --message-format=short 2>&1` | Count `warning:` and `error:` lines (skip the summary lines). Level 3 in CI is `-- -D warnings`. |
| `rustfmt` | format | `rustfmt.toml`, `.rustfmt.toml` | `cargo fmt --all --check` | |
| `cargo-test` | tests | (none) | `cargo test --workspace` | Unit tests live in `#[cfg(test)]` modules; integration tests in `tests/`. |
| `nextest` | tests | `.config/nextest.toml` | `cargo nextest run --workspace` if installed | |
| `cargo-llvm-cov` | coverage | (none) | `cargo llvm-cov --workspace --summary-only` if installed | Needs the `llvm-tools-preview` component. |
| `tarpaulin` | coverage | `tarpaulin.toml`, `.tarpaulin.toml` | `cargo tarpaulin --out Stdout` if installed | Linux-focused. |
| `cargo-deny` | static | `deny.toml` | not run (config only) |  |
| `cargo-audit` | deps_audit | `.cargo/audit.toml` | not run (config only) | `rustsec/audit-check` is the GitHub Action. |
| `cargo-machete` | deadcode | (none) | `cargo machete` if installed | Unused dependencies; fast, no build. |
| `cargo-udeps` | deadcode | (none) | recommend only: needs nightly | |

## Suppressions

`#[allow(` and `#![allow(`. A crate-level `#![allow(clippy::...)]` or `#![allow(dead_code)]` in `lib.rs`/`main.rs` hides warnings for the whole crate: list those separately. `unsafe` blocks are worth a count (`grep -c "unsafe {"`) as a review signal, not a suppression.

## First steps for recommendations

CI (GitHub Actions):

```yaml
- uses: dtolnay/rust-toolchain@stable
  with: { components: "clippy, rustfmt" }
- run: cargo fmt --all --check
- run: cargo clippy --workspace --all-targets -- -D warnings
- run: cargo test --workspace --locked
```

Workspace-wide lint levels (Rust 1.74+):

```toml
[workspace.lints.clippy]
unwrap_used = "warn"
[workspace.lints.rust]
unsafe_code = "forbid"
```

Each member crate then needs `[lints] workspace = true`. Clippy has no baseline file; for a crate with many warnings, deny warnings in CI for new crates first, or allow named lints at the crate root and remove them one by one.

Architecture: split a large crate into a Cargo workspace of crates along its boundaries; the compiler then rejects a dependency the manifest does not declare. Write the boundaries down in `ARCHITECTURE.md` (what each crate owns, what may depend on what).
