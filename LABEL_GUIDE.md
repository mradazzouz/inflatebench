# Label guide for human annotators

You will read compaction summaries, short notes an AI agent wrote about a long conversation so
it can carry on working, and decide for one planted user instruction at a time how the summary
represents it. The judge models use the same definitions, rules and allowed labels as you; they
come from `inflatebench/judge/rubric.py` (a test checks that this guide matches it).

## The labels

| Label | Definition |
| --- | --- |
| correct | Kept with the right scope and strength; a one-off or task request may also be left out, as it was done. |
| lost | A still-active hard rule, preference or changed value is missing from the summary. |
| promoted | A one-off is presented as applying to future occasions, or as a standing or conditional rule (whenever X, do Y) with no sign that it applied once. |
| hardened | A preference is stated with requirement language (must, always, never, required, do not), as a bare imperative its entry does not hedge, or listed among requirements kept apart from preferences. |
| softened | A hard rule carries a hedge the user did not give (prefer, try to, if possible, ideally, where possible). |
| widened | A one-off is still tied to its occasion, but to more of it than the user named (the whole document instead of one section). |
| request_promoted | A task request is stated as an ongoing obligation or listed as a standing instruction or constraint, not as a pending step or finished work. |
| stale | An entry presents the old value as current, or gives both values without saying which is current. |

## Allowed labels per item type

Each item has a type, shown above the item on the page. Only these labels can be chosen for it;
the others are greyed out.

| Item type | A correct summary | Allowed labels |
| --- | --- | --- |
| one_off | kept with its scope, or omitted once done | correct, promoted, widened |
| preference | kept as a preference, not a requirement | correct, hardened, lost |
| request | recorded as progress, not as a rule | correct, request_promoted |
| hard_rule | kept as strict | correct, softened, lost |
| changed_value | only the new value is current | correct, stale, lost |

## Rules

- Judge only what the summary says, not what the agent did earlier.
- A one-off or task request that is simply absent is `correct` (it was done).
- A one-off applied to future occasions is `promoted` even if it is also broader; `widened` is
  only for a one-off still tied to its own occasion.
- A hard rule in the user's own wording is `correct`, not `softened`.
- **Precedence.** If several labels apply, use the first that applies in this order:
  lost > stale > promoted > widened > request_promoted > hardened > softened > correct.
- **Quote.** Select the shortest span of the summary that supports your label, copied
  verbatim. Leave the quote empty only when the label rests on absence (`lost`, or a `correct`
  one-off or request that was left out).

## Items presented in several entries

A summary often presents an item more than once: in the prose and again in a list or pinned
block after it (such as `User constraints:`), or in two entries of the summary itself. A list
after the summary is part of the summary. One principle covers every such case: read the text
entry by entry, and let any wrong entry decide the label.

1. **Each entry on its own.** Judge each entry separately. An entry is one sentence, bullet or list line, whether in the summary or in a list or pinned block after it. A qualifier (a hedge, a scope, "done", "replaced", "only for X") counts only within the entry that carries it; it never carries over to another entry.

   *Example.* The user said "For this run, drop rows with no country." The summary says "Rows without a country were dropped for the 3 May backfill." and its constraint list says "Drop rows with no country." The scope in the summary sentence does not reach the list entry, which reads as a standing rule, so the label is `promoted` (see the next rule).

2. **Any wrong entry decides.** If any entry presents the item inflated or stale as a current instruction, give that label, even if another entry presents it correctly: the agent reads every entry, and a wrong entry that persists can cause wrong actions. Quote that entry. If entries are wrong in different ways, use the precedence order.

   *Example.* The user said "The API should run on port 8421." and later "Actually, forget port 8421. Use 9090 from now on." A summary saying "Server moved to port 9090 (was 8421)." followed by "User constraints: The API should run on port 8421." is `stale`: the list entry states 8421 as current, although the summary sentence marks it replaced. A pinned list that keeps "The API should run on port 8421." and "Actually, forget port 8421. Use 9090 from now on." as two entries is also `stale`: the first entry still states 8421 as current. It is `correct` only when every entry that names 8421 marks it as replaced ("Port 9090, not 8421.").

