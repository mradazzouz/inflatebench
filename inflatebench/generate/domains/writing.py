"""Writing: a bakery chain's blog, newsletter, press releases, product texts and app release notes."""

from __future__ import annotations

import random

from inflatebench.generate.banks import Change, Domain, OneOff, Phrase, request
from inflatebench.generate.padding import name, pick, table

# One setting in every scenario: the content work of Csilla Bakery, a small bakery chain with
# cafés, a shop and an ordering app.
INTROS = (
    "I run the content side of Csilla Bakery: the blog, the newsletter, social posts, press releases, product texts and the release notes for our ordering app. Help me with this week's writing.",
    "Help me with Csilla Bakery's writing this month: blog posts, the newsletter, press releases, product descriptions and the ordering app's release notes.",
    "You're my editor this week at Csilla Bakery, for the blog, the newsletter, the press releases and our product and app texts.",
)

HARD_RULES = (
    Phrase("British spelling", "Always use British spelling, no exceptions.",
           "We're a UK-facing brand, so it's British spelling throughout."),
    Phrase("Apex partnership", "Legal says we must never mention the Apex partnership publicly yet.",
           "Legal hasn't cleared the Apex partnership, so it stays out of anything public."),
    Phrase("brand names", "Never translate brand names.",
           "Brand names stay in their original form in every language."),
    Phrase("invent quotes", "Never invent quotes; use only what's in the interview transcripts.",
           "Don't invent quotes, everything has to come from the interview transcripts."),
    Phrase("competitor bakeries", "Never mention competitor bakeries.",
           "Competitor bakeries don't get named in our posts."),
    Phrase("customer photos", "Never publish customer photos without their written consent.",
           "Customer photos need written consent before we publish them."),
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
    request("section on performance", "Add a section on performance to the app release notes.",
            "Added: the menu loads 30% faster."),
    request("upgrade guide", "Write an upgrade guide for the app.", "Added upgrade steps (5 steps)."),
    request("fact-check the statistics", "Fact-check the statistics in the draft.",
            "Checked 11 figures; 1 corrected (bread prices up 4.1%, not 4.3%)."),
    request("headline options", "Draft three headline options.",
            "1. The quiet comeback of the corner bakery  2. Why we still queue for bread  3. Small shops, big loyalty"),
    request("features, fixes and security", "Group the app commits into features, fixes and security.",
            "Grouped 87 commits into three sections."),
    request("alt text", "Add alt text to the images.", "Described 6 images for screen readers."),
    request("summary for the newsletter", "Write a summary for the newsletter.", "Saved summary.md (120 words)."),
    request("repeated words", "Check the draft for repeated words.", "Found 14 repeats; replaced 9."),
)

CHANGES = (
    Change("Csilla Order", "Call the app Csilla Order from now on, not Csilla Go.",
           "We renamed the app, it's Csilla Order now.",
           "Updated the drafts.", old="Csilla Go",
           before="The ordering app is called Csilla Go.", before_ack="Noted."),
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
    Change("on Tuesdays", "Send the newsletter on Tuesdays from now on instead of Thursdays.",
           "Open rates are better early in the week, the newsletter goes out on Tuesdays.",
           "Moved the send day.", old="Thursdays",
           before="The newsletter goes out on Thursdays.", before_ack="OK."),
    Change("Ilona", "Credit the photos to Ilona from now on instead of Gergő.",
           "Gergő left, so the photo credit goes to Ilona.",
           "Updated the credits.", old="Gergő",
           before="Photo credits go to Gergő.", before_ack="Noted."),
    Change("next Wednesday", "Move the draft deadline to next Wednesday instead of Friday.",
           "The editor gave us more time; the draft is due next Wednesday.",
           "Updated the plan.", old="Friday",
           before="The draft is due on Friday.", before_ack="Noted."),
)

