# Runtime inventory — read-only discovery

**Date:** 2026-10-15
**Safety:** no runtime was started and no model was loaded.

## llama.cpp CUDA lane

- Executable: `E:\Echo-DB\tools\llama-b11446-cuda12.4\llama-server.exe`
- Version: `0.6.0-dev`, build `11446`, commit `a043d38a6`
- Build: Clang 20.1.8, Windows x86_64
- SHA-256: `485972547DB06AB4864628F59F099FC2B7FCF0FEF1ED79D0D8871D226FFCCEB1`
- Size: `9,216` bytes (launcher; adjacent DLLs provide the runtime)
- `--list-devices` reported: `CUDA0: NVIDIA GeForce RTX 4080 SUPER`, `32759 MiB`, `31381 MiB free`
- The help contract exposes GGUF model loading, device selection, split mode, tensor split, loopback host, port, API key, slots and metrics-related options.

## Strata CUDA lane

- Executable: `E:\Echo-DB\tools\Strata-v0.1.44.1-cuda12\strata.exe`
- Build metadata: version `0.1.44.1`, CUDA `12.9`, portable `true`, experimental `true`, vision `gpu`
- SHA-256: `DC676A683E5F0917E476FF29CE2F1D11371057068190870F0ACC6A22E53F9D61`
- Size: `285,957,120` bytes
- `strata-vision.exe` SHA-256: `E99EF40A638BE4CE4F8F48843858A2A7617CE2844EA0811CF03451945191E72F`
- `--version` returned exit code `1` with no output; the version is taken from the verified `BUILD.json`.
- Local Strata docs describe a browser/API surface at loopback port `8080`, a Monitor view, and an OpenAI-compatible `/v1` API. Its model setup and Windows launch contract still need a bounded qualification.

## Initial conclusion

- **First safe candidate:** llama.cpp against the verified six-shard UD-Q6 GGUF.
- **Second lane:** Strata, qualified separately with its own supported Qwen3.8 model/profile. Do not assume direct compatibility with the UD-Q6 GGUF.
- No phone-access or runtime-control endpoint is enabled by this discovery.