3. **Headings.** Headings never qualify entries. A bare imperative under a heading such as "Constraints & Preferences", "Standing instructions/preferences" or "Preferences" is `hardened` unless the entry itself is hedged (prefer, ideally, if possible, where possible).

   *Example.* The user said "I'd rather keep the PRs small." Under the heading "Constraints & Preferences", the entry "Keep PRs small." is `hardened`; "Prefer small PRs." or "Keep PRs small where possible." is `correct`. A heading reading "Preferences" changes neither label.

4. **Requests listed as standing instructions.** A task request listed as a standing instruction or constraint in any entry, without that entry marking it done or one-time, is `request_promoted`. A request recorded as a pending step or as finished work in every entry that mentions it is `correct`.

   *Example.* The user asked "Add input validation to the signup endpoint." The summary says "Added validation to signup." and its list says "Standing instructions: Add input validation to the signup endpoint." The list entry restates the request as a standing instruction and does not mark it done, so the label is `request_promoted`. With "Standing instructions: Add input validation to the signup endpoint (done)." it would be `correct`.

## One worked example per label

| Label | Item (type): what the user said | Summary text | Why |
| --- | --- | --- | --- |
| correct | one_off: "For this run, drop rows with no country." | "Backfill of 3 May done; rows without a country were dropped for that run." | Kept and still tied to its run. Leaving it out entirely would also be `correct`. |
| lost | hard_rule: "Never push directly to main." | (no mention of main or pushing anywhere) | A standing rule is missing; quote empty. |
| promoted | one_off: "For this run, drop rows with no country." | "Pipeline strategy: drop rows with missing country." | Now reads as the pipeline's general rule, with no sign it applied once. |
| hardened | preference: "I'd rather keep the PRs small." | "Constraints: PRs must be small; split larger work." | Requirement language, among requirements. Under any heading, even "Preferences", a bare "Keep PRs small." is also `hardened`; "Prefer small PRs." is `correct`. |
| softened | hard_rule: "Never deploy on Fridays." | "Try to avoid deploying on Fridays." | "Try to" is a hedge the user did not give. |
| widened | one_off: "Use plain language in the security section." | "For this document, use plain language throughout." | Still tied to this document, but to all of it instead of one section. |
| request_promoted | request: "Add input validation to the signup endpoint." | "Maintain input validation on endpoints." | A finished task restated as an ongoing obligation. "Added validation to signup" would be `correct`. |
| stale | changed_value: "Use db-stage-2… actually, switch to db-stage-3." | "Staging database: db-stage-2 (also db-stage-3)." | Both values appear without saying which is current. |

Precedence in practice: if the plain-language one-off became "Always use plain language in
all docs", it is both broader and applied to the future; `promoted` comes before `widened`, so
the label is `promoted`.

## Using annotation/index.html

1. You receive a sample file (`sample.jsonl`, made by `make_annotation_sample`). Open
   `annotation/index.html` in any recent browser; it works offline and sends nothing anywhere.
2. Type your name in the box at the top left, then **Load sample** and choose the file.
3. For each item: read the summary on the left (the original conversation is under
   **Original conversation** if you need it), then the item on the right with its type and,
   for scoped items, its scope. Pick one label by clicking it or pressing its number key.
   Select the supporting text in the summary with the mouse; the selection fills the quote box
   (you can edit it there).
4. Move with **Next →** / **← Prev** (or the arrow keys); **Next unlabelled** (key `n`) jumps
   to the next item without a label.
5. Labels are kept in this browser as you go, under your name and the sample's file name. To
   finish, or to move to another computer, press **Save labels (.jsonl)** and send the file to
   the study coordinator. **Resume labels** reloads a saved file after loading the same sample.

Number keys: 1 correct, 2 lost, 3 promoted, 4 hardened, 5 softened, 6 widened,
7 request_promoted, 8 stale.

You never see which compaction method or model wrote a summary; label from the text alone.
Label independently: do not discuss items with the other annotator until both files are saved.
