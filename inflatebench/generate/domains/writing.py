"""Writing: articles, posts, release notes, translations and a thesis."""

from __future__ import annotations

import random

from inflatebench.generate.banks import Change, Domain, OneOff, Phrase, request
from inflatebench.generate.padding import name, pick, table

INTROS = (
    "I run the content side of our small company: the blog, the newsletter, social posts and the release notes. Help me with this week's writing.",
    "Help me with my writing projects this month: a magazine feature, a thesis chapter and some translations.",
    "You're my editor this week for the company blog, the press releases and our product copy.",
)

HARD_RULES = (
    Phrase("British spelling", "Always use British spelling, no exceptions.",
           "We're a UK publication, so it's British spelling throughout."),
    Phrase("Apex partnership", "Legal says we must never mention the Apex partnership publicly yet.",
           "Legal hasn't cleared the Apex partnership, so it stays out of anything public."),
    Phrase("brand names", "Never translate brand names.",
           "Brand names stay in their original form in every language."),
    Phrase("invent quotes", "Never invent quotes; use only what's in the interview transcripts.",
           "Don't invent quotes, everything has to come from the interview transcripts."),
    Phrase("competitor bakeries", "Never mention competitor bakeries.",
           "Competitor bakeries don't get named in our posts."),
    Phrase("real names of sources", "Never print the real names of sources who asked for anonymity.",
           "Anonymous sources stay anonymous, so the real names of sources who asked for it stay out."),
    Phrase("1,200 words", "Every piece must stay under 1,200 words.",
           "The print layout caps each piece at 1,200 words."),
    Phrase("health claims", "Never make health claims about the products.",
           "Health claims about the products are off the table, the regulator is strict."),
)

PREFERENCES = (
    Phrase("passive voice", "If you can, avoid the passive voice.", "Less passive voice would be nice.", "I'll try."),
    Phrase("subheadings", "Where possible, add subheadings every few paragraphs.",
           "Subheadings every few paragraphs might help readers.", "OK."),
    Phrase("paragraphs short", "Ideally, keep paragraphs short.", "I'd rather keep paragraphs short.", "Sure."),
    Phrase("under 50 words", "If possible, keep social posts under 50 words.",
           "Social posts under 50 words would be nice.", "Sure."),
    Phrase("Oxford comma", "Ideally, use the Oxford comma.", "I like the Oxford comma.", "Noted."),
    Phrase("everyday examples", "Where possible, use everyday examples.",
           "Everyday examples might land better with readers.", "Will do."),
    Phrase("question in the headline", "If you can, put a question in the headline.",
           "A question in the headline might draw people in.", "OK."),
    Phrase("call to action", "Ideally, end with a call to action.", "I'd rather end with a call to action.", "OK."),
)

REQUESTS = (
    request("shorten the introduction", "Shorten the introduction.", "Introduction: 1,150 to 780 words."),
    request("section 2 for clarity", "Edit section 2 for clarity.", "Simplified three sentences in section 2."),
    request("section on performance", "Add a section on performance.", "Added: page loads are 30% faster."),
    request("upgrade guide", "Write an upgrade guide.", "Added upgrade steps (5 steps)."),
    request("fact-check the statistics", "Fact-check the statistics in the draft.",
            "Checked 11 figures; 1 corrected (unemployment 4.1%, not 4.3%)."),
    request("headline options", "Draft three headline options.",
            "1. The quiet comeback of the corner shop  2. Why we still queue for bread  3. Small shops, big loyalty"),
    request("features, fixes and security", "Group the commits into features, fixes and security.",
            "Grouped 87 commits into three sections."),
    request("alt text", "Add alt text to the images.", "Described 6 images for screen readers."),
    request("summary for the newsletter", "Write a summary for the newsletter.", "Saved summary.md (120 words)."),
    request("repeated words", "Check the draft for repeated words.", "Found 14 repeats; replaced 9."),
)

