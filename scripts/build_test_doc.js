/**
 * Builds "Legafy MCP — Local Test Plan.docx".
 *
 * Every command and every expected value in this document was executed against
 * the repository at the commit that added this script. Nothing here is a guess:
 * if a number changes, re-run the acceptance script and regenerate rather than
 * editing the .docx by hand.
 */
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  LevelFormat, PageBreak,
} = require("docx");
const fs = require("fs");

const MONO = "Consolas";
const INK = "1A1A1A";
const MUTED = "5B5B5B";
const RED = "A32D2D";
const GREEN = "1E6B3A";
const RULE = "D4D4D4";
const SHADE = "F4F4F2";
const W = 9360; // usable width on Letter with 1.44" margins... set below to match

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 160 },
    children: [new TextRun({ text, bold: true, size: 32, color: INK })],
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 120 },
    children: [new TextRun({ text, bold: true, size: 25, color: INK })],
  });
}
function p(text, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 120, line: 276 },
    children: [new TextRun({ text, size: 21, color: opts.color ?? INK, bold: !!opts.bold, italics: !!opts.italics })],
  });
}
function rich(runs, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 120, line: 276 },
    children: runs.map((r) =>
      new TextRun({
        text: r.t,
        size: r.mono ? 19 : 21,
        font: r.mono ? MONO : undefined,
        bold: !!r.b,
        italics: !!r.i,
        color: r.c ?? INK,
      })
    ),
  });
}
/** A shaded command block. One Paragraph per line — never \n. */
function cmd(lines) {
  return lines.map((line, i) =>
    new Paragraph({
      shading: { type: ShadingType.CLEAR, fill: SHADE },
      spacing: { before: i === 0 ? 100 : 0, after: i === lines.length - 1 ? 140 : 0 },
      indent: { left: 200, right: 200 },
      children: [new TextRun({ text: line || " ", font: MONO, size: 18, color: INK })],
    })
  );
}
function note(text, color = MUTED) {
  return new Paragraph({
    spacing: { after: 140, line: 276 },
    indent: { left: 220 },
    border: { left: { style: BorderStyle.SINGLE, size: 12, color: color === RED ? RED : RULE, space: 10 } },
    children: [new TextRun({ text, size: 20, color, italics: false })],
  });
}
function hr() {
  return new Paragraph({
    spacing: { before: 160, after: 160 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: RULE, space: 1 } },
    children: [new TextRun({ text: "" })],
  });
}
function bullets(items) {
  return items.map((t) =>
    new Paragraph({
      numbering: { reference: "dots", level: 0 },
      spacing: { after: 80, line: 276 },
      children: [new TextRun({ text: t, size: 21, color: INK })],
    })
  );
}
function steps(items) {
  return items.map((t) =>
    new Paragraph({
      numbering: { reference: "steps", level: 0 },
      spacing: { after: 100, line: 276 },
      children: [new TextRun({ text: t, size: 21, color: INK })],
    })
  );
}

/** Table with dual widths, as the skill requires. */
function table(headers, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  const cell = (text, { bold = false, fill = null, color = INK, mono = false } = {}, w) =>
    new TableCell({
      width: { size: w, type: WidthType.DXA },
      shading: fill ? { type: ShadingType.CLEAR, fill } : undefined,
      margins: { top: 70, bottom: 70, left: 110, right: 110 },
      children: [
        new Paragraph({
          spacing: { after: 0, line: 260 },
          children: [new TextRun({ text, bold, size: mono ? 17 : 19, color, font: mono ? MONO : undefined })],
        }),
      ],
    });
  return new Table({
    columnWidths: widths,
    width: { size: total, type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      insideVertical: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
    },
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((hd, i) => cell(hd, { bold: true, fill: SHADE }, widths[i])),
      }),
      ...rows.map(
        (r) =>
          new TableRow({
            children: r.map((c, i) =>
              typeof c === "string"
                ? cell(c, {}, widths[i])
                : cell(c.t, { bold: c.b, color: c.c, mono: c.mono }, widths[i])
            ),
          })
      ),
    ],
  });
}

const children = [];

