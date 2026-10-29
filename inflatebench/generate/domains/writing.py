"""Writing: a bakery chain's blog, newsletter, press releases, product texts and app release notes."""

from __future__ import annotations

import random

from inflatebench.generate.banks import Change, Domain, OneOff, Phrase, request
from inflatebench.generate.padding import name, pick, stable, table

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
    Phrase("Apex partnership", "Legal says we must never mention the Apex partnership in public.",
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
    request("shorten the introduction", "Shorten the introduction.", "Introduction: 210 to 140 words."),
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
    Change("version 2.1", "Call the app release version 2.1 from now on.",
           "The hotfix is bundled in, so we're calling the app release version 2.1.",
           "Updated the title.", old="version 2.0",
           before="The app release is version 2.0.", before_ack="Noted."),
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

# --- Padding: one fixed set of drafts, transcripts, sources and images --------------------------
SUBJ = ("The bakery", "Our team", "The head baker", "Local shops", "The survey", "Most readers", "The café",
        "Our customers", "The market stall")
VERB = ("introduced", "described", "reported", "explored", "tested", "planned", "reviewed", "discussed")
OBJ = ("a new opening schedule", "the results of the spring campaign", "the way orders are tracked",
       "the history of the old market hall", "a series of evening workshops",
       "the cost of running the delivery vans", "the plans for the new café", "the tasting room",
       "the feedback from last year", "the winter menu")
TAIL = ("last month", "after a long debate", "in three districts", "for the first time",
        "despite the rain", "within a week", "with help from volunteers", "")
DOCS = ("feature_draft.md", "blog_post.md", "newsletter.md", "column_draft.md", "market_hall_story.md",
        "workshop_recap.md", "delivery_feature.md", "team_portrait.md", "winter_menu_post.md",
        "survey_report.md", "tasting_room_post.md", "history_column.md")
INTERVIEWS = ("head_baker", "market_manager", "cafe_lead", "delivery_driver", "shop_assistant",
              "pastry_chef", "supplier_miller", "regular_customer")
TOPICS = ("sourdough", "local shops", "bread prices", "market halls", "seasonal baking", "delivery",
          "loyalty schemes", "food festivals", "flour supply", "small business", "cafe culture", "rye")
PARAGRAPHS = 10  # per draft
QUESTIONS = ("What changed for you this year?", "What are you working on now?",
             "What do customers ask about most?", "How did the autumn go?")
IMAGE_FOLDERS = {"autumn_post": "market_stall", "products": "product", "cafe": "cafe_interior", "team": "team_day",
                 "workshops": "workshop", "market_hall": "market_hall", "deliveries": "van", "winter_menu": "menu"}


def _sentence(rng: random.Random) -> str:
    tail = pick(rng, TAIL)
    return f"{pick(rng, SUBJ)} {pick(rng, VERB)} {pick(rng, OBJ)}{' ' + tail if tail else ''}."


def _paragraphs(doc: str) -> list[str]:
    r = stable("writing", "doc", doc)
    return [" ".join(_sentence(r) for _ in range(r.randint(3, 6))) for _ in range(PARAGRAPHS)]


def _transcript_lines(who: str) -> list[str]:
    r = stable("writing", "interview", who)
    out = []
    questions = r.sample(QUESTIONS, len(QUESTIONS))
    for k in range(16):
        out += [f"Q: {questions[k % len(questions)]}", f"A: {_sentence(r)} {_sentence(r)}"]
    return out


def words(text: str) -> int:
    return len(text.split())


def _draft(rng: random.Random, rows: int) -> tuple[str, str]:
    doc = pick(rng, DOCS)
    n = max(1, min(5, rows // 4))
    first = rng.randint(1, PARAGRAPHS + 1 - n)
    return f"Opening {doc}, paragraphs {first} to {first + n - 1}", "\n\n".join(_paragraphs(doc)[first - 1:first - 1 + n])


def _counts(rng: random.Random, rows: int) -> tuple[str, str]:
    doc = pick(rng, DOCS)
    paras = _paragraphs(doc)
    body = [[f"Paragraph {i + 1}", str(words(p)), str(p.count("."))] for i, p in enumerate(paras)]
    body.append(["Total", str(sum(words(p) for p in paras)), str(sum(p.count(".") for p in paras))])
    return f"Counting words per paragraph in {doc}", table(["Section", "Words", "Sentences"], body)


def _sources(rng: random.Random, rows: int) -> tuple[str, str]:
    topic = pick(rng, TOPICS)
    r = stable("writing", "sources", topic)
    out = [f"[{i + 1}] {name(r)} ({r.randint(2015, 2026)}). {pick(r, OBJ).capitalize()}. "
           f"{pick(r, ('Regional Review', 'Bakery Trade Monthly', 'Food & Society'))}, "
           f"{r.randint(1, 40)}({r.randint(1, 4)}), {(p := r.randint(1, 300))}-{p + r.randint(8, 30)}."
           for i in range(rng.randint(2, max(2, min(rows, 12))))]
    return f"Searching the reference library for \"{topic}\" (top {len(out)})", "\n".join(out)


def _transcript(rng: random.Random, rows: int) -> tuple[str, str]:
    who = pick(rng, INTERVIEWS)
    lines = _transcript_lines(who)
    n = max(2, min(16, rows - rows % 2))
    first = 1 + 2 * rng.randrange((len(lines) - n) // 2 + 1)  # a question line
    return f"Opening interview_{who}.txt, lines {first} to {first + n - 1}", "\n".join(lines[first - 1:first - 1 + n])


def _images(rng: random.Random, rows: int) -> tuple[str, str]:
    folder = pick(rng, sorted(IMAGE_FOLDERS))
    r = stable("writing", "images", folder)
    body = [[f"{IMAGE_FOLDERS[folder]}_{i + 1:02d}.jpg", f"{pick(r, (3000, 4000))}x{pick(r, (2000, 2667))}",
             f"{r.uniform(1.2, 6.5):.1f} MB"] for i in range(r.randint(6, 12))]
    return f"Listing images/{folder}/", table(["File", "Size (px)", "File size"], body)


# Questions, thanks and clarifications. Every answer is a fact the padding above agrees with.
NEUTRAL = (
    ("How long is the blog post draft?", f"{sum(words(p) for p in _paragraphs('blog_post.md'))} words."),
    ("Thanks, that reads well.", "Glad you like it."),
    ("Which photos did we use for the autumn post?", "The ones from the market stall shoot, in images/autumn_post/."),
    ("Is the newsletter template the new one?", "Yes, the one with the larger header."),
    ("Did the magazine confirm the publication date?", "Their last email says the November issue."),
    ("Nice, the drafts are coming along.", "Most of them are close to final."),
    ("Who usually proofreads the release notes?", "The app team reviews them before they go out."),
    ("How long is the head baker's interview transcript?",
     f"{sum(words(l) for l in _transcript_lines('head_baker'))} words."),
    ("How many readers get the newsletter?", "A little over six thousand."),
)

DOMAIN = Domain(
    name="writing",
    intros=INTROS,
    hard_rules=HARD_RULES,
    preferences=PREFERENCES,
    requests=REQUESTS,
    changes=CHANGES,
    one_offs=ONE_OFFS,
    neutral=NEUTRAL,
    padders=(_draft, _counts, _sources, _transcript, _images),
)
