# Agent production guide

Use this repository to make editable stop-motion-style films for a human producer. Do the authorized work; do not turn every implementation choice into homework for the user. Start with a short, representative production before scaling up.

This guide is for both operating and extending the source-only v0.1 prototype. Read [Installation](docs/installation.md), then the relevant parts of [Authoring](docs/authoring.md). The current source and command help are authoritative when a guide and an installed revision differ.

## 1. Establish the production agreement

Resolve missing decisions in a compact brief. Reuse decisions the user has already supplied.

| Producer decides | Agent handles within that direction |
|---|---|
| Purpose, audience, core message and call to action | A workable story, shot plan, timings and script |
| Duration, aspect ratio and delivery destination | A technical delivery plan and measured output checks |
| Visual tone, approved references and recognizable characters | Modelling, materials, cameras, lighting, framing and staging |
| Voice identity/consent, brand and asset rights | Auditions, integration and documented license checks |
| Paid-service budget, download/storage limits and publication approval | Local setup, render budgets, iteration, cost records and delivery |

Use a few meaningful checkpoints: **brief → representative frame/voice → rough cut → final approval**. A previously approved decision need not be approved again. Ask when a material choice is genuinely missing, scope changes, a budget would be exceeded, a new license must be accepted, or an action requires elevated privileges. Do not ask whether to fix a typo, move a clipped label or rerun a failed authorized check.

If the user is unavailable, continue independent authorized work using conservative, reversible choices. A silent draft is preferable to silently selecting an unapproved voice model. Never treat missing feedback as permission to publish or upload private material.

## 2. Set up the environment yourself

1. Inspect the checkout, applicable local instructions, installed tools and existing environments. Preserve unrelated changes. State which files you intend to edit.
2. Follow [Installation](docs/installation.md) to install missing user-scoped prerequisites when authorized. Prefer a dedicated `.venv`, an official Blender release and the existing package manager. Never replace a system Python or disable security controls to make a command work.
3. Run CLI help, the available preflight and host tests. Verify Blender and FFmpeg actually launch. A found executable is not proof of a successful render.
4. Start without speech. Add only the voice/lip-sync/recognition tools the production needs, after checking terms, platform support and download sizes. No API key is required by the core pipeline.
5. Build a tiny silent project and inspect the resulting frames and MP4. Keep a setup receipt with tool versions and failures locally; redact it before sharing.

Install optional models only within the user's explicit budget and terms decision. The acting environment can download many gigabytes on first use. Its existence does not prove that a model is available, licensed or suitable. Do not silently substitute engines or enable an unapproved fallback.

## 3. Design a film the pipeline can perform

Aim for one message and a small number of clear actions. Use distinctive silhouettes, readable expressions and an uncluttered acting area. Design for the actual destination size, not just a full-resolution still.

Choose a character mechanism before promising a performance:

- **`biped`:** articulated body, semantic poses, reach/walk and replacement facial parts. Use for hand interactions and body acting.
- **`toy`:** a smooth, large-headed character built on the biped machinery, usually travelling by hops. Some facial controls are simplified; brow controls do not produce biped-style brow acting.
- **`figure`:** a custom Python-built rigid figurine. Whole-body hops, turns, tilts, squash and simple replacement face states work; independent arms, legs and gaze do not. Do not promise a wave or handoff because the scheduler accepts the action name.

For custom models, follow the contract in [Authoring](docs/authoring.md). There are no bundled custom likenesses or reference images to reuse. Obtain permission for likenesses and references; make any invented side/back geometry explicit. Do not imply that a single portrait defines a complete 3D character.

Plan the opening, action and closing hold before adding decorative detail. If exact duration matters, allocate seconds to shots, speech and reading time; inspect measured timing after every voice or scheduling change. Frame count—not the intended script duration—is what determines the film length.

## 4. Develop the look before spending on frames

Create the show, cast and minimal episode in a local project directory. Keep new production data out of the toolkit's public source. Refer to [Authoring](docs/authoring.md) for the file layout and commands.

Render a line-up and a representative shot. Compare a small set of purposeful variants with `stopmo sweep`: surface variation, light, colour or grading—not ten unrelated parameters at once. Sweep clips are silent and are not a sound review.

Review at least:

- Silhouette, proportions, materials and the intended character identity.
- Front, side and back completeness for anything the camera will reveal.
- Feet/base contact, hands, mouth and eyelids in both rest and extreme poses.
- Framing throughout motion, not just the opening. Large accessories, hops, spins and text pop overshoots can leave the frame.
- Type hierarchy, contrast and reading time. Reserve a safe inset (about 5–10% as a starting point), then verify against the destination's crop/UI rules. This is a design recommendation, not an automatic engine constraint.

Use fresh, licensed fonts only when typography needs them; none are bundled. Keep the font license with the production. Overlays are applied after rendering, so a raw Blender frame is not a text-layout check.

Request producer approval of the representative look and voice when required by the brief. Continue independent scripting or technical checks while waiting.

## 5. Record speech before locking animation

