# Mesh System Dashboard — Answered Build Questions

## Decision summary

Build this as a **Mesh-native, read-only system dashboard** first.

- Existing Mesh PWA: keep it as the host application.
- New route: `/system`.
- Backend: add a Mesh module and endpoints; do not create a second public service.
- Frontend: vanilla HTML/CSS/JavaScript using the existing Mesh shell and terminal theme.
- Stream: isolated `/api/system/events` SSE endpoint, reusing Mesh’s existing SSE discipline where practical.
- Persistence: separate `data/system_dashboard.db` for bounded telemetry and `data/system_dashboard_prefs.json` for preferences.
- Controls: disabled by default in Phase 1. Add engine-specific controls only after read-only detection is proven.
- Current test target: Strata running Qwen3.8-Flash-Next IQ3_S.
- DeepSeek Harness: not part of this dashboard’s control path. It is intentionally excluded from the current workflow.

## 1. Platform and host

1. **OS:** Windows 11 Pro.
2. **Machine:** the dashboard runs on the same PC as Mesh and the local inference engines.
3. **Network:** loopback by default. The existing private Tailscale route may expose the Mesh page, but do not bind a new public listener.
4. **Embedding:** embed the dashboard inside the existing Mesh PWA rather than creating another service.
5. **Python:** the active `python` command is Python **3.11.16**. The Mesh source should target that runtime. Existing `cpython-314` cache files are stale artifact evidence, not proof of the active runtime.
6. **Current Mesh identity:** preserve the existing loopback/private-host policy and exact process ownership checks. Do not weaken Host or Origin validation for the dashboard.

## 2. Hardware and metrics

7. **GPU:** NVIDIA GeForce RTX 4080 SUPER, approximately 32 GiB VRAM.
8. **CPU/RAM:** AMD Ryzen 9 7900X with 128 GB system RAM.
9. **NVIDIA metrics:** `nvidia-smi` is available and has already been used successfully.
10. **GPU metrics:** read temperature, utilization, VRAM total/used/free, power draw, and fan percentage/RPM when the driver reports them.
11. **CPU temperature/fan:** not yet verified from an approved source. Do not fabricate values. Show `unavailable` until a reliable WMI or hardware-monitor source is positively identified.
12. **Fan terminology:** display GPU fan percentage/RPM and CPU fan percentage/RPM when available. “Fan power” is not a useful metric. Display GPU power draw and CPU package power separately when available.
13. **Drives:** monitor C: and D: first. Show used percentage, free space, and total size. Exclude network and removable drives by default.
14. **Resource sampling:** system metrics every 2 seconds; engine/model discovery every 5 seconds; push changes over SSE.
15. **No invented data:** every unavailable sensor must be labeled unavailable rather than replaced with a guessed value.

## 3. Dependencies and subprocess policy

16. **Backend dependency policy:** prefer Python standard library for the core dashboard.
17. **Allowed stdlib components:** `http.server`, `threading`, `subprocess`, `ctypes`, `socket`, `sqlite3`, `json`, `shutil.disk_usage`, `time`, and `pathlib`.
18. **Subprocesses:** allowed for read-only probes such as `nvidia-smi`, PowerShell/WMI, and engine health commands.
19. **Dependency additions:** do not add `psutil`, pynvml, HWiNFO, OpenHardwareMonitor, or another helper just to make the first version appear complete. An optional sensor adapter can be added later after explicit qualification.
20. **Web Push:** not part of the first dashboard slice. Do not install `pywebpush` or cryptography for this feature.
21. **Security:** probes must use bounded timeouts, fixed argument lists, no shell interpolation, and no arbitrary command execution from the browser.

## 4. Mesh integration

22. **Module location:** add a focused module beside the existing Mesh backend modules. Suggested name: `system_dashboard.py`.
23. **Frontend location:** add the dashboard view to the existing Mesh HTML/JS/CSS surface rather than creating a second frontend application.
24. **Route:** `/system`.
25. **API endpoints:**

```text
GET  /system
GET  /api/system/metrics
GET  /api/system/llm
GET  /api/system/drives
GET  /api/system/events
GET  /api/system/health
POST /api/system/refresh
```