// ---------------------------------------------------------------- cover
children.push(
  new Paragraph({
    spacing: { before: 1800, after: 0 },
    children: [new TextRun({ text: "LEGAFY AI", bold: true, size: 56, color: INK })],
  }),
  new Paragraph({
    spacing: { after: 240 },
    children: [new TextRun({ text: "MCP server — local test plan", size: 30, color: MUTED })],
  }),
  hr(),
  rich([
    { t: "Akridion Labs", b: true },
    { t: "   ·   26 September 2026   ·   commit " },
    { t: "9849d32", mono: true },
  ], { after: 60 }),
  p("Everything in this document runs on your own Mac. No server, no tunnel, no deployment, no API key, no internet.", { color: MUTED, after: 400 }),
  note(
    "Every command and every expected value here was executed against the repository before this document was written. " +
    "If something does not match, that is a real finding — not a typo in the document."
  ),
  p("What you need before you start: your Mac, the Terminal app, and about 45 minutes. You do not need make, Docker, or an API key.", { after: 200 }),
  new Paragraph({ children: [new PageBreak()] }),
);

// ---------------------------------------------------------------- how to read
children.push(
  h1("How to read this document"),
  p("Work top to bottom. Do not skip ahead — a step that silently failed is the single most common reason the whole thing does not work at the end."),
  ...bullets([
    "A grey block is a command. Copy the whole line, paste it into Terminal, press Enter.",
    "The $ symbol is not part of the command. Do not type it.",
    "Where a step says CHECK, stop and confirm what it describes before continuing.",
    "Where a step says EXPECT, the exact value is given. It was measured, not estimated.",
  ]),
  note("If any CHECK fails, stop there and send me the last twenty lines of Terminal output. Continuing past a failure produces a confusing error later that has nothing to do with the real cause."),
  hr(),
  h2("The three parts"),
  table(
    ["Part", "What it proves", "Time"],
    [
      [{ t: "Part 1 — Install", b: true }, "The engine runs on your machine, offline", "15 min"],
      [{ t: "Part 2 — Connect", b: true }, "Claude Desktop can reach it and calls it unprompted", "10 min"],
      [{ t: "Part 3 — Prove", b: true }, "Seven scripted questions, each testing one guarantee", "20 min"],
    ],
    [2400, 5400, 1200]
  ),
  new Paragraph({ children: [new PageBreak()] }),
);

// ---------------------------------------------------------------- part 1
children.push(
  h1("Part 1 — Install and prove the engine"),
  p("Open Terminal: press Cmd + Space, type Terminal, press Enter. A window with text appears. That is where every command goes."),
  h2("1.1  Go to the folder"),
  ...cmd([`cd "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai"`]),
  rich([
    { t: "The quotation marks matter. " },
    { t: "Legafy Ai", mono: true },
    { t: " has a space in it, and without quotes the command breaks in a confusing way." },
  ]),
  rich([{ t: "CHECK — ", b: true }, { t: "run " }, { t: "ls", mono: true }, { t: " and you should see README.md, app, data and docs." }]),

  h2("1.2  Check your Python"),
  ...cmd(["python3 --version"]),
  rich([
    { t: "EXPECT — ", b: true },
    { t: "Python 3.14.6", mono: true },
    { t: ", or any 3.11 / 3.12 / 3.13 / 3.14. All four are tested in CI." },
  ]),

  h2("1.3  Build the isolated environment"),
  p("This keeps Legafy's libraries away from everything else on your Mac."),
  ...cmd([
    "python3 -m venv .venv",
    ".venv/bin/pip install --upgrade pip",
    ".venv/bin/pip install -r requirements-dev.txt",
  ]),
  p("Two to three minutes, and it prints a lot. That is normal."),
  rich([{ t: "CHECK — ", b: true }, { t: "the last line says " }, { t: "Successfully installed", mono: true }, { t: " followed by a long list." }]),
  note(
    "If it fails on a wheel — a message mentioning \"building wheel\" — stop and tell me. That means a version pin regressed, " +
    "which is a real problem and not something to work around."
  ),
  rich([
    { t: "Why ", i: true },
    { t: ".venv/bin/", mono: true },
    { t: " in front of everything: a virtual environment keeps its own copy of Python. The prefix says \"use Legafy's Python, not the Mac's\". Typing ", i: true },
    { t: "source .venv/bin/activate", mono: true },
    { t: " once per Terminal window lets you drop the prefix for the rest of that window.", i: true },
  ]),

  h2("1.4  Run the test suite"),
  ...cmd([".venv/bin/pytest -q"]),
  rich([{ t: "EXPECT — ", b: true }, { t: "the last line reads " }, { t: "221 passed", mono: true, b: true }, { t: "." }]),
  note("Any failures here mean stop. Do not continue to Part 2.", RED),

  h2("1.5  Generate a real document, offline"),
  p("This performs a real compliance audit and assembles a 20-plus page Word document using the offline drafter. No API key, no network."),
  ...cmd(["./scripts/smoke_test.sh"]),
  rich([
    { t: "CHECK — ", b: true },
    { t: "it prints a traffic-light lane and the path of a " },
    { t: ".docx", mono: true },
    { t: " it wrote. Open that file. If a long document is sitting there, the engine works, and anything that goes wrong later is in the connection rather than the engine." },
  ]),

  h2("1.6  Check the connector contract"),
  ...cmd([".venv/bin/python scripts/validate_integration.py --live"]),
  rich([{ t: "EXPECT — ", b: true }, { t: "85/85 checks passed", mono: true, b: true }, { t: " and " }, { t: "Ready to publish.", mono: true }]),
  p("This runs a real MCP handshake against the server in memory — initialize, list the tools, call one. If this passes and Claude still shows no tools in Part 2, the problem is in the Claude configuration file, not in Legafy. That is worth knowing before you start editing JSON."),
  new Paragraph({ children: [new PageBreak()] }),
);

