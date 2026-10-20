# Prompt Template: Generate a K10 Bot Controller

Copy this prompt into your coding assistant and fill in the task details. Do not include the bot's master token in source code, chat history, or committed configuration; read it at runtime instead.

```text
Build a controller for the existing K10 bot firmware. Do not invent endpoints,
authentication headers, command bytes, payload layouts, or hardware capabilities.

Before coding, read these references:
- participant-AGENTS.md
- ai-mandatory-checklist.md
- communication.md
- binary-protocol.md
- ai-udp-client.md
- relevant sensor/wiring pages for the requested hardware

Treat the active firmware handlers as the protocol source of truth. Treat the
Python SensorsScreen client as a secondary operational example. If a required
behavior or payload is not documented or verifiable from source, stop and ask
for the missing reference instead of guessing.

Task:
[Describe the behavior the controller should implement.]

Target language and runtime:
[Language, version, operating system, and required libraries.]

Hardware configuration:
[Motor channels, servo channels and types, sensors, wiring, and any mechanisms.]

Network configuration:
- Bot IP: [read from user/configuration at runtime]
- Master token: [prompt securely/read from protected configuration at runtime]
- Transport: [UDP preferred for real-time control, or explain why HTTP is needed]

Requirements:
- Register before master-protected writes and validate registration success.
- Keep a separate heartbeat sender active every 25-30 ms during the session.
- Validate response sender, action, status, and payload length. Handle UDP's
  8-byte diagnostics trailer, PING's response exception, and heartbeat's lack
  of a response.
- Use one socket receive dispatcher if streams and command acknowledgments are
  both consumed. Never let competing receivers steal one another's packets.
- Configure servo types before movement. Use 0x24 for positional angles; 0x2A
  is not implemented.
- On every exit path, best-effort zero each continuous servo configured by the
  client individually, send 0x28 for DC motors, then unregister with 0x42.
  Explain that packet loss prevents a physical safety guarantee.
- Do not replay stale motion after a timeout. Stop or enter a fault state when
  heartbeat or command handling fails.
- Do not send live motion commands unless I explicitly authorize hardware use.

Deliver:
1. Complete, runnable source with setup and invocation instructions.
2. A brief mapping of each used action/payload to the protocol reference.
3. Tests using mocks or loopback for failed registration, malformed or
   unexpected replies, diagnostics trailers, timeouts, and cleanup.
4. Any unresolved assumptions or hardware checks, clearly listed.

Start with an offline test. Do not connect to the live bot or actuate hardware
unless I explicitly authorize that step.
```

This template sets implementation requirements, not a guarantee of physical safety. Review generated code and test it offline before connecting motors or servos.