26. **SSE:** use `GET /api/system/events` for metric and state updates. Keep it separate from Relay message delivery so telemetry cannot enter the chat/outbox path.
27. **Authentication:** loopback read-only access may use the existing local Mesh policy. Tailscale access must use the existing private Mesh authentication/Host rules. Controls, when later enabled, require a separate capability or token.
28. **PWA:** reuse the existing Mesh manifest and service worker. Do not cache system values, chat, approvals, attachments, or credentials.
29. **Strata WebApp:** provide a link/open action to `http://127.0.0.1:8094/`, but do not proxy model traffic through Mesh.
30. **Navigation:** add System as a Mesh navigation destination without changing the accepted Relay layout.

## 5. Current local LLM target

31. **Engine currently being tested:** Strata.
32. **Strata executable:** staged `strata.exe` version 0.1.44.1.
33. **Current model:** Qwen3.8-Flash-Next GSQ-RCO IQ3_S.
34. **Current model ID:** `qwen3.8-flash-next-iq3-s-strata`.
35. **Current endpoint:** `http://127.0.0.1:8094/v1`.
36. **Strata WebApp:** `http://127.0.0.1:8094/`.
37. **Health endpoint:** `GET http://127.0.0.1:8094/health`.
38. **Model endpoint:** `GET http://127.0.0.1:8094/v1/models`.
39. **Current context:** 196,608 tokens.
40. **Output policy:** no artificial output cap; API `max_tokens: 0` means use the remaining context.
41. **Placement:** GPU hot-expert cache plus RAM-resident/mapped expert complement; this is expected Strata behavior, not an error.
42. **MTP:** enabled in the current Strata launch.
43. **Current verification:** health, model listing, and a completion smoke test passed.
44. **Dashboard display:** show Strata, model ID, loaded state, context, endpoint, engine version when available, and GPU/RAM placement when available from the engine log or health surface.
45. **DeepSeek Harness:** do not integrate it into this dashboard right now. The user explicitly wants to use the Strata WebApp directly while testing Qwen3.8.
46. **Other engines:** do not claim Ollama, LM Studio, vLLM, KoboldCpp, or text-generation-webui support is installed. Build adapters behind a registry, but only enable adapters after each engine is positively detected and tested.

## 6. Detection strategy

47. **Use a registry plus probes:** do not scan every port or broadly enumerate/kill processes.
48. **Detection order:**

```text
1. Explicit configured engine adapters.
2. Known loopback endpoints with bounded health/model requests.
3. Positively identified owned processes for correlation only.
4. Report unknown processes as unknown; do not treat names alone as engines.
```

49. **Strata adapter:** query `/health` and `/v1/models`; correlate the exact owned `strata.exe`/wrapper identity only if process data is needed.
50. **OpenAI-compatible adapter:** support read-only `/v1/models` probing for explicitly registered local endpoints.
51. **Process matching:** require executable path, PID, creation time, full command line, working directory, and expected port where possible.
52. **No broad process-name sweep:** never treat every `python.exe`, `llama-server.exe`, or `strata.exe` as owned by Mesh.
53. **Unknown engine behavior:** display an informational “detected but unsupported” record; do not offer pause, unload, suspend, or kill.

## 7. Pause and unload semantics

54. **Phase 1 is read-only.** The dashboard must not pause, unload, suspend, kill, or restart any local model.
55. **Universal pause is not assumed.** “Pause” must be defined per engine as one of: reject new work, stop accepting requests, pause an owned wrapper, or suspend an owned process. Do not use a misleading universal button.
56. **Universal unload is not assumed.** Use an engine API where one exists. Otherwise report `unsupported` rather than silently killing a process.
57. **Strata current behavior:** expose status and an “Open Strata WebApp” action first. Do not claim that Strata unload is supported until a graceful, identity-verified lifecycle path is qualified.
58. **Process controls:** if later enabled, they must operate only on a positively verified owned identity. Never broad-kill by process name or port alone.
59. **Confirmation:** every destructive or interrupting action requires explicit confirmation naming engine, model, PID, and expected effect.
60. **Unload all:** do not add an “Unload all” control. It is too broad for the first implementation.
61. **Audit:** future control actions must be recorded in `system_control_log` with timestamp, engine, model, method, identity evidence, result, and failure reason.

