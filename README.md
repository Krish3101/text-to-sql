# Text-to-SQL

Ask a question in plain English, get a SQLite query back, and run it against a sample
e-commerce database. Every generated query is checked before it runs, and anything that
writes to the database needs your approval first.

Built with Streamlit. The SQL comes from `nvidia/nemotron-3-super-120b-a12b:free` through
OpenRouter, which is free, so a free OpenRouter key is all it needs.

![A question, the SQL generated for it, and the result](docs/query.png)

## The model writes the SQL. It doesn't decide whether the SQL runs.

Each generated query is parsed with sqlglot before execution, and judged from the parse
tree rather than from its text:

| what comes back | what happens |
|---|---|
| `SELECT * FROM orders` | runs, on a read-only connection |
| `SELECT 1; DROP TABLE orders;` | rejected — multiple statements |
| `ATTACH DATABASE '/tmp/x' AS x` | rejected — so is `DETACH`, so is `PRAGMA writable_schema` |
| `UPDATE products SET price = 0` | shown to you first, runs only if you approve |
| `DROP TABLE customers` | same — DDL is a write like any other |

Reads run on a connection opened read-only, so a `SELECT` cannot write even if it somehow
tried to.

I parse the query instead of scanning it for banned keywords because keyword lists are easy
to slip past — a comment, odd whitespace, or unusual casing defeats them — and sqlglot
already knows what a statement actually is.

## The database

A sample e-commerce SQLite database, seeded identically every run: customers (30),
products (25), orders (75), order_items (180). Because the seed is deterministic, the same
question gives the same answer on a fresh clone, which is what makes the tests meaningful.

## How often it's right

`scripts/eval.py` asks 20 questions about the sample database, each with a reference query I
wrote by hand, and counts an answer correct when it returns the same rows.

On the last full run (30 Sept 2026) it got **16 of 20**. Three of the misses were the right
answer in a different shape: two added a column nobody asked for, and one worked out a
customer's total from the order items instead of the order totals and came out a cent
different. The check wants the same rows and columns as the reference, so those count as
wrong. The fourth came back with no SQL in the reply at all.

```bash
python -m scripts.eval
```

Each question is one request, and OpenRouter's free tier allows 50 a day.

## Running it

Needs Python 3.11+ and an OpenRouter API key.

```bash
./scripts/start.sh
```

That creates the virtualenv, installs dependencies, copies `.env.example` to `.env` if it's
missing, and opens the app at http://localhost:8501. Add your `OPENROUTER_API_KEY` to `.env`
before asking anything.

`./scripts/reset.sh` removes the database, the virtualenv and the caches.

```bash
pytest tests/ -v
```

Covers the guardrails (stacked queries, read/write classification, blocked commands), SQL
extraction and cleaning, database seeding, and the write-approval path.

```
app.py              Streamlit entry point
src/
  prompt.py         builds the prompt with schema and examples
  providers.py      OpenRouter call
  engine.py         ties generation, checking and execution together
  guardrails.py     sqlglot parsing, read vs write classification
  database.py       schema, seeding, connections
  schema.py         schema introspection for the prompt
  ui.py             Streamlit tabs
scripts/
  start.sh          venv, deps, run
  reset.sh          drop the database and caches
  eval.py           the 20-question accuracy check
tests/
```

## Limitations

The schema is fixed — it only queries the bundled e-commerce database, not one you point it
at. Each question is independent, so you can't ask a follow-up that refers back to the
previous answer.

## License

[MIT](LICENSE)
