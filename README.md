# Lumen — RAG Data Analytics Assistant

An end-to-end AI analytics workspace. Upload a business dataset (CSV or Excel), ask
questions in plain English, and get **data-backed answers** — numbers computed with
pandas, an automatic chart, and a full evidence trail showing exactly how each figure
was produced.

This is deliberately **not a chatbot wrapped around a spreadsheet**. The language model
does two narrow jobs: it turns a question into a structured analysis plan, and it
explains the result once pandas has computed it. Every number in every answer comes from
a real aggregation over the real dataset.

**Stack:** React (Vite) · FastAPI · pandas · Plotly · ChromaDB · Groq

---

## The core idea

```
Upload  →  Validate & clean  →  Profile  →  Build metadata documents
                                                    ↓
                                         Embed into ChromaDB
                                                    ↓
Question  →  Retrieve context  →  LLM plans (JSON)  →  Pandas executes
                                                    ↓
                          Answer + Chart + Evidence trail
```

**Why a plan instead of generated code?** The LLM emits a validated JSON object
describing the analysis — intent, metric, aggregation, grouping columns, filters, sort,
limit, chart type. A deterministic executor runs it. That means:

- No model-written code is ever executed.
- Every column name is validated against the real schema before use.
- The same question always produces the same number.
- The exact operation can be shown to the user as evidence.

If the model is unreachable or the API key is missing, a rule-based planner takes over,
so the app still answers totals, rankings, trends and distributions.

---

## Architecture

```
Browser (React SPA)                   Python backend (FastAPI)
┌──────────────────────┐              ┌────────────────────────────────┐
│ Conversation         │  POST /ask   │ answer.py   orchestration      │
│ Dashboard            │─────────────▶│ planner.py  question → plan    │
│ Explorer             │              │ analysis.py plan → numbers     │
│ Retrieval inspector  │◀─────────────│ charts.py   → Plotly JSON      │
│ Evidence drawer      │   JSON       │ vectorstore.py ChromaDB        │
└──────────────────────┘              └────────────────────────────────┘
```

Charts are built with Plotly **in Python**, serialised to JSON, and re-themed in the
browser to match the active light/dark palette. The chart type is chosen by the analysis
engine, so the visualisation always matches the operation that actually ran.

The built client lives in `web/dist` and is served by FastAPI, so **the target machine
needs Python only** — Node.js is required at build time, not at run time.

---

## Features

**Ingestion & cleaning**
- CSV, TSV, Excel (multi-sheet), and PDF reports as extra RAG context
- Delimiter sniffing, encoding fallbacks, column-name tidying
- Numbers hidden behind `$`, `,`, `%` and `(123)` negatives are recovered
- Date parsing, duplicate removal, empty-column dropping — all logged and shown

**Automatic profiling**
- Every column is classified as **metric**, **dimension**, **date**, **identifier** or **text**
- Identifiers (`Row ID`, `Postal Code`) are never summed; fractions (`Discount`) are averaged
- Dimensions are ranked by how useful they are to group by, so the first chart is a good one
- Per-column statistics, missing-value counts, IQR outlier counts, cardinality
- Derived business metrics detected automatically (Profit Margin %, Average Selling Price)

**RAG layer (ChromaDB)**
- The vector store holds *descriptions*, never raw rows: a data dictionary, one card per
  column, statistical summaries, business definitions, the cleaning log, and any PDF
  reports you add
- Embeddings via Chroma's built-in ONNX `all-MiniLM-L6-v2` — runs locally, no second API
  key, no PyTorch
- A keyword (TF-IDF) fallback index keeps the app working if Chroma cannot start

**Analytics engine**
- Intents: `aggregate`, `topn`, `trend`, `distribution`, `relationship`, `correlation`, `rows`, `describe`
- Aggregations: sum, mean, median, count, min, max, nunique
- Filters: `== != > < >= <= in "not in" contains between`, with fuzzy category matching
  (asking for "west" finds `West`)
- Time grains: day / week / month / quarter / year, with period-over-period change
- Ratio metrics aggregated correctly (`sum(Profit) / sum(Sales)`, never the mean of row ratios)
- Comparisons ("18.5% ahead of East") are computed in Python and handed to the narrator,
  so it never estimates them
- Anomaly detection: monthly z-scores on the headline metric

**Interface**
- **Assistant** — conversation with follow-up support, inline charts, per-answer actions
- **Pipeline indicator** — shows Retrieve → Plan → Compute → Explain while a question runs
- **Evidence drawer** — a slide-over with the operation, the validated JSON plan, the
  columns and filters used, and every retrieved chunk with its similarity score
