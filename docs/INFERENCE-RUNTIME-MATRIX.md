# Mesh inference runtime matrix

**Status:** discovery only; no runtime started and no model loaded.

| Runtime lane | Local evidence | First-use fit | Current blocker |
|---|---|---|---|
| llama.cpp CUDA 12.4 | `E:\Echo-DB\tools\llama-b11446-cuda12.4\llama-server.exe` exists; `--help` exposes GGUF model path, GPU/device selection, split mode, tensor split, loopback host, port, API key, health/slots/metrics-related options | Best first adapter for the verified six-shard `UD-Q6_K_XL` GGUF | Must perform a read-only capability/version/device check, then a separately authorized local smoke load; exact GPU split is not chosen yet |
| Strata CUDA 12 | `E:\Echo-DB\tools\Strata-v0.1.44.1-cuda12\strata.exe` and `strata-vision.exe` exist; build is portable, CUDA 12.9, experimental, GPU/vision capable | Required second lane; includes Chat/Monitor/API concepts and is intended for Qwen3.8-Flash-Next | The current Strata documentation describes its own setup/model formats and port 8080; compatibility with the downloaded Unsloth UD-Q6 GGUF and the exact Windows launch/API contract is unverified |
| rtp-llm | Source tree exists at `E:\Echo-DB\tools\rtp-llm` with server/front-end/model code | Not a first phone-control lane | No bounded Windows executable/configuration/ownership contract identified |

## Recommended order

1. **Inventory only:** record executable hashes/versions, supported model formats, device list, default ports, health endpoints, process identity, and shutdown behavior. Do not start a model.
2. **llama.cpp lane:** use the verified Qwen UD-Q6 GGUF as the first fixed profile because the runtime explicitly exposes GGUF loading and GPU split controls.
3. **Strata lane:** qualify its own recommended Qwen3.8 model path and API separately. Do not assume the llama.cpp GGUF is interchangeable.
4. Put both behind one Mesh runtime adapter interface with explicit runtime/model profiles. The phone never supplies executable paths, model paths, argv, ports, or arbitrary settings.
5. Add live telemetry and phone chat only after a local disposable smoke test proves load, health, inference, unload, process ownership, VRAM read-back, and failure behavior.

## Private-phone boundary

Keep the phone on the existing private Tailscale route. Runtime servers remain loopback-bound; Mesh is the only authenticated proxy. Do not expose llama.cpp or Strata directly to the tailnet until the broker, request limits, authentication, CSRF/origin checks, and receipt/read-back path are verified.

## Known model status

The verified model is `Qwen3.8-Flash-Next-UD-Q6_K_XL` from Unsloth revision `38bb39ee97821de2c9009abb7e93950eec396e66`. All six shards and `MANIFEST.json` are present. Its direct Strata compatibility is **UNKNOWN** until tested against Strata's documented model setup; no model process has been started by this discovery.
