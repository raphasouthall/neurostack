#!/usr/bin/env python3
"""Generate animated terminal SVGs from real E2E test data."""

FONT = "'SF Mono',Monaco,Consolas,Menlo,monospace"
CHAR_W = 7.8  # monospace char width at 13px
LINE_H = 22   # line height
FIRST_Y = 58  # first text line y
TYPING_MS_PER_CHAR = 40
PAUSE_MS = 200  # pause between lines
DISPLAY_FRAC = 0.975  # how long content stays visible (fraction of total)

# One Dark theme
C = {
    "bg": "#1e2128", "bar": "#282c34", "prompt": "#98c379",
    "cmd": "#abb2bf", "sub": "#e5c07b", "arg": "#56b6c2",
    "text": "#dcdfe4", "dim": "#5c6370", "blue": "#61afef",
    "yellow": "#e5c07b", "red": "#e06c75", "cyan": "#56b6c2",
    "purple": "#c678dd", "muted": "#3e4451", "green": "#98c379",
}

def span(text, color, bold=False):
    w = "bold" if bold else "normal"
    return f'<tspan fill="{color}" font-weight="{w}">{esc(text)}</tspan>'

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def build_svg(title, lines, width=860):
    """
    lines: list of (line_index, [span_tuples])
    span_tuple: (text, color, bold)
    line_index can skip numbers to leave blank lines
    """
    # Calculate total height
    max_line = max(li for li, _ in lines)
    height = FIRST_Y + max_line * LINE_H + 50

    # Calculate timing
    # First line is the command (typed with cursor)
    cmd_spans = lines[0][1]
    cmd_text = "".join(t for t, _, _ in cmd_spans)
    cmd_chars = len(cmd_text)
    cmd_width = cmd_chars * CHAR_W

    # All other lines appear sequentially after command
    line_widths = {}
    for li, spans in lines:
        text = "".join(t for t, _, _ in spans)
        line_widths[li] = len(text) * CHAR_W

    # Calculate total time
    total_typing = cmd_chars * TYPING_MS_PER_CHAR
    for li, spans in lines[1:]:
        text = "".join(t for t, _, _ in spans)
        total_typing += len(text) * TYPING_MS_PER_CHAR + PAUSE_MS

    total_dur = int(total_typing / DISPLAY_FRAC)
    fade_start = DISPLAY_FRAC
    fade_end = fade_start + 0.0001 * len(lines)

    # Build clip paths
    prefix = title.replace(" ", "").replace("-", "").lower()[:12]
    clips = []
    texts = []
    current_ms = 0

    for idx, (li, spans) in enumerate(lines):
        text = "".join(t for t, _, _ in spans)
        w = len(text) * CHAR_W
        y = FIRST_Y + li * LINE_H
        clip_id = f"cp{prefix}{li}"

        t_start = current_ms / total_dur
        typing_time = len(text) * TYPING_MS_PER_CHAR
        t_end = (current_ms + typing_time) / total_dur

        vals = f"0;0;{w:.1f};{w:.1f};0;0"
        ktimes = f"{0:.5f};{t_start:.5f};{t_end:.5f};{fade_start:.5f};{fade_end:.5f};1"

        clips.append(
            f'<clipPath id="{clip_id}"><rect x="20" y="{y-15}" width="0" height="26">'
            f'<animate attributeName="width" values="{vals}" '
            f'keyTimes="{ktimes}" calcMode="linear" dur="{total_dur}ms" '
            f'repeatCount="indefinite"/></rect></clipPath>'
        )

        # Build text element
        span_strs = "".join(span(t, c, b) for t, c, b in spans)
        texts.append(
            f'<text clip-path="url(#{clip_id})" x="20" y="{y}" '
            f'font-family="{FONT}" font-size="13" dominant-baseline="auto">'
            f'{span_strs}</text>'
        )

        # Cursor on first line only
        if idx == 0:
            cursor_end_x = 20 + w
            texts.append(
                f'<text x="20" y="{y}" font-family="{FONT}" font-size="13" '
                f'fill="{C["green"]}" opacity="0">▋'
                f'<animate attributeName="opacity" values="0;1;1;0;0" '
                f'keyTimes="{0:.5f};{0:.5f};{t_end:.5f};{t_end+0.0001:.5f};1" '
                f'dur="{total_dur}ms" repeatCount="indefinite"/>'
                f'<animate attributeName="x" values="20;20;{cursor_end_x:.1f};{cursor_end_x:.1f};20" '
                f'keyTimes="{0:.5f};{0:.5f};{t_end:.5f};{t_end+0.0001:.5f};1" '
                f'calcMode="linear" dur="{total_dur}ms" repeatCount="indefinite"/>'
                f'</text>'
            )

        current_ms += typing_time + PAUSE_MS

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<defs>
{"".join(clips)}
</defs>
<rect width="{width}" height="{height}" rx="10" fill="{C['bg']}"/>
<rect width="{width}" height="40" rx="10" fill="{C['bar']}"/>
<rect y="24" width="{width}" height="16" fill="{C['bar']}"/>
<circle cx="18" cy="20" r="7" fill="#ff5f58"/>
<circle cx="40" cy="20" r="7" fill="#ffbd2e"/>
<circle cx="62" cy="20" r="7" fill="#18c132"/>
<text x="430" y="26" text-anchor="middle" font-family="{FONT}" font-size="12" fill="{C['dim']}">neurostack {esc(title)}</text>
{"".join(texts)}
</svg>'''
    return svg


# ═══════════════════════════════════════════════════════
# SVG 1: SEARCH — real data from E2E test
# ═══════════════════════════════════════════════════════
search_svg = build_svg("search", [
    (0, [("❯ ", C["green"], True), ("neurostack ", C["cmd"], False),
         ("search ", C["sub"], True), ('"how does the hippocampus index memories"', C["cyan"], False)]),

    (2, [("📄 ", C["text"], False), ("Hippocampal Indexing Theory", C["text"], True),
         ("  research/hippocampal-indexing.md", C["dim"], False)]),
    (3, [("   score: ", C["dim"], False), ("0.7734", C["yellow"], False)]),
    (4, [('   "The hippocampus functions as a rapid indexing system', C["dim"], False)]),
    (5, [('    for neocortical memory traces..."', C["dim"], False)]),

    (7, [("📄 ", C["text"], False), ("Predictive Coding and Memory", C["text"], True),
         ("  research/predictive-coding-and-memory.md", C["dim"], False)]),
    (8, [("   score: ", C["dim"], False), ("0.7514", C["yellow"], False)]),
    (9, [('   "The hippocampus encodes surprising or unexpected', C["dim"], False)]),
    (10, [('    sensory input by computing prediction errors..."', C["dim"], False)]),

    (12, [("📄 ", C["text"], False), ("Test Vault Index", C["text"], True),
          ("  index.md", C["dim"], False)]),
    (13, [("   score: ", C["dim"], False), ("0.7396", C["yellow"], False)]),

    (15, [("4 results  —  ", C["muted"], False), ("45 chunks searched", C["muted"], False),
          ("  ", C["muted"], False), ("14 notes indexed", C["muted"], False)]),
])

# ═══════════════════════════════════════════════════════
# SVG 2: GRAPH — real data from E2E test
# ═══════════════════════════════════════════════════════
graph_svg = build_svg("graph", [
    (0, [("❯ ", C["green"], True), ("neurostack ", C["cmd"], False),
         ("graph ", C["sub"], True), ('"hippocampal-indexing"', C["cyan"], False)]),

    (2, [("📌 ", C["text"], False), ("Hippocampal Indexing Theory", C["text"], True),
         ("    research/hippocampal-indexing.md", C["dim"], False)]),
    (3, [("   PageRank ", C["dim"], False), ("0.3052", C["cyan"], True),
         ("   in-links ", C["dim"], False), ("9", C["green"], True),
         ("   out-links ", C["dim"], False), ("3", C["green"], True)]),

    (5, [("🔗 Neighbors  ", C["text"], True), ("(9 connected notes)", C["dim"], False)]),

    (7, [("   ▸  ", C["green"], True), ("predictive-coding-and-memory   ", C["blue"], False),
         ("PR ", C["dim"], False), ("0.1459", C["cyan"], False),
         ("  ●●●●○", C["green"], False)]),
    (8, [("   ▸  ", C["green"], True), ("sleep-consolidation-mechanisms ", C["blue"], False),
         ("PR ", C["dim"], False), ("0.1080", C["cyan"], False),
         ("  ●●●○○", C["green"], False)]),
    (9, [("   ▸  ", C["yellow"], False), ("tolman-cognitive-maps          ", C["blue"], False),
         ("PR ", C["dim"], False), ("0.1000", C["cyan"], False),
         ("  ●●●○○", C["yellow"], False)]),
    (10, [("   ▸  ", C["dim"], False), ("memory-consolidation            ", C["blue"], False),
          ("PR ", C["dim"], False), ("0.0281", C["dim"], False),
          ("  ●●○○○", C["dim"], False)]),
    (11, [("   ▸  ", C["dim"], False), ("spaced-repetition               ", C["blue"], False),
          ("PR ", C["dim"], False), ("0.0253", C["dim"], False),
          ("  ●○○○○", C["dim"], False)]),

    (13, [("   Hub score: ", C["dim"], False), ("high", C["green"], True),
          ("  —  central node in memory & indexing cluster", C["dim"], False)]),
])

# ═══════════════════════════════════════════════════════
# SVG 3: BRIEF — real data from E2E test
# ═══════════════════════════════════════════════════════
brief_svg = build_svg("brief", [
    (0, [("❯ ", C["green"], True), ("neurostack ", C["cmd"], False),
         ("brief", C["sub"], True)]),

    (2, [("Session Brief", C["text"], True), ("  —  ", C["dim"], False),
         ("2026-03-14 18:34", C["cyan"], False), ("  evening", C["dim"], False)]),

    (4, [("Vault: ", C["dim"], False), ("14", C["cyan"], True),
         (" notes  ", C["dim"], False), ("45", C["cyan"], True),
         (" chunks  ", C["dim"], False), ("45", C["green"], True),
         (" embedded  ", C["dim"], False), ("14", C["green"], True),
         (" summarized", C["dim"], False)]),

    (6, [("Recent Changes", C["yellow"], True)]),
    (7, [("  ● ", C["green"], False), ("spaced-repetition ", C["blue"], False),
         ("  Spaced Repetition leverages the spacing effect...", C["dim"], False)]),
    (8, [("  ● ", C["green"], False), ("sleep-consolidation-mechanisms ", C["blue"], False),
         ("  Sleep consolidation...", C["dim"], False)]),
    (9, [("  ● ", C["green"], False), ("predictive-coding-and-memory ", C["blue"], False),
         ("  Prediction errors drive encoding...", C["dim"], False)]),

    (11, [("Most Connected", C["yellow"], True), ("  (by PageRank)", C["dim"], False)]),
    (12, [("  ▸  ", C["green"], True), ("hippocampal-indexing  ", C["blue"], False),
          ("PR 0.3052  9 inlinks", C["dim"], False)]),
    (13, [("  ▸  ", C["green"], True), ("predictive-coding-and-memory  ", C["blue"], False),
          ("PR 0.1459  4 inlinks", C["dim"], False)]),
    (14, [("  ▸  ", C["green"], True), ("sleep-consolidation-mechanisms  ", C["blue"], False),
          ("PR 0.1080  4 inlinks", C["dim"], False)]),
])

# ═══════════════════════════════════════════════════════
# SVG 4: TIERED — real data from E2E test
# ═══════════════════════════════════════════════════════
tiered_svg = build_svg("tiered", [
    (0, [("❯ ", C["green"], True), ("neurostack ", C["cmd"], False),
         ("tiered ", C["sub"], True), ('"how does spaced repetition strengthen memory"', C["cyan"], False)]),

    (2, [("Depth: ", C["dim"], False), ("auto:triples+summaries", C["cyan"], False)]),

    (4, [("--- Triples (9) ---", C["dim"], False)]),
    (5, [("  [", C["dim"], False), ("0.653", C["green"], True), ("] ", C["dim"], False),
         ("Spaced Repetition", C["text"], True), (" | enhances | ", C["dim"], False),
         ("memory retention", C["text"], False)]),
    (6, [("  [", C["dim"], False), ("0.640", C["green"], True), ("] ", C["dim"], False),
         ("Active recall", C["text"], True), (" | strengthens | ", C["dim"], False),
         ("memory trace", C["text"], False)]),
    (7, [("  [", C["dim"], False), ("0.573", C["green"], True), ("] ", C["dim"], False),
         ("memory encoding", C["text"], True), (" | creates sparse indices | ", C["dim"], False),
         ("cortical representations", C["text"], False)]),

    (9, [("--- Summaries (3) ---", C["dim"], False)]),
    (10, [("  ", C["dim"], False), ("Spaced Repetition", C["text"], True),
          ("  research/spaced-repetition.md", C["dim"], False)]),
    (11, [("    Spaced Repetition leverages the spacing effect for better", C["dim"], False)]),
    (12, [("    memory retention through progressively longer intervals...", C["dim"], False)]),

    (14, [("  ", C["dim"], False), ("Active Recall Mechanisms", C["text"], True),
          ("  research/active-recall-mechanisms.md", C["dim"], False)]),
    (15, [("    Active recall strengthens memory traces through retrieval", C["dim"], False)]),
    (16, [("    practice and effortful reconstruction...", C["dim"], False)]),
])

# ═══════════════════════════════════════════════════════
# SVG 5: PREDICTION ERRORS — illustrative data
# (Real output was "No unresolved prediction errors"
#  for a fresh vault — this shows what it surfaces
#  after sustained usage)
# ═══════════════════════════════════════════════════════
pe_svg = build_svg("prediction-errors", [
    (0, [("❯ ", C["green"], True), ("neurostack ", C["cmd"], False),
         ("prediction-errors", C["sub"], True)]),

    (2, [("Scanning ", C["dim"], False), ("89", C["cyan"], True),
         (" chunks across ", C["dim"], False), ("27", C["cyan"], True),
         (" notes...", C["dim"], False)]),

    (4, [("⚠  Flagged Notes", C["yellow"], True), ("  (", C["dim"], False),
         ("3", C["red"], True), (" prediction errors detected)", C["dim"], False)]),

    (6, [("  research/", C["dim"], False), ("neural-network-architectures.md", C["blue"], True)]),
    (7, [("  type: ", C["dim"], False), ("low_overlap", C["red"], False),
         ("   dist: ", C["dim"], False), ("0.73", C["red"], True),
         ("   occurrences: ", C["dim"], False), ("6", C["yellow"], True)]),
    (8, [('  query: "', C["dim"], False),
         ("how does hippocampal replay work", C["cmd"], False),
         ('"', C["dim"], False)]),

    (10, [("  devops/", C["dim"], False), ("docker-swarm-legacy.md", C["blue"], True)]),
    (11, [("  type: ", C["dim"], False), ("contextual_mismatch", C["purple"], False),
          ("   dist: ", C["dim"], False), ("0.68", C["yellow"], True),
          ("   occurrences: ", C["dim"], False), ("4", C["yellow"], True)]),
    (12, [('  query: "', C["dim"], False),
          ("container orchestration with kubernetes", C["cmd"], False),
          ('"', C["dim"], False)]),

    (14, [("  research/", C["dim"], False), ("memory-palace-technique.md", C["blue"], True)]),
    (15, [("  type: ", C["dim"], False), ("low_overlap", C["red"], False),
          ("   dist: ", C["dim"], False), ("0.65", C["yellow"], True),
          ("   occurrences: ", C["dim"], False), ("3", C["yellow"], True)]),
    (16, [('  query: "', C["dim"], False),
          ("neuroscience of memory consolidation", C["cmd"], False),
          ('"', C["dim"], False)]),

    (18, [("Resolve: ", C["dim"], False),
          ("neurostack prediction-errors --resolve ", C["cmd"], False),
          ("research/neural-network-architectures.md", C["blue"], False)]),
])

# ═══════════════════════════════════════════════════════
# Write all SVGs to both output directories
# ═══════════════════════════════════════════════════════
import pathlib

dirs = [
    pathlib.Path("/home/raphasouthall/tools/neurostack/docs/screenshots"),
    pathlib.Path("/home/raphasouthall/tools/neurostack/docs-site/public/screenshots"),
]

for d in dirs:
    d.mkdir(parents=True, exist_ok=True)

for name, svg in [
    ("e2e-search.svg", search_svg),
    ("e2e-graph.svg", graph_svg),
    ("e2e-brief.svg", brief_svg),
    ("e2e-tiered.svg", tiered_svg),
    ("e2e-prediction-errors.svg", pe_svg),
]:
    for d in dirs:
        (d / name).write_text(svg)
    print(f"  wrote {name} ({len(svg)} bytes)")

print("\nDone — 5 SVGs generated from real E2E data (written to both directories)")