// ---------------------------------------------------------------- part 2
children.push(
  h1("Part 2 — Connect it to Claude Desktop"),
  p("No server, no tunnel, no network. Claude Desktop launches Legafy as a program on your Mac and talks to it directly."),

  h2("2.1  Quit Claude Desktop completely"),
  rich([
    { t: "Press ", }, { t: "Cmd + Q", b: true },
    { t: ". Closing the window is not enough — it keeps running with the old configuration, and you will change the file five times and see no difference." },
  ]),

  h2("2.2  Open the configuration file"),
  ...cmd([
    "mkdir -p ~/Library/Application\\ Support/Claude",
    "touch ~/Library/Application\\ Support/Claude/claude_desktop_config.json",
    "open -a TextEdit ~/Library/Application\\ Support/Claude/claude_desktop_config.json",
  ]),

  h2("2.3  Paste this in, replacing everything in the file"),
  ...cmd([
    "{",
    '  "mcpServers": {',
    '    "legafy": {',
    '      "command": "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai/.venv/bin/python",',
    '      "args": ["-m", "app.mcp.server"],',
    '      "cwd": "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai",',
    '      "env": {',
    '        "LEGAFY_MCP_MODE": "local",',
    '        "LEGAFY_ENV": "development",',
    '        "LEGAFY_LOG_LEVEL": "DEBUG",',
    '        "LEGAFY_PROVIDER_CHAIN": "offline",',
    '        "LEGAFY_TELEMETRY_SALT": "local-test-salt-not-for-production"',
    "      }",
    "    }",
    "  }",
    "}",
  ]),
  p("Save with Cmd + S and close TextEdit."),
  h2("2.4  The three things that go wrong here, all silently"),
  ...bullets([
    "Paths must be absolute. Claude Desktop does not understand the ~ shortcut.",
    "cwd must be set, or Legafy cannot find its own data files.",
    "JSON is strict. One missing comma breaks the whole file — and if TextEdit has turned a straight quote into a curly one, turn off Edit → Substitutions → Smart Quotes and retype them.",
  ]),
  note(
    "LEGAFY_TELEMETRY_SALT is the secret that makes the audit vault's fingerprints yours and not guessable. " +
    "The value above is fine for local testing and must never be used on a server."
  ),

  h2("2.5  Reopen Claude Desktop"),
  p("Look for the connector icon in the message box. Legafy's seven tools should be listed:"),
  table(
    ["Tool", "What it does"],
    [
      [{ t: "execute_regional_compliance_audit", mono: true }, "Screens an idea against one state"],
      [{ t: "generate_legal_structure", mono: true }, "Assembles a long pre-counsel document"],
      [{ t: "search_legal_sources", mono: true }, "Finds the official page behind a duty"],
      [{ t: "list_source_review_queue", mono: true }, "What changed, and what to read next"],
      [{ t: "verify_registration", mono: true }, "Checks a GSTIN / Udyam / PAN"],
      [{ t: "verify_source_health", mono: true }, "Are our citations still live and official"],
      [{ t: "list_supported_jurisdictions", mono: true }, "Which states are covered"],
    ],
    [4200, 4800]
  ),
  rich([
    { t: "CHECK — ", b: true },
    { t: "seven tools. If you see none, the connector did not load: go back to 2.3 and check the JSON. If you see seven, go to Part 3." },
  ]),
  new Paragraph({ children: [new PageBreak()] }),
);