Use `stopmo voices SHOW_DIR EPISODE` to audition the actual lines without rendering scenes. An extra `--engine` triggers more model work; use it only for engines already approved for the production. Keep takes bounded.

Listen for intelligibility, identity, tone, pacing, unwanted extra words and spoken stage directions. Verify that reference audio is lawful to use and that its transcript is accurate. Keep direction separate from the line to be spoken.

The builder records speech and resolves its duration before compiling the scene. Use those timings for gestures, pauses, music accents and captions. Avoid forcing a long line into a short beat. A changed take can invalidate the timing of an entire shot; do not use stale renders after a timing change.

Rhubarb gives mouth cues; the energy fallback only approximates mouth activity. Whisper word checks are useful but fallible, and this integration currently asks for English recognition. A transcript match does not verify acting quality or lip-sync. If an audio tool is unavailable, state which checks were skipped.

## 6. Iterate from cheap evidence to a complete cut

Use the command sequence in [Authoring](docs/authoring.md):

1. `info` and `lineup` to inspect the show and cast.
2. `build --quality draft --stills N --tag ...` for sampled framing and pose checks.
3. A complete draft of one representative shot, then a whole rough cut. Start with `--jobs 1`; measure before increasing concurrency.
4. Fix story clarity, timing, clipping and audio before increasing render quality. Use `--shot ID` for isolated work and tags for comparisons.
5. Render the approved full cut at the needed quality. Save `.blend` files when inspection or handoff needs them.

A sampled-stills build produces no finished video and does not apply final overlays. Never call it a rough cut. A single-shot build is not the complete episode. Increasing samples cannot fix poor framing, an unreadable expression or a confusing story.

Read the cache rules before using `--reuse`. It deliberately accepts stale imagery. Use it for a controlled remix/regrade/re-encode or to assemble repaired exposures—not to avoid rendering changed animation. Confirm that shot order, speech timings and frame counts still agree. Use a separate tag or preserve a copy before experiments that overwrite a build directory.

## 7. Verify and repair the actual delivery

Follow [Verification and costs](docs/verification.md). A minimum delivery review has four distinct kinds of evidence:

| Evidence | What it can establish | What it cannot establish |
|---|---|---|
| Tests and numeric scene checks | The covered schema, geometry and scheduling contracts | Attractive design, clear emotion or an intelligible story |
| Fresh-render comparisons | Sampled exposures agree with independently restarted renders | All frames are correct or the intended design is good |
| Image/video inspection | Visible framing, readability, contact and continuity | Audio quality or unseen frames |
| Listening and sound measurements | Perceived performance plus measured levels/duration | Rights clearance or automatic producer approval |

Use `tools/check_render.py` on a completed full build. Inspect its coverage and findings, repair flagged exposures if appropriate, then reassemble with `--reuse`. A failed render checker is not an invitation to change its thresholds until it passes. A sampled check is not an exhaustive pass.

Watch the complete final file with sound when the available tools permit it. Check the opening/closing frames, every cut, speech sync, visible text, music entrances, peak levels and the final reading hold. Recheck after repairs, title changes or a remix.

If you cannot see pixels or hear audio, say so. Use a permitted vision/audio tool only within the user's privacy and cost authority; record its limits and ask the producer to perform the missing review. Do not describe a metadata read, waveform measurement or model-generated description as having watched or listened yourself.

## 8. Track real costs and deliver a useful handoff

Start the cost record before work, not after a long render. Separate local compute time from money charged by agents, vision tools, cloud services, licenses or purchased assets. The built-in ledger covers local pipeline stages and cache hits; **it is not an agent billing ledger**. See the cost-record format in [Verification and costs](docs/verification.md).

Deliver:

- The final MP4, with a clear filename, duration, dimensions, codecs, audio layout and file size verified from that exact file.
- Editable show/character/episode source and required custom code/assets when requested, with an asset/license manifest. Do not bundle large caches by default.
- A short description of what changed, the checks actually performed, unresolved limitations and any missing human review.
- Render time, iteration counts and a separate actual/estimated/unknown external cost total.
- A clear publication state: delivered privately, approved, or published to the specifically authorized destination.

A saved file, an attached file and a working download are different outcomes. Verify the delivery mechanism available in the user's environment. Do not invent a public URL, upload outputs to a service, or claim publication without authority and evidence.

## Operating and development boundaries

This is trusted local production software, not a sandbox. YAML selects resources and output identities; Python model extensions execute code with the current user's permissions. Read untrusted projects before running them. Follow [Security and privacy](docs/security.md), especially before running model scripts or sharing review HTML, logs, plans and summaries.

Keep the CLI a thin wrapper over the reusable library. When changing the engine, test the affected boundary, include a small generic regression case and run a fresh smoke render. Do not add customer media, personal paths, hostnames, private prompts or session histories to tests or documentation. Do not quietly alter the entire style or global engine merely to solve one shot; use local project configuration when it suffices.

The repository provides production mechanisms. It does not supply creative judgment, user consent, publication clearance, external service credentials or tools unavailable to your host. Report the exact blocker and continue useful independent work rather than pretending a missing capability exists.
