No Rust extension is shipped initially. Add Rust only when a repeatable profile identifies a hot path and a benchmark specification demonstrates that the native implementation is worth its build and wheel-maintenance cost.

Any future PyO3/maturin module must retain a Python reference implementation for correctness tests and must pass parity tests across supported platforms.