## 8. Display and history

62. **Loaded models:** show currently loaded/detected models first. Keep installed-model catalogs out of the first view unless an adapter provides them reliably.
63. **Fields:** engine, model, status, context, endpoint, PID/port when verified, GPU/RAM placement, last activity, and supported controls.
64. **Generation status:** show active/idle only when the engine exposes reliable evidence. Otherwise show loaded/unknown activity.
65. **Per-model VRAM:** show it only when mapped to a verified process/model or reported directly by the engine. Do not divide total VRAM by model count.
66. **History:** keep bounded history: one-minute samples for 7 days and five-minute rollups for 30 days. This is enough for troubleshooting without turning telemetry into an unbounded log.
67. **Database:** use a separate `data/system_dashboard.db`, not the Relay/outbox database.
68. **Suggested tables:**

```text
system_metrics
system_llm_state
system_alerts
system_control_log
```

69. **Preferences:** use `data/system_dashboard_prefs.json` for theme, refresh interval, and view preferences. Do not store credentials there.

## 9. Visual and interaction requirements

70. **Style:** use the terminal theme in `MESH-THEME-SPEC.md`.
71. **Default theme:** dark.
72. **Theme toggle:** persist light/dark selection in localStorage without reload or state loss.
73. **Dashboard form:** one compact overview screen with expandable detail panes; do not create a large analytics dashboard.
74. **Readouts:** terminal font for metrics, IDs, ports, timestamps, and model names.
75. **Sparklines:** optional later. Do not make charts a Phase 1 dependency.
76. **Thresholds:** dashboard-only notices by default. Do not send push notifications or Telegram messages automatically.
77. **Alert defaults:** no unsolicited alerts. A user can opt in later to visible dashboard alerts.
78. **Mobile mode:** compact summary showing GPU, CPU, RAM, drives, and loaded model count; details expand inside the same pane.
79. **Controls:** no control buttons should appear until the corresponding backend effect is implemented and verified.

## 10. Safety and rollout

80. **Phase 1:** read-only metrics, Strata health/model detection, dashboard route, SSE, theme toggle, and bounded persistence.
81. **Phase 2:** qualify CPU sensor sources and additional engine adapters independently.
82. **Phase 3:** add engine-specific pause/unload only with exact ownership checks and confirmation.
83. **No OS changes:** do not install drivers, hardware utilities, services, scheduled tasks, startup hooks, or new listeners as part of the dashboard.
84. **No public exposure:** keep Mesh and the dashboard private/loopback-bound; do not use Funnel.
85. **No model routing changes:** the dashboard observes Strata; it does not change DeepSeek routing, model selection, or inference settings.
86. **Verification gates:**

```text
- Existing Mesh tests still pass.
- /system renders through the real Mesh server.
- /api/system/health identifies the module and version.
- Strata health/model probes pass against 127.0.0.1:8094.
- SSE reconnects without duplicate metric state.
- Theme toggle works in both themes and survives reload.
- No horizontal overflow at phone width.
- Unavailable sensors are labeled unavailable.
- No control endpoint can mutate engine state in Phase 1.
```

## 11. Minimum implementation target

Implement the first slice without asking for more configuration:

```text
Mesh / System

GPU
  NVIDIA RTX 4080 SUPER
  temperature / utilization / VRAM / power / fan when available

CPU / MEMORY
  Ryzen 9 7900X
  CPU temperature: unavailable until a verified source exists
  RAM used / available / percentage

DRIVES
  C: used / free / total
  D: used / free / total

LOCAL LLM
  Strata
  Qwen3.8-Flash-Next IQ3_S
  loaded
  context: 196608
  endpoint: 127.0.0.1:8094/v1
  [open Strata WebApp]
```

The dashboard should be truthful before it is comprehensive. It is better to show one verified Strata model and several unavailable sensor fields than to display plausible but unverified metrics.