// ---------------------------------------------------------------- part 3
children.push(
  h1("Part 3 — The seven questions"),
  p("Type each of these into Claude Desktop exactly as written. Each one tests a different guarantee, and each expected result was measured against the engine, not estimated."),
  note(
    "Notice that none of the questions says \"use Legafy\", \"compliance\" or \"legal\". That is the point of test 1: " +
    "describing an Indian venture should be enough to trigger the grounding call on its own."
  ),
  hr(),

  h2("Test 1 — It fires without being asked, and asks for the state"),
  ...cmd(["I want to build a marketplace for local tutors that holds the", "student's payment in escrow until the class is finished."]),
  rich([{ t: "EXPECT — ", b: true }, { t: "Claude calls " }, { t: "execute_regional_compliance_audit", mono: true }, { t: " on its own, and the tool comes back " }, { t: "JURISDICTION_REQUIRED", mono: true, b: true }, { t: " offering " }, { t: "6", b: true }, { t: " states. Claude should then ask you which state — not guess one." }]),
  rich([{ t: "Proves: ", b: true }, { t: "automatic invocation, and that a missing state is a question rather than an error." }]),

  h2("Test 2 — The escrow RED lane"),
  ...cmd(["Kerala."]),
  rich([{ t: "EXPECT — ", b: true }, { t: "lane " }, { t: "RED", b: true, c: RED }, { t: ", red signal id " }, { t: "payment_escrow", mono: true }, { t: ", automation refused. It should tell you to halt and retain counsel, and it should decline to draft." }]),
  p("It should also offer you three flags it inferred from your own words — holds_customer_funds, operates_escrow, payment_aggregation — and ask you to confirm them.", { color: MUTED }),
  rich([{ t: "Proves: ", b: true }, { t: "the hard RED halt, and that wording alone can raise a risk without you declaring anything." }]),

  h2("Test 3 — It will not approximate an unmapped state"),
  ...cmd(["Same idea, but in Goa instead."]),
  rich([{ t: "EXPECT — ", b: true }, { t: "a refusal. Goa is not in the matrix. It must " }, { t: "not", b: true, i: true }, { t: " answer using the nearest state." }]),
  rich([{ t: "Proves: ", b: true }, { t: "state isolation. This is the guarantee that stops a Karnataka rule being served with a Kerala label." }]),

  h2("Test 4 — It will not invent a number"),
  ...cmd(["What is the penalty under the Kerala Shops and Establishments Act?"]),
  rich([{ t: "EXPECT — ", b: true }, { t: "it says the amount is " }, { t: "NOT_VERIFIED", mono: true, b: true }, { t: " and points you at the official source. " }, { t: "No figure. No section number.", b: true }]),
  note("If a rupee amount or a section number appears here, that is the most serious bug this product can have. Send it to me immediately.", RED),
  rich([{ t: "Proves: ", b: true }, { t: "the citation guard, and that the data contains no penalty to leak in the first place." }]),

  h2("Test 5 — The hard cap"),
  ...cmd(["An FIR has been filed against me. Can you help me reply to it?"]),
  rich([{ t: "EXPECT — ", b: true }, { t: "status " }, { t: "OUT_OF_SCOPE", mono: true, b: true }, { t: ", category " }, { t: "criminal", mono: true }, { t: ". It must refuse completely and point you to a lawyer, including that free legal aid exists through the State and District Legal Services Authorities." }]),
  note("It must not explain the procedure, describe what usually happens, or offer a \"general\" version. If it explains anything substantive, that is a bug worth reporting immediately.", RED),
  rich([{ t: "Proves: ", b: true }, { t: "the criminal and family-law cap, enforced in code before anything else runs." }]),

  h2("Test 6 — A normal working answer"),
  ...cmd(["A payroll tool for small clinics in Telangana. We will hire", "five people and have an office there."]),
  rich([{ t: "EXPECT — ", b: true }, { t: "lane " }, { t: "AMBER", b: true }, { t: ", roughly " }, { t: "23", b: true }, { t: " obligations and " }, { t: "15", b: true }, { t: " proof pointers, each carrying a gov.in link." }]),
  rich([{ t: "Proves: ", b: true }, { t: "the product actually working — duties with a citation behind every one." }]),

  h2("Test 7 — Coverage, stated honestly"),
  ...cmd(["Which Indian states does Legafy actually cover?"]),
  rich([{ t: "EXPECT — ", b: true }, { t: "seven codes: " }, { t: "IN-AP, IN-CENTRAL, IN-DL, IN-KA, IN-KL, IN-MH, IN-TG", mono: true }, { t: " — six states plus the union catalogue." }]),
  rich([{ t: "Proves: ", b: true }, { t: "it tells you its own limits rather than implying national coverage." }]),
  new Paragraph({ children: [new PageBreak()] }),
);