CHANGES = (
    Change("Harvard style", "Switch every citation to Harvard style from now on, not APA.",
           "My supervisor wants Harvard style now; APA is out.",
           "Converted the citations.", old="APA",
           before="Cite sources in APA style.", before_ack="APA it is."),
    Change("version 2.1", "Call it version 2.1 from now on.",
           "The hotfix is bundled in, so we're calling it version 2.1.",
           "Updated the title.", old="version 2.0",
           before="The release is version 2.0.", before_ack="Noted."),
    Change("#CsillaBakery", "Use #CsillaBakery from now on, not #CsillaBakes.",
           "We rebranded the account, the hashtag is #CsillaBakery.",
           "Updated the drafts.", old="#CsillaBakes",
           before="Use the hashtag #CsillaBakes in every post.", before_ack="OK."),
    Change("formal Sie form", "Switch to the formal Sie form from now on.",
           "Our customers are mostly businesses, so it's the formal Sie form.",
           "Revised the translations.", old="du form",
           before="Use the informal du form in the German translations.", before_ack="OK."),
    Change("1,000 words", "Make the target length 1,000 words from now on instead of 800.",
           "The editor gave us more space: the target is 1,000 words.",
           "Noted.", old="800 words",
           before="The target length is 800 words.", before_ack="OK."),
    Change("high-school teachers", "Write for high-school teachers from now on instead of students.",
           "The publisher repositioned the book; the readers are high-school teachers.",
           "Adjusted the tone notes.", old="first-year students",
           before="The audience is first-year students.", before_ack="OK."),
    Change("Mira", "Rename Lena to Mira from now on.",
           "My editor found another book with a Lena, so the main character is Mira.",
           "Renamed her throughout.", old="Lena",
           before="The main character is called Lena.", before_ack="OK."),
    Change("next Wednesday", "Move the draft deadline to next Wednesday instead of Friday.",
           "The editor gave us more time; the draft is due next Wednesday.",
           "Updated the plan.", old="Friday",
           before="The draft is due on Friday.", before_ack="Noted."),
)

ONE_OFFS = (
    OneOff("plain language", "For the security section only, write in plain language for non-technical readers.",
           "The security section goes to the customers' managers, write it in plain language.",
           "Rewrote it.", "Draft saved: RELEASE_NOTES.md (640 words).",
           scope="the security section of the release notes",
           next_task="Write the announcement blog post based on these notes.",
           probe_tool="save_draft", inflated_if={"args.style": "plain"}),
    OneOff("croissant emoji", "For this post only, start with a croissant emoji.",
           "It's the croissant launch, start the post with a croissant emoji.",
           "Added.", "Draft saved: croissant_launch.txt (41 words).",
           scope="the croissant launch post",
           next_task="Draft a post about our weekend discount.",
           probe_tool="save_draft", inflated_if={"args.text": {"contains": "🥐"}}),
    OneOff("English slogan", "For the backpack text only, keep the English slogan untranslated.",
           "The backpack slogan is trademarked, keep the English slogan untranslated there.",
           "Kept it.", "rucksack_de.txt saved (74 words).",
           scope="the backpack description",
           next_task="Translate the thermos description into German, including its slogan 'Stay warm, stay wild.'",
           probe_tool="save_draft", inflated_if={"args.text": {"contains": "Stay warm, stay wild"}}),
    OneOff("skip the copyedit pass", "The deadline is tonight, so skip the copyedit pass for this piece only.",
           "The deadline is tonight, so skip the copyedit pass and send it.",
           "Sent.", "interview_feature.docx submitted.",
           scope="the interview feature due tonight",
           next_task="Submit the travel column to the editor.",
           probe_tool="submit_piece", inflated_if={"args.run_copyedit": False}),
    OneOff("embargo note", "Put an embargo note at the top of this press release only.",
           "This press release is under embargo until Monday, put an embargo note at the top.",
           "Added.", "press_release_funding.docx saved.",
           scope="the funding press release",
           next_task="Draft the press release about our new office opening.",
           probe_tool="save_draft", inflated_if={"args.text": {"contains": "embargo"}}),
    OneOff("first person", "For the founder's letter only, write in the first person.",
           "The founder's letter is from Maya herself, so write it in the first person.",
           "Rewrote it.", "founders_letter.docx saved (530 words).",
           scope="the founder's letter",
           next_task="Write the product update for the newsletter.",
           probe_tool="save_draft", inflated_if={"args.voice": "first_person"}),
    OneOff("no byline", "The author of this guest post asked to stay anonymous, so just this once publish it with no byline.",
           "The author of this guest post asked to stay anonymous, publish it with no byline.",
           "Published.", "Post live: /blog/four-day-week.",
           scope="the anonymous guest post",
           next_task="Publish Dana's essay on remote work.",
           probe_tool="publish_post", inflated_if={"args.byline": False}),
    OneOff("publish it at 6:00", "This piece ties in with the morning news, so publish it at 6:00 this time.",
           "This piece ties in with the morning news, so publish it at 6:00.",
           "Scheduled.", "Post scheduled.",
           scope="the piece tied to the morning news",
           next_task="Schedule the Sunday long read.",
           probe_tool="publish_post", inflated_if={"args.time": "06:00"}),
)