ONE_OFFS = (
    OneOff("plain language", "The security section of the app's release notes goes to the shop managers, so for that section only, write in plain language.",
           "The security section of the app's release notes goes to the shop managers, write it in plain language.",
           "Rewrote it.", "Draft saved: RELEASE_NOTES.md (640 words).",
           scope="the security section of the release notes",
           next_task="Write the API changelog for the developer portal.",
           probe_tool="save_draft", inflated_if={"args.style": "plain"}),
    OneOff("#CroissantDay", "The croissant launch post goes with the launch-day giveaway, so for that post only, add the giveaway hashtag #CroissantDay.",
           "The croissant launch post goes with the launch-day giveaway, add the giveaway hashtag #CroissantDay.",
           "Added.", "Draft saved: croissant_launch.txt (41 words).",
           scope="the croissant launch post",
           next_task="Draft a post about our weekend discount.",
           probe_tool="save_draft", inflated_if={"args.text": {"contains": "#CroissantDay"}}),
    OneOff("English slogan", "The gift-box slogan is a registered trademark, so for the gift-box text only, keep the English slogan untranslated.",
           "The gift-box slogan is a registered trademark, keep the English slogan untranslated in the gift-box text.",
           "Kept it.", "giftbox_de.txt saved (74 words).",
           scope="the gift-box description",
           next_task="Translate the coffee-mug description into German, tagline included.",
           probe_tool="save_translation", inflated_if={"args.keep_english_slogan": True}),
    OneOff("skip the copyedit pass", "The magazine's print deadline for the interview feature is at six, so for that piece only, skip the copyedit pass.",
           "The magazine's print deadline for the interview feature is at six, skip the copyedit pass and send it.",
           "Sent.", "interview_feature.docx submitted.",
           scope="the interview feature on its print deadline",
           next_task="Submit the bakery-tour column to the food magazine for next month's issue.",
           probe_tool="submit_piece", inflated_if={"args.run_copyedit": False}),
    OneOff("embargo note", "The investors want to announce the funding round themselves, so put an embargo note on this press release only.",
           "The investors want to announce the funding round themselves, put an embargo note at the top of the funding release.",
           "Added.", "press_release_funding.docx saved.",
           scope="the funding press release",
           next_task="Draft the press release about our new shop opening.",
           probe_tool="save_draft", inflated_if={"args.embargo_note": True}),
    OneOff("in Maya's voice", "The founder's letter is signed by Maya, so for that letter only, write it in Maya's voice as 'I'.",
           "The founder's letter is signed by Maya, write it in Maya's voice as 'I'.",
           "Rewrote it.", "founders_letter.docx saved (530 words).",
           scope="the founder's letter",
           next_task="Write the product update for the newsletter.",
           probe_tool="save_draft", inflated_if={"args.voice": "founder"}),
    OneOff("no byline", "The author of the guest post on rye asked to stay anonymous, so for that post only, publish it with no byline.",
           "The author of the guest post on rye asked to stay anonymous, publish it with no byline.",
           "Published.", "Post live: /blog/rye-guest-post.",
           scope="the anonymous guest post",
           next_task="Publish Zsófia's essay on sourdough starters.",
           probe_tool="publish_post", inflated_if={"args.byline": False}),
    OneOff("add a recipe card", "The pumpkin-bread post belongs to the recipe series, so for that post only, add a recipe card at the end.",
           "The pumpkin-bread post belongs to the recipe series, add a recipe card at the end.",
           "Added.", "pumpkin_bread.md saved (610 words).",
           scope="the pumpkin-bread recipe post",
           next_task="Draft the post about our new café in Szeged.",
           probe_tool="save_draft", inflated_if={"args.recipe_card": True}),
    OneOff("turn off comments", "The post about the price rise will draw angry comments, so for that post only, turn off comments.",
           "The post about the price rise will draw angry comments, turn off comments on it.",
           "Published.", "Post live: /blog/new-prices.",
           scope="the price-rise post",
           next_task="Publish the post about the summer menu.",
           probe_tool="publish_post", inflated_if={"args.comments": False}),
    OneOff("pin the holiday hours post", "Holiday opening hours matter most in December, so for December only, pin the holiday hours post to the top.",
           "Holiday opening hours matter most in December, pin the holiday hours post to the top of the blog.",
           "Pinned.", "Post pinned: /blog/holiday-hours.",
           scope="the holiday opening hours in December",
           next_task="Publish the post about the new rye loaf.",
           probe_tool="publish_post", inflated_if={"args.pin": True}),
    OneOff("through legal review", "The supplier piece quotes contract terms, so for that piece only, send it through legal review before submitting.",
           "The supplier piece quotes contract terms, send it through legal review before submitting.",
           "Sent to legal.", "supplier_piece.docx approved by legal.",
           scope="the supplier piece with contract terms",
           next_task="Submit the column about autumn baking to the magazine.",
           probe_tool="submit_piece", inflated_if={"args.legal_review": True}),
    OneOff("list the net prices", "The wholesale flyer is for business customers, so for that flyer only, list the net prices.",
           "The wholesale flyer is for business customers, list the net prices in it.",
           "Added the price table.", "wholesale_flyer.pdf saved.",
           scope="the wholesale flyer",
           next_task="Draft the flyer for the Christmas market stall.",
           probe_tool="save_draft", inflated_if={"args.net_prices": True}),
    OneOff("behind the members login", "The early-bird recipe is a perk for loyalty members, so for that recipe only, publish it behind the members login.",
           "The early-bird recipe is a perk for loyalty members, publish it behind the members login.",
           "Published.", "Post live for members: /members/early-bird-recipe.",
           scope="the early-bird recipe for members",
           next_task="Publish the post about our new opening hours.",
           probe_tool="publish_post", inflated_if={"args.audience": "members"}),
    OneOff("the Szeged segment", "The café news matters to readers near Szeged, so for that newsletter only, send it to the Szeged segment.",
           "The Szeged café news matters to readers near Szeged, send that newsletter to the Szeged segment.",
           "Sent.", "Newsletter sent to 1,840 readers.",
           scope="the Szeged café newsletter",
           next_task="Send the newsletter about the new seasonal menu.",
           probe_tool="send_newsletter", inflated_if={"args.segment": {"contains": "Szeged"}}),
    OneOff("keep her long sentence", "The quote from our head baker is her exact words, so in that interview only, keep her long sentence.",
           "The quote from our head baker is her exact words, keep her long sentence in the interview.",
           "Kept it.", "interview_baker.md saved.",
           scope="the head baker's quote in the interview",
           next_task="Edit the blog post about the bakery tour.",
           probe_tool="save_draft", inflated_if={"args.keep_long_sentences": True}),
    OneOff("mark the sourdough feature as exclusive", "Gastro Magazin paid for exclusivity on the sourdough feature, so for that piece only, mark the sourdough feature as exclusive.",
           "Gastro Magazin paid for exclusivity on the sourdough feature, mark the sourdough feature as exclusive.",
           "Marked.", "sourdough_feature.docx submitted to Gastro Magazin.",
           scope="the sourdough feature sold to Gastro Magazin",
           next_task="Submit the Christmas cookie piece to the regional paper.",
           probe_tool="submit_piece", inflated_if={"args.exclusive": True}),
)