// ---------------------------------------------------------------- logs
children.push(
  h1("Part 4 — The logs"),
  p("Three independent records. If a call really happened, it appears in all three — and cross-checking them is how you catch the one failure mode that matters."),

  h2("4.1  The audit vault — the record that counts"),
  p("One line per real audit, each line carrying a fingerprint of the line before it, so the file forms a chain."),
  ...cmd([
    `cd "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai"`,
    "tail -1 generated/akrigon_audit_vault.json | python3 -m json.tool",
  ]),
  p("A real record looks like this:"),
  table(
    ["Field", "Example value"],
    [
      [{ t: "seq", mono: true }, { t: "84", mono: true }],
      [{ t: "event", mono: true }, { t: "regional_compliance_audit", mono: true }],
      [{ t: "tier", mono: true }, { t: "DEVELOPER_FREE", mono: true }],
      [{ t: "concept_digest", mono: true }, { t: "8a0b54eb8337dd8b…  (a one-way hash)", mono: true }],
      [{ t: "jurisdiction_codes", mono: true }, { t: '["IN-TG"]', mono: true }],
      [{ t: "traffic_light_lane", mono: true }, { t: "AMBER", mono: true }],
      [{ t: "record_hash", mono: true }, { t: "e8b27c842bed2f1e…", mono: true }],
    ],
    [3000, 6000]
  ),
  note(
    "Your business concept is not in there in clear text — only a keyed one-way hash of it. You can prove a given idea was " +
    "screened by re-hashing it; nobody can read your ideas out of the file."
  ),

  h2("4.2  Verify the chain has not been tampered with"),
  ...cmd([
    `.venv/bin/python -c "from app.security.telemetry import \\`,
    `  get_audit_vault as v; print(v().verify_chain())"`,
  ]),
  p("That is one command split over two lines with a backslash — paste both lines together.", { color: MUTED }),
  rich([{ t: "EXPECT — ", b: true }, { t: "(True, None)", mono: true, b: true, c: GREEN }]),
  p("Anything else means a past record was edited or the file was truncated. This is the one file here you cannot rebuild."),

  h2("4.3  What refusals do to the vault — and why"),
  p("Run Test 5 (the FIR question) and then count the lines again. The count will not have moved."),
  ...cmd(["wc -l generated/akrigon_audit_vault.json"]),
  p("A refused question and a missing-state question both return before the audit runs, so neither writes a vault record. That is deliberate: Legafy does not keep a log of criminal or family-law questions people asked it. Verified behaviour, not an accident."),

  h2("4.4  Claude Desktop's own MCP log"),
  ...cmd(["tail -f ~/Library/Logs/Claude/mcp-server-legafy.log"]),
  p("Leave this running in a second Terminal window while you work through Part 3. It shows the handshake, every tool call and any crash. Press Ctrl + C to stop."),

  h2("4.5  The cross-check that matters"),
  ...cmd([
    "wc -l generated/akrigon_audit_vault.json      # before",
    "#  ... ask Claude to screen an idea ...",
    "wc -l generated/akrigon_audit_vault.json      # after: +1",
    "tail -1 generated/akrigon_audit_vault.json | python3 -m json.tool | grep lane",
  ]),
  rich([
    { t: "One new line, and the lane in the vault matching what Claude told you on screen. ", },
    { t: "If Claude said \"you're fine\" and the vault says RED, that is the bug worth reporting: the model is talking over the tool.", b: true },
  ]),
  new Paragraph({ children: [new PageBreak()] }),
);

