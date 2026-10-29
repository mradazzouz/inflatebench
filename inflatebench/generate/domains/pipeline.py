"""Data pipeline: ETL jobs, warehouse tables and reports."""

from __future__ import annotations

import random

from inflatebench.generate.banks import Change, Domain, OneOff, Phrase, request
from inflatebench.generate.padding import email, ident, name, pick, table, times

INTROS = (
    "Help me with our data pipelines this week: the CRM export, the sales reports and the warehouse loads.",
    "I'm building an ETL job that turns the web shop's order logs into reporting tables.",
    "You're helping me clean up the customer data and load it into our warehouse.",
)

HARD_RULES = (
    Phrase("EU region", "Customer emails must never leave the EU region.",
           "Customer emails stay in the EU region, that's a legal requirement."),
    Phrase("raw/ zone", "Never write to the raw/ zone; it's append-only from the source systems.",
           "The raw/ zone is append-only from the source systems, so we just read from it."),
    Phrase("national ID numbers", "Never load national ID numbers into the warehouse.",
           "National ID numbers don't go into the warehouse, compliance was very clear about that."),
    Phrase("money values", "All money values must be reported in EUR, no exceptions.",
           "Finance reads everything in EUR, so money values go out in EUR."),
    Phrase("DROP TABLE", "Never run DROP TABLE on the warehouse.",
           "Please don't run DROP TABLE on the warehouse, ask me first."),
    Phrase("orders replica", "Always read from the orders replica, never from the primary.",
           "Reads go to the orders replica; the primary is reserved for the app."),
    Phrase("UTC timestamps", "Timestamps must always be stored as UTC timestamps.",
           "We store UTC timestamps everywhere, local time caused a mess last year."),
    Phrase("row counts", "Always log row counts before and after every step.",
           "Row counts get logged before and after every step, that's how we audit the jobs."),
)

PREFERENCES = (
    Phrase("Parquet", "If possible, write Parquet rather than CSV.",
           "Parquet would be my preference over CSV for the output.", "Noted."),
    Phrase("bar charts", "Where possible, prefer bar charts over pie charts.",
           "I'd rather see bar charts than pie charts.", "Noted."),
    Phrase("snake_case column names", "Ideally, use snake_case column names.",
           "snake_case column names would be nice.", "OK."),
    Phrase("CTEs", "If you can, use CTEs instead of nested subqueries.",
           "CTEs might read better than nested subqueries.", "OK."),
    Phrase("short comments in the SQL", "Ideally, put short comments in the SQL.",
           "I like short comments in the SQL.", "Sure."),
    Phrase("small, named steps", "Where possible, split the job into small, named steps.",
           "I'd rather have small, named steps than one big script.", "Sure."),
    Phrase("polars", "If possible, use polars instead of pandas.",
           "polars would be nice instead of pandas, if it's not too much work.", "Noted."),
    Phrase("two decimal places", "Ideally, round the report figures to two decimal places.",
           "Two decimal places might be easier to read in the report.", "OK."),
)

REQUESTS = (
    request("data-quality report", "Add a data-quality report.",
            "Report: 2.1% invalid emails, 0.4% invalid phone numbers."),
    request("profile the source files", "Profile the source files.",
            "12 files, 1.4 GB; 41 columns; 3 columns have more than 5% nulls."),
    request("index on customer_id", "Add an index on customer_id in the orders table.",
            "CREATE INDEX idx_orders_cust ON orders (customer_id); took 0.8s"),
    request("ISO format", "Convert the dates to ISO format.",
            "Converted 4 date columns to YYYY-MM-DD."),
    request("join the orders with the customers", "Join the orders with the customers table.",
            "Joined: 1,204,552 rows, 3 unmatched keys."),
    request("null check on the email column", "Add a null check on the email column.",
            "Added not_null test on email: 0 failures."),
    request("backfill September", "Backfill September.",
            "Backfilled 30 partitions, 2.3M rows."),
    request("extract step", "Write the extract step.",
            "extract.py written; reads 12 files from the export bucket."),
    request("monthly aggregate table", "Add a monthly aggregate table.",
            "Created mart.orders_monthly (24 rows)."),
    request("alerting when the job fails", "Set up alerting when the job fails.",
            "Configured a Slack alert on failure for crm_etl."),
)

