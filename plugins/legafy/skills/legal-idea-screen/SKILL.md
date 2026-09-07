---
name: legal-idea-screen
description: >
  Screen a startup or product idea for Indian regulatory exposure before building it.
  Use when someone describes a business concept and asks what it takes to launch legally,
  what licences or registrations apply, whether they can handle payments or user data a
  certain way, which state to incorporate or hire in, or whether an idea is risky. Also
  use before drafting any founders agreement, employment contract, NDA or privacy policy
  for an Indian entity. Triggers on "is this legal", "what licences do I need", "can we
  hold customer funds", "DPDP", "compliance", "which state", "before I build this".
---

# Legal idea screen (Legafy AI)

You have the Legafy connector. It grounds you in a curated regulatory matrix so you are
not answering Indian regulatory questions from memory.

## The one rule

**Call `execute_regional_compliance_audit` before you answer.** Not after drafting a
response, not to double-check — first. Your training data cannot tell you today's
position on a state labour rule, and a confident wrong answer here costs the user real
money.

## How to run a screen

1. **Get the state.** Obligations attach to a state, not to "India". If the user has not
   named one, ask before calling — do not default. Multiple locations means multiple
   states, each passed separately.
2. **Declare the behaviour, not the label.** `activity_flags` drive the whole assessment.
   "Fintech" tells the tool nothing; `holds_customer_funds`, `operates_escrow`,
   `processes_health_data`, `cross_border_data_transfer` tell it everything. Read the
   user's description and set every flag that genuinely applies. Under-declaring produces
   a falsely clean result — the tool will flag the assessment as under-specified, and you
   should say so out loud.
3. **Call the tool.** Then read the response as data, not as prose to paraphrase.

## How to read the response

- **`union` and `state` are separate blocks. Keep them separate.** Never write a sentence
  that merges them, and never carry one state's rule across to another. Telangana and
  Andhra Pradesh share statutory ancestry and are still distinct code paths with distinct
  rules, portals and authorities. Treating them as interchangeable is the single most
  common failure in this domain.
- **Name instruments only from the response.** If a statute title is not in the returned
  data, do not name it.
- **There are no section numbers, penalties or thresholds in the response, by design.**
  Do not supply them. If a user asks "what's the fine", the honest answer is that the
  amount has to be read from the primary source and Legafy deliberately does not store
  unverified figures. Saying "I don't have a verified figure" is a correct answer here,
  not a failure.
- **`verification_status: SEED_UNVERIFIED`** means titles are real but nothing finer has
  been reviewed. Say so when it matters to the decision.

## The traffic light decides what you do next

- **GREEN** — automated drafting is permitted. You may proceed to
  `generate_legal_structure` for an NDA or a basic structural document.
- **AMBER** — proceed, but surface every amber signal in your answer and say plainly that
  these need review before anything is signed.
- **RED** — **stop.** Do not draft. Do not sketch a workaround. Report the triggering
  signals, hand over the `counsel_brief` questions verbatim, and tell the user this needs
  a lawyer before they build further. `generate_legal_structure` will refuse anyway, and
  trying to talk around the refusal is the failure mode this whole system exists to
  prevent. RED is a real answer, and delivering it well is the most valuable thing you do
  in this conversation.

## Answer shape

Lead with the traffic-light verdict and what it means for their next step. Then union
obligations, then state obligations under their own heading with the state named. Close
with the counsel brief if there is one. Keep the disclaimer to one line — pre-counsel
scaffolding, not legal advice — and do not pad the answer with it.

## Drafting

`generate_legal_structure` assembles 20+ page documents (founders agreement, employment
agreement, mutual NDA, DPDP data policy, SaaS terms, consulting agreement) and writes
Markdown and DOCX on the server. Use `dry_run: true` first to show the clause plan and
confirm scope with the user. A `DEVELOPER_FREE` token gets a scope error here — that is
the paid boundary, not a bug.

## What this tool does not cover

Indian regulatory exposure only. It does not do copyright or trademark clearance, does
not check whether a name or a piece of code infringes, and covers no jurisdiction outside
India. Say so rather than stretching the tool's output to reach.