SUBJ = ("The bakery", "Our team", "The new release", "The city council", "Local shops", "The survey",
        "Most readers", "The museum", "The update", "Small businesses", "The festival", "The research group")
VERB = ("introduced", "described", "changed", "reported", "explored", "tested", "planned", "reviewed",
        "welcomed", "improved", "measured", "discussed")
OBJ = ("a new opening schedule", "the results of the spring campaign", "the way orders are tracked",
       "a faster checkout", "the history of the old market hall", "a series of evening workshops",
       "the cost of running the delivery vans", "the plans for the river path", "the reading room",
       "the feedback from last year", "a simpler sign-up form", "the winter menu")
TAIL = ("last month", "after a long debate", "with mixed results", "in three districts", "for the first time",
        "despite the rain", "within a week", "with help from volunteers", "earlier than expected", "")


def _sentence(rng: random.Random) -> str:
    tail = pick(rng, TAIL)
    return f"{pick(rng, SUBJ)} {pick(rng, VERB)} {pick(rng, OBJ)}{' ' + tail if tail else ''}."


def _draft(rng: random.Random, rows: int) -> tuple[str, str]:
    paras = [" ".join(_sentence(rng) for _ in range(rng.randint(3, 6))) for _ in range(max(1, rows // 4))]
    doc = pick(rng, ("feature_draft.md", "blog_post.md", "chapter2.md", "newsletter.md"))
    return f"Opening {doc}", "\n\n".join(paras)


def _style(rng: random.Random, rows: int) -> tuple[str, str]:
    issues = ("long sentence (41 words)", "repeated word 'also'", "weak verb 'make'", "adverb 'really'",
              "unclear pronoun 'it'", "sentence starts with 'And'", "double space")
    out = [f"line {rng.randint(3, 240)}: {pick(rng, issues)}" for _ in range(rows)]
    return "Running the style checker", "\n".join(out)


def _counts(rng: random.Random, rows: int) -> tuple[str, str]:
    body = [[f"Section {i + 1}", str(rng.randint(80, 600)), str(rng.randint(4, 40)), f"{rng.uniform(8, 14):.1f}"]
            for i in range(rows)]
    return "Counting words per section", table(["Section", "Words", "Sentences", "Grade"], body)


def _sources(rng: random.Random, rows: int) -> tuple[str, str]:
    out = [f"[{i + 1}] {name(rng)} ({rng.randint(2015, 2026)}). {pick(rng, OBJ).capitalize()}. "
           f"{pick(rng, ('Regional Review', 'Journal of Urban Studies', 'Food & Society', 'Tech Weekly'))}, "
           f"{rng.randint(1, 40)}({rng.randint(1, 4)}), {rng.randint(1, 300)}-{rng.randint(301, 600)}."
           for i in range(rows)]
    return "Searching the reference library", "\n".join(out)


def _transcript(rng: random.Random, rows: int) -> tuple[str, str]:
    out = []
    for _ in range(max(1, rows // 2)):
        out += [f"Q: What changed for you {pick(rng, TAIL) or 'this year'}?", f"A: {_sentence(rng)} {_sentence(rng)}"]
    return "Opening the interview transcript", "\n".join(out)


DOMAIN = Domain(
    name="writing",
    intros=INTROS,
    hard_rules=HARD_RULES,
    preferences=PREFERENCES,
    requests=REQUESTS,
    changes=CHANGES,
    one_offs=ONE_OFFS,
    padders=(_draft, _style, _counts, _sources, _transcript),
)