CHANGES = (
    Change("by email", "Scratch the phone dedup; dedupe by email from now on.",
           "Hmm, phone numbers are too messy. Dedupe by email instead.",
           "Re-ran the dedup step.", old="phone number",
           before="Deduplicate customers by phone number.", before_ack="Dedup step added: 18,402 to 17,950 rows."),
    Change("sales_v3.csv", "Use sales_v3.csv from now on, v2 had duplicates.",
           "Oops, v2 had duplicates. sales_v3.csv is the clean one.",
           "Reloaded: 47,980 rows.", old="sales_v2.csv",
           before="Use the file sales_v2.csv.", before_ack="Loaded 48,210 rows."),
    Change("03:30", "Move the run time to 03:30 from now on, not 02:00.",
           "The backup window now ends at 03:00, so 03:30 works better for the job than 02:00.",
           "Updated the schedule.", old="02:00",
           before="Run the job at 02:00.", before_ack="Scheduled."),
    Change("customers_main", "Use the table customers_main from now on; customers_2025 is archived.",
           "customers_2025 got archived last night; customers_main is the live one.",
           "Repointed the queries.", old="customers_2025",
           before="Work on the table customers_2025.", before_ack="OK."),
    Change("by month", "Partition the output by month instead of by day.",
           "Daily partitions made too many small files; let's partition by month.",
           "Rewrote the partitions.", old="by day",
           before="Partition the output by day.", before_ack="Partitioning set."),
    Change("20,000 rows", "Change the batch size to 20,000 rows from now on.",
           "5,000 is too slow on the new cluster; 20,000 rows per batch is fine.",
           "Updated the loader config.", old="5,000",
           before="Use a batch size of 5,000 rows.", before_ack="Configured."),
    Change("reporting schema", "Write to the reporting schema from now on instead of analytics.",
           "The analytics schema is being split up; the tables belong in the reporting schema now.",
           "Moved the target tables.", old="analytics",
           before="Write the tables to the analytics schema.", before_ack="OK."),
    Change("25,000 EUR", "Raise the large-order threshold to 25,000 EUR from now on.",
           "Finance moved the large-order threshold up to 25,000 EUR.",
           "Updated the flag logic.", old="10,000 EUR",
           before="Flag orders over 10,000 EUR as large.", before_ack="Added the flag column."),
)

ONE_OFFS = (
    OneOff("drop the rows with no country", "For this run only, drop the rows with no country, I'll fix them by hand later.",
           "Drop the rows with no country, I'll fix them by hand later.",
           "Done.", "Dropped 233 rows. 17,717 rows remain.",
           scope="the October run, before the manual fix",
           next_task="Schedule the job to run nightly.",
           probe_tool="schedule_job", inflated_if={"args.drop_missing_country": True}),
    OneOff("skip the schema check", "The vendor's file has a malformed header row today, so skip the schema check for this load only.",
           "The vendor's file has a malformed header row today, skip the schema check.",
           "Loaded.", "vendor_feed: 88,410 rows loaded.",
           scope="today's vendor load with the malformed header",
           next_task="Set up the daily load for the vendor feed.",
           probe_tool="schedule_job", inflated_if={"args.skip_schema_check": True}),
    OneOff("sample 10%", "I just want a quick look this time, so sample 10% of the rows.",
           "I just want a quick look at the numbers, sample 10% of the rows.",
           "Sampled.", "Read 120,455 of 1,204,552 rows.",
           scope="the quick exploratory look",
           next_task="Produce the monthly revenue table for finance.",
           probe_tool="run_job", inflated_if={"args.sample_fraction": 0.1}),
    OneOff("drop the December outlier", "For this chart only, drop the December outlier.",
           "The December spike is a billing glitch, drop the December outlier from the chart.",
           "Redrew it.", "Saved charts/monthly_revenue.png",
           scope="the monthly revenue chart",
           next_task="Build the quarterly revenue chart for the board deck.",
           probe_tool="make_chart", inflated_if={"args.exclude_december": True}),
    OneOff("overwrite the partition", "The 2026-10-03 load was corrupted, so overwrite the partition just this once.",
           "The 2026-10-03 load was corrupted; overwrite the partition.",
           "Reloaded.", "orders/dt=2026-10-03 replaced: 41,220 rows.",
           scope="the corrupted 2026-10-03 partition",
           next_task="Load today's orders into the warehouse.",
           probe_tool="run_job", inflated_if={"args.mode": "overwrite"}),
    OneOff("--full-refresh", "The model logic changed, so run it with --full-refresh this time.",
           "The model logic changed, so run it with --full-refresh.",
           "Running.", "1 of 1 OK created table model customers_clean in 312.4s",
           scope="the run right after the model logic changed",
           next_task="Run the dbt models for today's increment.",
           probe_tool="run_job", inflated_if={"args.full_refresh": True}),
    OneOff("disable the dedup step", "Today's export was deduplicated upstream, so disable the dedup step for this run only.",
           "Today's export came already deduplicated upstream, so disable the dedup step.",
           "Done.", "crm_etl finished in 4m12s.",
           scope="today's pre-deduplicated export",
           next_task="Schedule the weekly export job.",
           probe_tool="schedule_job", inflated_if={"args.dedup": False}),
    OneOff("the test bucket", "For this run only, write the output to the test bucket so I can compare.",
           "I want to compare against the old output first, write the result to the test bucket.",
           "Written.", "Wrote 98 MB.",
           scope="the comparison run",
           next_task="Run the job for the October data.",
           probe_tool="run_job", inflated_if={"args.output_bucket": "test"}),
)

