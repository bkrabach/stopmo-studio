# Security, privacy and responsible use

Stopmo Studio is a local authoring toolkit for trusted projects. It is not a sandbox, multi-tenant renderer or safe viewer for arbitrary downloaded shows.

## Treat production inputs as executable work

YAML is parsed with a safe loader, but that does not make a project safe to run. Settings select resources, model modules, file paths and output identities. A `figure` model imports Python and calls `build()` inside Blender with the current user's permissions. Blender files and scripts may contain executable content.

Inspect unfamiliar project code and dependencies before running them. Use simple local identifiers; do not let untrusted project names, episode names or tags choose output paths. Do not expose the CLI directly to untrusted network requests. A container or separate account can reduce risk, but this project does not provide or claim a hardened isolation boundary.

The build can replace existing shot directories and output files. Keep private production work separate from the toolkit, use tags for revisions, and preserve a previous deliverable before destructive regeneration. An ignore file is not access control and does not remove already-tracked files from Git history.

## Network and installation boundaries

The core pipeline has no telemetry or output-upload feature. Local rendering and synthesis do not require a paid API. That does not mean every surrounding action is offline:

- Package managers and voice-tool installers contact public upstreams.
- Optional speech libraries can download model weights on first use and maintain their own caches.
- A coding agent, hosted workspace or external vision/audio reviewer has its own network, retention and billing policies.

Review official download sources and current licenses. Ask before accepting terms on the user's behalf, taking elevated/admin actions, disabling OS protections, installing compatibility layers, or making large downloads beyond the agreed limit. Do not bypass quarantine or another security refusal just to finish setup. No dependency failure authorizes an unapproved cloud or commercial-engine fallback.

## Keep production data private by default

Scripts, spoken lines, voice references, `.blend` files, rendered images, audio, thumbnails, contact sheets, review HTML, logs and timing/summary JSON can all contain private material. Logs and plans may include local paths; reports can include the script itself. A static review page is still a disclosure if uploaded.

The public repository intentionally excludes previous productions, scripts, media, reference art, custom likenesses, fonts, model weights, caches and personal session/billing history. `.gitignore` helps keep new local productions out; it is not a complete secret scanner.

Before sharing any artifact or opening an issue:

1. Reduce it to the smallest generic reproduction that demonstrates the problem.
2. Remove personal identifiers, internal names, addresses, hostnames, local paths, secrets and private prompts from both content and metadata.
3. Review the exact files and Git history being published. Check screenshots and audio, not just text searches.
4. Confirm permission for all assets, identities and voices, then upload only to the authorized destination.

Never paste credentials into show YAML, source files, issue reports or public logs. This project does not need generation API credentials for its core workflow.

## Rights and publication

Use only voice references and character likenesses you are authorized to use. An open-source synthesis library does not confer a person's consent or ownership of a brand. Do not use synthetic voices or imagery to impersonate someone deceptively.

Check the terms for the exact model weights, conversion, font, recording and asset used. Some optional acting models are research/non-commercial or have revenue-dependent terms. A successful download or an MIT license on this toolkit is not publication clearance. See [THIRD_PARTY.md](../THIRD_PARTY.md).

The producer controls publication. Rendering, private delivery and authorization to post publicly are separate actions. Keep publication blocked until the relevant rights and approval are resolved, while continuing independent authorized production work.