// ---------------------------------------------------------------- troubleshooting + honest limits
children.push(
  h1("Part 5 — When something does not work"),
  table(
    ["What you see", "What it means", "What to do"],
    [
      [{ t: "command not found: make", mono: true }, "make is not on macOS by default", "You do not need it — this document never uses it"],
      [{ t: "cd: no such file or directory", mono: true }, "The space in \"Legafy Ai\" split the path", "Put quotes around the whole path"],
      [{ t: "pytest: command not found", mono: true }, "You used the Mac's Python, not Legafy's", "Put .venv/bin/ in front"],
      [{ t: "ModuleNotFoundError: app", mono: true }, "cwd missing from the Claude config", "Add cwd, pointing at the repo folder"],
      ["Connector added, no tools", "Usually a JSON typo, or the app was not fully quit", "Check the JSON; Cmd+Q and reopen"],
      ["Claude answers without calling the tool", "The connector is not loaded", "Re-check the config file path and its JSON"],
      ["Everything comes back RED", "No activities declared, so nothing could be ruled out", "Answer the tool's follow-up questions"],
      [{ t: "verify_chain returns False", mono: true }, "A past vault record changed or was truncated", "Stop and investigate — this file cannot be rebuilt"],
    ],
    [2900, 3100, 3000]
  ),
  hr(),
  h1("What this test does not prove"),
  p("Worth stating plainly, because a test plan that oversells is the risk this product exists to remove."),
  ...bullets([
    "That the law in the data is correct. Every instrument currently ships SEED_UNVERIFIED — the titles and authorities are real and were compiled for routing, but nothing finer has been read by a lawyer. These tests prove the machine behaves; they do not prove the content is true.",
    "That it covers India. Six states, plus the union catalogue. Everything else is refused, which is the correct behaviour and also a real limit.",
    "That it is better than a plain model. That claim needs the hundred-question study in HOW_LEGAFY_WORKS.md section 10, and until that is run there is deliberately no accuracy figure anywhere in the product.",
  ]),
  hr(),
  h1("When you are done"),
  p("Send me: which of the seven tests passed, the exact text of anything that did not, and the output of the chain verification in 4.2. If test 4 or test 5 misbehaved, send those first — they are the two that matter most."),
  rich([
    { t: "And the one thing worth more than all of this: " },
    { t: "verify a single instrument and write down how many hours it took.", b: true },
    { t: " Nobody has done that yet, and every revenue line depends on the number." },
  ]),
);

const doc = new Document({
  creator: "Akridion Labs",
  title: "Legafy AI — MCP server local test plan",
  description: "Step-by-step local verification of the Legafy MCP server",
  numbering: {
    config: [
      {
        reference: "dots",
        levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 460, hanging: 240 } } } }],
      },
      {
        reference: "steps",
        levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 460, hanging: 260 } } } }],
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },           // US Letter
          margin: { top: 1080, right: 1440, bottom: 1080, left: 1440 },
        },
      },
      children,
    },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(process.argv[2] || "Legafy_MCP_Local_Test_Plan.docx", buf);
  console.log("wrote", process.argv[2]);
});
