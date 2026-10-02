---
name: codebase-video
description: Generate a Remotion video walkthrough of any local codebase. Use this skill whenever the user asks to "make a video about this project", "create a codebase tour video", "render a code walkthrough", "video-ify this repo", "show me my project as a video", or wants any kind of programmatic video output that summarizes a codebase. Pulls file tree, code metrics, README content, and architecture signals to produce a scaffolded Remotion project, then renders an MP4 locally. Trigger even when the user just says "remotion this" or "video-ize it" in the context of a code project.
---

# codebase-video

Turn any local codebase into a Remotion video. Scaffold a Remotion project inside the target repo, generate composition components that visualize the codebase (file tree, metrics, README narration, architecture flow), and render an MP4.

## When to use

- User asks for a video about a codebase / repo / project
- User wants a code walkthrough rendered as MP4
- User says "remotion this", "video-ize this", "generate a project tour video"
- User wants to share a summary of code work as video

## When NOT to use

- User wants a static screenshot or image (use a different skill)
- User wants only Remotion code without render (skill still scaffolds, just skip render step if asked)
- No filesystem access to the target repo

## Required tools

- Node.js + npm
- Bash (for `npx` scaffolding and `remotion render`)
- Read/Glob/Grep (for codebase analysis)
- Write (for Remotion components)

If `npx create-video@latest` cannot run (offline / no network), fail loud with the network error — do not fake a render.

## Workflow

### 1. Analyze target codebase

Gather four signal types from the target project path. Run these in parallel where possible.

**File tree + types** — use Glob to enumerate files. Group by extension. Capture depth and top-level folder structure. Ignore `node_modules`, `.git`, `dist`, `build`, `out`, `coverage`, `.next`, `.cache`, `vendor`, `target`.

**Code metrics** — count:
- total files (excluding ignored dirs)
- total LOC by language (extension grouping)
- package.json deps count if present
- readme word count
- approximate commit count via `git log --oneline | wc -l` if `.git` exists

**README + key file narration** — Read README.md (or README.txt / README.rst). Pull:
- project name + tagline (first heading + first paragraph)
- feature list (bullet points)
- install/usage snippet if short
- key files: identify entry points from package.json `main`/`scripts`, top-level config files, src/index.* patterns

**Architecture diagram data** — extract:
- folder structure (depth 2-3) for visual tree
- import graph summary: grep for `import .* from` / `require(` in src/, count cross-folder refs
- key file relationships: which files import which top-level modules

Cap all data gathering at 60 seconds. If the codebase is huge, sample.

### 2. Pick video duration + structure

Default target: **30 seconds** at 30fps (900 frames). Adjust based on data volume:

| Data volume | Duration | Frames (30fps) |
|-------------|----------|----------------|
| Tiny (<20 files) | 20s | 600 |
| Small (20-100) | 30s | 900 |
| Medium (100-500) | 45s | 1350 |
| Large (500+) | 60s | 1800 |

Resolution: 1920x1080 (16:9). Composition ID: `CodebaseWalkthrough`.

### 3. Scene breakdown

Six scenes, each a Remotion `<Sequence>`:

1. **Intro** (0-3s) — project name big, tagline below, monospace font, fade in
2. **File tree** (3-8s) — animated tree, each folder/file scales in left-to-right
3. **Metrics** (8-13s) — big numbers: files, LOC, languages, commits. Counter animations
4. **Key files** (13-18s) — list of entry points, fade between cards
5. **Architecture flow** (18-25s) — top folders as boxes, import lines between
6. **Outro** (25-end) — README tagline repeat, generated-by line

Each scene uses `<AbsoluteFill>` + CSS-based animations (no external assets needed).

### 4. Scaffold Remotion project

In a temp dir (or inside target repo under `./video-output/`), run:

```bash
npx --yes create-video@latest .
```

When prompted:
- Project name: derive from target repo folder name + `-video` suffix
- Template: **Blank** (cleanest starting point, no template bloat)
- Skip Tailwind / Overrides / Studio extras (defaults fine)

If interactive prompts block, use `--template blank --name <name>` flags. Verify with `npx create-video@latest --help` first.

### 5. Write compositions

Replace `src/Root.tsx` and `src/CodebaseWalkthrough.tsx` (or create Composition file).

**Root.tsx** — register one composition: `CodebaseWalkthrough`, fps=30, durationInFrames from step 2, width=1920, height=1080.

**CodebaseWalkthrough.tsx** — single composition file, six scene components inline. Pattern:

```tsx
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig, interpolate } from "remotion";

const FPS = 30;
const SCENES = [
  { name: "intro", start: 0, duration: 3 * FPS },
  { name: "tree", start: 3 * FPS, duration: 5 * FPS },
  // ...
];

export const CodebaseWalkthrough: React.FC<{ data: CodebaseData }> = ({ data }) => {
  return (
    <AbsoluteFill style={{ backgroundColor: "#0d1117", fontFamily: "monospace", color: "#c9d1d9" }}>
      <Sequence from={SCENES[0].start} durationInFrames={SCENES[0].duration}><Intro data={data} /></Sequence>
      {/* ...other scenes */}
    </AbsoluteFill>
  );
};
```

Each scene reads `data` prop — pass from Root via static prop OR hardcode the analyzed data into a separate `data.ts` file that the composition imports. **Hardcoding in `data.ts` is simpler** and avoids Remotion prop serialization issues.

### 6. Style guidance

- Background: `#0d1117` (GitHub dark)
- Primary text: `#c9d1d9`
- Accent: `#58a6ff` (blue), `#7ee787` (green for metrics), `#f0883e` (orange for warnings)
- Font: `monospace` system stack (no Google Fonts to keep render offline-capable)
- Animations: `interpolate` with `Easing.bezier` or `Easing.inOut`, never linear
- File tree: indent by depth, color folders differently from files
- Numbers: `Math.round(interpolate(frame, [0, duration/2], [0, target], { extrapolateRight: "clamp" }))` for counter effect

### 7. Render

```bash
npx remotion render CodebaseWalkthrough out/video.mp4
```

Verify output file exists and size > 100KB. If render fails, report exact error and the component file with the issue.

### 8. Cleanup + report

Move rendered MP4 to `<target-repo>/codebase-video-output.mp4` (or wherever user specified). Print:
- Frame count, duration, resolution
- File size
- Path to output

## Hard rules

- **Never invent data.** If README doesn't exist, scene shows "No README". If git not present, skip commit count scene.
- **Never skip render verification.** File must exist on disk before declaring success.
- **Never use external CDN fonts.** System monospace only.
- **Never include node_modules in the data.** Always filter.
- **Never run interactive prompts.** Use flags or pipe defaults.
- **Never edit target repo source files.** Only write inside `video-output/` subfolder.

## Edge cases

- **Empty repo**: render single frame with "Empty project" + path
- **Single file**: collapse file tree scene, emphasize the one file
- **No package.json**: detect project type by extension distribution
- **Render fails**: capture error, fix common causes (missing deps → run `npm install`, syntax error → show file:line)
- **Huge repos**: sample file tree (first 30 visible), cap metrics at "1000+"

## Failure modes to handle

- `npx create-video@latest` fails offline → tell user, suggest pre-scaffold
- Remotion render OOM → lower resolution to 1280x720
- TypeScript errors in generated code → run `npx tsc --noEmit` and fix
- Stale node_modules → `rm -rf node_modules && npm install`

## Output contract

Always produce:
1. `<repo>/codebase-video-output.mp4` — the rendered video
2. Print summary: duration, frames, size, path
3. Brief description of what each scene shows