- **Dashboard** — KPI cards, an executive summary with its computed facts, automatic charts
- **Explorer** — cleaned data, raw upload, column profile, data-quality view
- **Retrieval** — query the vector store directly and browse the indexed corpus
- Light and dark themes, command palette (<kbd>Ctrl/Cmd</kbd>+<kbd>K</kbd>), collapsible
  rail (<kbd>Ctrl/Cmd</kbd>+<kbd>\</kbd>), drag-and-drop upload, keyboard-first navigation

---

## Quick start

### Windows (easiest)

Double-click **`run.bat`**. It creates a virtual environment, installs the Python
dependencies, downloads the example dataset and starts the app at
<http://localhost:8000>. Node.js is not needed — the client is already built.

### Any platform

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
python data/fetch_data.py
cp .env.example .env            # copy on Windows
python -m server
```

Then open <http://localhost:8000>.

### API key

Get a free key at <https://console.groq.com/keys> and put it in `.env`:

```
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=openai/gpt-oss-120b
CHROMA_DIR=.chroma
```

The app runs without a key — it falls back to the rule-based planner and a deterministic
narrator — but the natural-language understanding is much weaker. The sidebar badge shows
`live` or `local` so you always know which path answered.

> Groq retires models regularly. If the configured model 404s, the client automatically
> walks a fallback list. `GET /api/models` lists what the key can actually use.

---

## Development

Working on the React client needs Node.js 18+:

```bash
# Terminal 1 - API with auto-reload
python -m server --reload --port 8000

# Terminal 2 - Vite dev server with hot reload, proxying /api to :8000
cd web
npm install
npm run dev          # http://localhost:5173
```

On Windows, `dev.bat` starts both.

When you are done, rebuild the client so the Python-only launcher picks up the changes:

```bash
cd web && npm run build
```

`web/dist` is committed on purpose — that is what makes the project runnable without Node.

---

## Using it

1. **Sidebar** — upload a file (or drag one in), or click *Try the Superstore example*.
   Filter by date range and up to five categorical columns; every view respects the filters.
2. **Assistant** — ask questions. Follow-ups work: the last few turns are sent to the
   planner, so *"and for the West region?"* resolves correctly.
3. **Evidence** — on any answer, open the drawer to see the operation, the JSON plan, the
   rows analysed and the retrieved context.
4. **Dashboard** — KPI cards, executive summary, automatic charts, flagged anomalies.
5. **Explorer** — what was uploaded, what cleaning changed, how each column was classified.
6. **Retrieval** — query the vector store and browse every indexed chunk.

### Questions that work

```
What were our total sales?
Which region generated the highest profit?
What are the top 10 customers by revenue?
How did sales change month by month?
Which region has the highest profit margin?
Compare sales in 2017 with 2016
Show me the distribution of discount
What is the relationship between sales and profit?
Which sub-category loses the most money?
Which state has the worst profit margin in the Consumer segment?
```

---

## API

The backend is a normal REST API — interactive docs at <http://localhost:8000/docs>.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Status, model, configured samples |
| `GET` | `/api/models` | Chat models this key can use |
| `POST` | `/api/datasets/upload` | Upload CSV/Excel, returns profile + cleaning report |
| `POST` | `/api/datasets/sample/{name}` | Load a bundled example |
| `GET` | `/api/datasets/{id}/filters` | Filterable columns and date bounds |
| `POST` | `/api/datasets/{id}/rows` | Paged rows (raw or cleaned, filtered) |
| `POST` | `/api/datasets/{id}/overview` | KPIs, charts, anomalies |
| `POST` | `/api/datasets/{id}/summary` | Executive summary + the facts behind it |
| `POST` | `/api/datasets/{id}/ask` | **The main endpoint**: answer, chart, evidence |
| `POST` | `/api/datasets/{id}/retrieve` | Query the vector store |
| `GET` | `/api/datasets/{id}/documents` | The full indexed corpus |
| `POST` | `/api/datasets/{id}/context/pdf` | Add a PDF report to the index |

---

## Example dataset

`data/superstore.csv` — the classic **Sample - Superstore** retail dataset: 9,994 US order
lines from 2014–2017 with `Sales`, `Profit`, `Quantity`, `Discount` across `Region`,
`Category`, `Sub-Category`, `Segment`, `State` and `Customer`.

It is downloaded from a public GitHub mirror by `data/fetch_data.py`, not generated. That
script also fetches a second, differently-shaped supermarket dataset so you can verify the
profiler adapts to an unfamiliar schema.

```bash
python data/fetch_data.py
```

---

## Project layout

```
run.bat                 One-click Windows launcher (Python only)
dev.bat                 Development mode (API + Vite, needs Node)
requirements.txt
.env.example
test_pipeline.py        End-to-end smoke test, no web server needed

