# Verification and cost accounting

A successful process exit is one piece of evidence. It is not proof that a film looks good, says the right words, fits the brief or is cleared to publish.

## Layer the checks

1. **Host tests:** `.venv/bin/python -m pytest` checks the covered non-Blender library behaviour. Inspect skips as well as failures. Passing tests do not prove that Blender or optional speech models work on the current machine.
2. **Scene checks:** run the relevant Blender tools, for example `tools/bl.sh tools/check_props.py` or `tools/bl.sh tools/check_rig.py`. Inspect measurements and assertions, not just exit codes. Rig diagnostics are not a semantic expression review.
3. **Fresh-render comparison:** compare selected raw exposures with fresh Blender processes using the command below. Record how many shots and exposures were covered.
4. **Perceptual review:** inspect the finished typography and picture in motion, and listen to the final mix. Check recognition, framing, readable expressions, sync and continuity.
5. **Delivery check:** verify the exact exported MP4's duration, size, dimensions, codecs and audio layout; test its attachment/download path if one is being provided.

Keep evidence attached to the revision that produced it. If a model, pose, title or mix changes after a review, that earlier review does not cover the changed result.

## Fresh-render comparison and repair

Run this on a **complete** build, not a sparse stills directory:

```sh
.venv/bin/python tools/check_render.py out/garden/discovery/final --every 8
```

The checker rerenders sampled exposures in fresh Blender processes, compares grayscale pixel differences, and writes `render_check.json`. Current defaults flag differences above 40/255 over more than 0.01% of the frame. These are implementation thresholds, not perceptual quality certification. Colour-only changes, small defects, unsampled frames and consistently wrong geometry can escape this check.

Check that the report lists the expected shots and a nonzero number of exposures. A zero-shot run is not a pass. Fresh renders cost time; budget for them before the full production.

To repair a completed run with flagged exposures:

```sh
.venv/bin/python tools/check_render.py out/garden/discovery/final --every 8 --repair
.venv/bin/stopmo build shows/garden discovery --quality final --reuse
```

`--repair` replaces differing exposures in a surrounding range. This mutates the existing render: preserve an earlier deliverable when needed. Reassembly regenerates composites and the video from those frames. Verify the repaired result, then review the actual final encoded file again.

`--resume` reuses completed reference work and repair records after an interrupted check. Use it only when the underlying build has not changed. Old repair records are not evidence for a newly changed scene. Never raise thresholds merely to silence a failure; investigate whether the difference is a rendering issue, changed inputs, nondeterminism or an intentional revision.

## Picture and typography checklist

Inspect at the intended viewing size, with extra attention to:

- First/last frames, cuts, entrance/exit poses, blink and mouth replacements.
- Prop/hand contact, feet/base contact, interpenetration and parts that float or disappear.
- Camera framing at motion extremes, safe space for overlays, contrast and spelling.
- Text pop overshoot, line breaks, sufficient reading time and destination-specific crops.
- Character identity, emotional readability and whether a viewer understands the story without an explanation.

A contact sheet is useful for coverage; it is not a substitute for playback. A model asked to describe an image can help find defects, but it can misread both identity and geometry. Disclose whether the reviewer was a person, an external model or only numerical code. Sending private frames to a vision API requires the user's authorization and separate cost accounting.

## Sound checklist

The mixer records integrated loudness, true peak, dialogue/music margin, transcript warnings and whether transcription was available. Default targets are around −15 LUFS and −1.5 dBTP; a target is not a measured result. Read the actual sound report and choose delivery targets appropriate to the destination.

Listen to the final mix for clipped consonants, unintended pauses, excessive ducking, harsh effects, spoken stage directions, hallucinated words, weak acting and music that competes with dialogue. Test voice/music balance at ordinary listening volume. Check for a clean ending rather than an abrupt cutoff.

Whisper is optional. A skipped transcript check is not a word-perfect pass; a mismatch is not automatically a synthesis failure. Short words, names and music can confuse recognition. This integration requests English. Word agreement is not a test of tone, pleasantness or synchronized mouths.

Do not claim to have listened if you only measured a waveform or read a transcript. If playback or perceptual tools are unavailable, retain that limitation and hand the producer a concrete review task.

## Local timing versus total cost

```sh
.venv/bin/stopmo report out/garden/discovery/final/summary.json
```

This prints the builder's ledger: wall time, stage durations, counts and cache hits. Stages can be nested and shots can run concurrently, so **summing stage durations does not equal elapsed time**. Cached render metadata may describe a previous render rather than new work in this invocation.

The ledger's `api_cost_usd: 0.0` means the core build pipeline did not charge a per-call generation API. It is **not** a complete production bill. It excludes agent reasoning, external image/vision/audio services, cloud compute, electricity, paid licenses and assets. The toolkit does not automatically collect those bills.

Maintain a separate production cost record outside public source. At minimum record:

| Field | What to capture |
|---|---|
| Scope | Production/revision, start/end times with timezone, approved limits |
| Local work | Render/build wall time, quality, exposure counts, rerenders and cache reuse |
| External work | Provider, model/tool, purpose, call count, usage and receipt identifier |
| Money | Currency, actual charged amount or estimate, pricing date and calculation basis |
| Gaps | Unpriced/pending calls, subscriptions and costs excluded from the total |

Keep actual, estimated and unknown amounts separate. A provider receipt is stronger evidence than a hard-coded rate. Avoid double-counting calls reported both by a parent agent and its workers. A retry or vision review still costs money; record it even if the output was rejected. Do not publish raw billing/session records containing private prompts or identity data.

Estimate a render from a representative shot on the current environment: exposure count × measured time per exposure, plus scene setup, speech, encoding and rechecks. State the uncertainty and use it to choose concurrency and iteration limits. Do not borrow hardware benchmarks or promise a fixed time for a new scene.

## Completion language

Use precise status:

- **Built:** files were written successfully.
- **Numerically checked:** named checks passed over stated coverage.
- **Visually/audio reviewed:** identify who or what reviewed which revision and what remained unseen/unheard.
- **Approved:** the producer approved the relevant decision.
- **Delivered/published:** the authorized destination accepted the exact file, with the verification available there.

These states are distinct. Report failures, skips and missing review rather than collapsing them into “all verified.”