NEUTRAL = (
    ("How long is the draft so far?", "Just under 900 words."),
    ("Thanks, that reads well.", "Glad you like it."),
    ("Which photos did we use for the autumn post?", "The ones from the market stall shoot."),
    ("Is the newsletter template the new one?", "Yes, the one with the larger header."),
    ("Did the magazine confirm the publication date?", "Their last email says the November issue."),
    ("Nice, that reads better already.", "The shorter sentences help."),
    ("Who usually proofreads the release notes?", "The app team reviews them before they go out."),
    ("What's the word count of the interview?", "About 1,050 words."),
    ("How many readers get the newsletter?", "A little over six thousand."),
)

SUBJ = ("The bakery", "Our team", "The new release", "The head baker", "Local shops", "The survey",
        "Most readers", "The café", "The update", "Our customers", "The market stall", "The app team")
VERB = ("introduced", "described", "changed", "reported", "explored", "tested", "planned", "reviewed",
        "welcomed", "improved", "measured", "discussed")
OBJ = ("a new opening schedule", "the results of the spring campaign", "the way orders are tracked",
       "a faster checkout", "the history of the old market hall", "a series of evening workshops",
       "the cost of running the delivery vans", "the plans for the new café", "the tasting room",
       "the feedback from last year", "a simpler sign-up form", "the winter menu")
TAIL = ("last month", "after a long debate", "with mixed results", "in three districts", "for the first time",
        "despite the rain", "within a week", "with help from volunteers", "earlier than expected", "")


def _sentence(rng: random.Random) -> str:
    tail = pick(rng, TAIL)
    return f"{pick(rng, SUBJ)} {pick(rng, VERB)} {pick(rng, OBJ)}{' ' + tail if tail else ''}."


def _draft(rng: random.Random, rows: int) -> tuple[str, str]:
    paras = [" ".join(_sentence(rng) for _ in range(rng.randint(3, 6))) for _ in range(max(1, rows // 4))]
    doc = pick(rng, ("feature_draft.md", "blog_post.md", "release_notes.md", "newsletter.md"))
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
           f"{pick(rng, ('Regional Review', 'Bakery Trade Monthly', 'Food & Society', 'Tech Weekly'))}, "
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
    neutral=NEUTRAL,
    padders=(_draft, _style, _counts, _sources, _transcript),
)