server/
  __main__.py           python -m server
  api.py                FastAPI routes + serves the built client
  store.py              In-memory dataset registry
  schemas.py            Analytics objects → JSON (NaN-safe, Plotly encoding)

src/                    The analytics core - no web framework imports
  config.py             Environment and constants
  ingestion.py          File reading, validation, cleaning, PDF extraction
  profiling.py          Column role classification, statistics, anomalies
  metadata.py           Profile → RAG documents, business glossary, planner schema
  vectorstore.py        ChromaDB wrapper + keyword fallback index
  llm.py                Groq client: model fallbacks, JSON mode, reasoning stripping
  planner.py            Question → AnalysisPlan (LLM) + rule-based planner
  analysis.py           Plan validation and execution - all real numbers happen here
  charts.py             Plotly chart selection and rendering
  answer.py             Orchestration, narration, executive summary

web/
  src/
    App.jsx             Shell, routing, global state
    api.js              Typed fetch wrapper
    styles.css          Design system (tokens, light + dark)
    components/
      Rail.jsx            Sidebar: source, schema, filters
      Conversation.jsx    Thread, composer, answer cards
      Pipeline.jsx        Retrieve → Plan → Compute → Explain indicator
      EvidenceDrawer.jsx  Provenance slide-over
      Dashboard.jsx       KPIs, summary, automatic charts
      Explorer.jsx        Data, schema and quality views
      Retrieval.jsx       Vector store inspector
      Chart.jsx           Plotly host, lazy-loaded and theme-aware
      CommandPalette.jsx  Ctrl/Cmd+K
      Primitives.jsx      Markdown, tables, chips, toasts
      Icons.jsx           Hand-rolled icon set
  dist/                 Built client - committed so Python alone can serve it

data/
  fetch_data.py         Downloads the example datasets
  superstore.csv
```

---

## Verifying it works

```bash
python test_pipeline.py
```

Runs the whole pipeline headlessly: ingestion, profiling, KPIs, vector store build and
query, anomaly detection, the rule-based planner, then nine real questions through the
full Groq path, printing the plan, the operation, the computed table and the narrative for
each. It asserts that `Sales`/`Profit`/`Quantity` are classified as metrics,
`Region`/`Category`/`Segment` as dimensions, and `Order Date` as a date.

---

## Design notes

**Why the plan is validated before execution.** `validate_plan()` resolves every
model-supplied column name against the real schema (exact → case-insensitive →
punctuation-insensitive → fuzzy), swaps in the primary metric when the model invents one,
drops unusable filters with a warning, and clamps limits. A malformed plan degrades into a
sensible analysis instead of an exception.

**Why filters that match nothing are skipped.** An over-eager filter would otherwise
produce a confident answer over zero rows. Skipped filters are reported in the evidence.

**Why ratios are aggregated before dividing.** Profit margin by region is
`sum(Profit) / sum(Sales)` per region. Averaging per-row margins would weight a $3 order
the same as a $3,000 one.

**Why the narrator gets a formatted table and pre-computed comparisons.** It receives
numbers already rendered as `108,418.45` plus the exact gaps and shares, and is instructed
to quote them verbatim. That removes the main source of transcription drift — without it
the model says "roughly 17%" when the real figure is 18.5%.

**Why "which is highest" still returns five rows.** Ranking questions are more useful with
runners-up: the chart is readable and the answer can say by how much the leader leads.

**Why Plotly is lazy-loaded.** It is ~4.5 MB — three quarters of the bundle. Deferring it
until the first chart renders keeps the initial app shell at ~62 KB gzipped.

**Why there is a keyword fallback.** ChromaDB downloads its ONNX model on first use. On a
locked-down or offline machine that fails; the TF-IDF index keeps retrieval working and the
UI states which backend answered.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Failed to build chroma-hnswlib` | You are on ChromaDB 0.5.x, which needs a C++ compiler on Windows. `pip install "chromadb>=1.0"` |
| Browser shows "The React client has not been built yet" | `cd web && npm install && npm run build` |
| Answers say the planner is `Rule plan` | The Groq call failed. Check `GROQ_API_KEY`; `/api/health` reports the last error |
| `model does not exist` | Groq retired it. Set `GROQ_MODEL` to one listed by `/api/models` |
| First question is slow | Chroma downloads its ~80 MB embedding model once, then caches it |
| Answers arrive slowly in bursts | Groq free-tier rate limiting; the client backs off and retries |
| `Dataset not found` after a restart | Datasets are held in memory. Re-upload, or load the sample again |