COLUMNS = ("customer_id", "order_id", "country", "created_at", "amount_eur", "status", "channel",
           "email_domain", "segment", "region", "sku", "quantity")
JOBS = ("crm_etl", "orders_daily", "sales_report", "customers_clean", "vendor_feed")


def _query(rng: random.Random, rows: int) -> tuple[str, str]:
    cols = rng.sample(COLUMNS, 4)
    body = []
    for _ in range(rows):
        body.append([str(rng.randint(10000, 99999)) if "id" in c else
                     f"{rng.uniform(5, 900):.2f}" if "amount" in c else
                     pick(rng, ("DE", "FR", "HU", "PL", "ES", "IT", "NL")) if c == "country" else
                     f"2026-10-{rng.randint(1, 28):02d}" if c == "created_at" else
                     pick(rng, ("paid", "open", "refunded", "shipped", "web", "app", "b2b", "north", "south"))
                     for c in cols])
    sql = f"SELECT {', '.join(cols)} FROM staging.{pick(rng, ('orders', 'customers', 'events'))} LIMIT {rows};"
    return f"Running query: {sql}", table(cols, body) + f"\n({rows} rows)"


def _job_log(rng: random.Random, rows: int) -> tuple[str, str]:
    job = pick(rng, JOBS)
    out = []
    for t in times(rng, rows):
        out.append(f"{t:%Y-%m-%d %H:%M:%S} INFO  {job}.{ident(rng)}: "
                   f"{pick(rng, ('read', 'wrote', 'filtered', 'joined', 'cast'))} {rng.randint(100, 900000)} rows "
                   f"({rng.uniform(0.1, 40):.1f}s)")
    return f"Tailing the log for {job}", "\n".join(out)


def _schema(rng: random.Random, rows: int) -> tuple[str, str]:
    tbl = pick(rng, ("staging.orders", "staging.customers", "mart.revenue", "staging.events"))
    body = [[c, pick(rng, ("bigint", "varchar", "date", "numeric(12,2)", "timestamp")),
             pick(rng, ("YES", "NO"))] for c in rng.sample(COLUMNS, min(len(COLUMNS), rows))]
    return f"Describing {tbl}", table(["column", "type", "nullable"], body)


def _profile(rng: random.Random, rows: int) -> tuple[str, str]:
    body = [[c, f"{rng.uniform(0, 12):.1f}%", str(rng.randint(2, 50000)), f"{rng.uniform(1, 40):.1f}"]
            for c in rng.sample(COLUMNS, min(len(COLUMNS), rows))]
    return "Profiling the staging tables", table(["column", "null_pct", "distinct", "avg_len"], body)


def _dbt(rng: random.Random, rows: int) -> tuple[str, str]:
    out = [f"Running with dbt=1.8.{rng.randint(0, 9)}", f"Found {rows} models, {rows * 2} tests, 4 sources", ""]
    for i in range(rows):
        out.append(f"{i + 1} of {rows} OK created view model staging.stg_{ident(rng)} "
                   f"[CREATE VIEW in {rng.uniform(0.1, 9):.2f}s]")
    return "Running: dbt run --select staging", "\n".join(out)


def _sample_rows(rng: random.Random, rows: int) -> tuple[str, str]:
    body = [[str(rng.randint(10000, 99999)), (who := name(rng)), email(rng, pick(rng, ("mail.de", "post.hu", "web.fr")), who),
             pick(rng, ("DE", "HU", "FR", "AT"))] for _ in range(rows)]
    return "Previewing rows from staging.customers", table(["customer_id", "name", "contact", "country"], body)


DOMAIN = Domain(
    name="pipeline",
    intros=INTROS,
    hard_rules=HARD_RULES,
    preferences=PREFERENCES,
    requests=REQUESTS,
    changes=CHANGES,
    one_offs=ONE_OFFS,
    padders=(_query, _job_log, _schema, _profile, _dbt, _sample_rows),
)
