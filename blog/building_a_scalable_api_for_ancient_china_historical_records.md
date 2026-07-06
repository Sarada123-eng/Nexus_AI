# Building a Scalable API for Ancient China Historical Records

## Why a Dedicated API for Ancient China Data Matters

- **Data volume overwhelms naïve CRUD**  
  A typical repository contains ≈ 2 M oracle‑bone glyphs, ≈ 150 K dynastic annal entries, and ≈ 5 GB of GIS raster layers (e.g., LiDAR‑derived burial sites). Loading all rows into a single REST `GET /records` response would require > 10 GB of heap memory, causing out‑of‑memory crashes on commodity servers. Even a paginated endpoint that returns 10 K rows per page still forces the application layer to materialize large joins in memory before serialization.

- **Latency spikes when merging text and space**  
  Real‑time queries such as “show all annals mentioning *Zhou* within 200 km of the Yellow River” trigger a cross‑join between a full‑text index (≈ 150 K documents) and a PostGIS table (≈ 2 M point features). Without pre‑computed spatial‑text indexes, the DB must scan both tables, resulting in 1‑2 s latency on average and > 10 s for hotspot periods. Users experience timeouts, and downstream AI pipelines stall.

- **Business case for reproducible, versioned access**  
  Scholars cite exact manuscript versions; educators need stable snapshots for curricula; large‑language‑model fine‑tuning requires immutable training sets. A dedicated API can expose a `v{date}` namespace (e.g., `/v2024-04-01/records`) guaranteeing that the same query today and next year returns identical payloads, which is impossible with ad‑hoc file dumps.

- **High‑level architecture that mitigates the above**  

  ```
  Ingestion → Transformation → Query Service
  ```

  1. **Ingestion** pulls raw XML, CSV, and GeoTIFF files into a message queue (Kafka).  
  2. **Transformation** normalizes to a columnar store (Apache Parquet) and builds separate indexes: ElasticSearch for full‑text, PostGIS for geometry, and a version‑aware metadata catalog.  
  3. **Query Service** (e.g., FastAPI + async SQLAlchemy) composes queries against the pre‑indexed layers, streams results with HTTP chunked encoding, and enforces API‑level caching headers.

  *Trade‑off*: Maintaining dual indexes adds storage cost (~30 % overhead) but reduces average query latency from seconds to < 200 ms, a worthwhile gain for interactive research tools. Edge cases such as schema evolution are handled by versioned Parquet partitions; any failure to load a new shard triggers a rollback to the previous stable version, preserving API continuity.

## Designing a Normalized Data Model for Dynastic Records  

**ER diagram sketch** – The core entities and their keys are:  

| Table      | Primary Key          | Foreign Keys (references)                     |
|------------|----------------------|----------------------------------------------|
| `Dynasty`  | `dynasty_id` (PK)    | –                                            |
| `Reign`    | `reign_id` (PK)      | `dynasty_id` → `Dynasty(dynasty_id)`         |
| `Artifact` | `artifact_id` (PK)   | `location_id` → `Location(location_id)`      |
| `Location` | `location_id` (PK)   | –                                            |
| `Translation` | `translation_id` (PK) | `artifact_id` → `Artifact(artifact_id)`<br>`source_text_id` → `SourceText(source_text_id)` |
| `SourceText` | `source_text_id` (PK) | –                                            |
| `ArtifactSource` (junction) | (`artifact_id`,`source_text_id`) PK | `artifact_id` → `Artifact`<br>`source_text_id` → `SourceText` |

Relationships:  
- `Dynasty` 1‑* `Reign` (one dynasty has many reigns).  
- `Reign` 1‑* `Artifact` (optional, via provenance).  
- `Artifact` *‑* `SourceText` through `ArtifactSource`.  
- `Artifact` *‑1 `Location` (each artifact is found at one location).  

**SQL DDL with temporal constraint**  

```sql
CREATE TABLE reign (
    reign_id      SERIAL PRIMARY KEY,
    dynasty_id    INT NOT NULL REFERENCES dynasty(dynasty_id),
    ruler_name   TEXT NOT NULL,
    start_year   INT NOT NULL,
    end_year     INT NOT NULL,
    CHECK (start_year < end_year)               -- enforce chronological order
);
```

*Why*: The `CHECK` prevents impossible intervals, catching data entry errors early.

**Checklist: handling many‑to‑many Artifact ↔ SourceText**  

- [ ] Create a pure junction table `artifact_source` with composite PK (`artifact_id`, `source_text_id`).  
- [ ] Define both columns as `NOT NULL` and add `FOREIGN KEY` constraints.  
- [ ] Index each column individually for fast look‑ups from either side.  
- [ ] Use `ON DELETE CASCADE` only if you want artifacts or source texts to disappear together; otherwise prefer `ON DELETE RESTRICT`.  
- [ ] Populate via a single `INSERT … SELECT` batch to keep the operation atomic.  

**Storing uncertain dates with `daterange` and confidence**  

```sql
CREATE TABLE artifact (
    artifact_id   SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    provenance    DATERANGE NOT NULL,          -- e.g. '[1200-01-01,1220-12-31)'
    confidence    NUMERIC(3,2) CHECK (confidence BETWEEN 0 AND 1) DEFAULT 0.95
);
```

Example insertion:  

```sql
INSERT INTO artifact (name, provenance, confidence)
VALUES ('Jade Bi', '[1195-01-01,1205-12-31)', 0.80);
```

*Trade‑off*: `daterange` enables range queries (`&&`, `@>`) but cannot express non‑contiguous uncertainty; for fragmented estimates you’d need a separate table.  

**Edge cases & mitigation**  
- Overlapping reign periods for the same dynasty violate historical logic; add a `EXCLUDE USING gist (dynasty_id WITH =, tsrange(start_year, end_year) WITH &&)` constraint if needed.  
- Null `confidence` hides data quality; enforce `NOT NULL` and default to `0.5` for unknown confidence.  

By following this schema, developers get a fully normalized model that eliminates redundancy while supporting complex queries across dynastic timelines, artifact provenance, and multilingual annotations.

## Minimal Working Example: FastAPI Endpoint that Serves Oracle Bone Inscriptions

**FastAPI route (10 lines)**  
```python
from fastapi import FastAPI, Depends, HTTPException
from sqlmodel import SQLModel, Field, select
from sqlmodel.ext.asyncio.session import AsyncSession

app = FastAPI()
class Artifact(SQLModel, table=True): id: int = Field(default=None, primary_key=True); chinese: str; english: str | None = None
@app.get("/artifacts/{id}", response_model=ArtifactResponse)
async def get_artifact(id: int, session: AsyncSession = Depends(get_session)):
    a = (await session.exec(select(Artifact).where(Artifact.id == id))).one_or_none(); 
    if not a: raise HTTPException(404, "Not found")
    return a
```

**Pydantic response model** – placed above the route so `response_model` resolves correctly. The model inherits from `SQLModel` (which is a Pydantic model) and forces UTF‑8 handling of Chinese characters; the English field is optional.

```python
class ArtifactResponse(SQLModel):
    id: int
    chinese: str               # e.g. "卜辞"
    english: str | None = None
```

*Why*: Explicit response models guarantee a stable JSON‑API contract and let FastAPI automatically encode Unicode without extra configuration.

**Unit test with mocked DB** – uses `pytest` and `unittest.mock`. The async DB session is replaced by a stub that returns a fabricated `Artifact`.

```python
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_get_artifact():
    fake = Artifact(id=1, chinese="卜辞", english="oracle inscription")
    mock_session = AsyncMock()
    mock_session.exec.return_value

## Performance & Cost: Caching, Pagination, and Edge‑Case Loads

**1. Redis LRU cache for hot reign periods**  
Store the result of the most‑queried dynasty‑range queries in a Redis instance configured with `maxmemory-policy allkeys-lru`. Example in Python:

```python
import aioredis, json, asyncio

REDIS_URL = "redis://:password@redis-prod:6379/0"
CACHE_TTL = 300          # seconds

async def get_reign_data(key: str):
    r = await aioredis.from_url(REDIS_URL)
    cached = await r.get(key)
    if cached:
        return json.loads(cached)          # cache hit
    # cache miss → fetch from Aurora
    data = await fetch_from_db(key)        # your async DB call
    await r.set(key, json.dumps(data), ex=CACHE_TTL)
    return data
```

Configure Redis with `maxmemory 4gb` and `maxmemory-policy allkeys-lru`. Run a Locust load test that alternates between cached and uncached keys; the observed median latency drops from ~1 s to ~200 ms, a **5× speed‑up**. Record the results in `locustfile.py` and assert `response_time < 200` for the cached path.

**2. Cursor‑based pagination**  
Replace `OFFSET` scans with a token that encodes the last primary key seen. In the API layer:

```python
import base64, json
PAGE_SIZE = 100

def encode_token(last_id: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"last_id": last_id}).encode()).decode()

def decode_token(token: str) -> int:
    return json.loads(base64.urlsafe_b64decode(token))["last_id"]
```

SQL query:

```sql
SELECT * FROM records
WHERE dynasty_id = :dynasty_id
  AND id > :last_id
ORDER BY id ASC
LIMIT :page_size;
```

The response includes `next_token = encode_token(last_row.id)` when `len(rows) == PAGE_SIZE`. This eliminates full‑table scans, keeping latency under the 200 ms target even as the table grows to millions of rows.

**3. Failure‑mode test for >10 000 rows**  
Create an integration test that forces the DB to return 10 001 rows:

```python
def test_large_export(client):
    resp = client.get("/records?dynasty=Han&export=csv")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "text/csv"
    # Ensure streaming, not full load in memory
    assert resp.is_streamed
```

In the endpoint, fall back to a generator‑based CSV stream:

```python
def stream_csv(query):
    yield "id,year,event\n"
    for row in query.yield_per(1000):
        yield f"{row.id},{row.year},{row.event}\n"
```

If the row count exceeds the threshold, the handler switches to `stream_csv` to avoid OOM and keep response time acceptable.

**4. Cost‑estimation: Aurora on‑demand vs. provisioned**  

| Instance type                | On‑demand (USD/month) | Provisioned (USD/month) | Notes |
|------------------------------|-----------------------|--------------------------|-------|
| db.r5.large (2 vCPU, 16 GiB) | $150                  | $120 (reserved 1‑yr)     | Sufficient for 1 M requests with ~30 ms DB latency |
| db.r5.xlarge (4 vCPU, 32 GiB) | $300                  | $240 (reserved 1‑yr)     | Handles burst traffic up to 5× peak without scaling |
| Aurora Serverless v2 (auto)  | $0.10 per ACU‑hr       | N/A                      | Pay‑as‑you‑go, ideal for irregular spikes but higher per‑request cost |

*Why*: On‑demand offers flexibility for unpredictable bursts; provisioned reduces unit cost when traffic is steady. Serverless eliminates capacity planning but can introduce cold‑start latency, which may breach the 200 ms SLA during sudden spikes. Choose provisioned for the baseline 1 M‑request/month load and supplement with a small Redis cache to absorb bursty read traffic.

## Common Mistakes When Exposing Historical Data

### 1. Storing raw UTF‑8 blobs without validation  
Raw text from ancient tablets often contains non‑standard glyphs or corrupted bytes. Persisting it directly leads to unreadable responses and downstream parsing errors.  

**Fix:** Define a JSON schema (or Pydantic model) that enforces Unicode Normalization Form C (NFC) and rejects illegal code points.

```python
from pydantic import BaseModel, validator
import unicodedata

class Record(BaseModel):
    title: str
    content: str

    @validator("content")
    def normalize_nfc(cls, v):
        return unicodedata.normalize("NFC", v)
```

*Why?* Normalization guarantees a single binary representation, preventing duplicate keys and simplifying search indexing.

### 2. Exposing internal `confidence` scores as public fields  
Confidence scores (e.g., 0.73) reveal proprietary heuristics and can be misinterpreted by API consumers.

**Fix:** Map the numeric range to a vetted enum (`LOW`, `MEDIUM`, `HIGH`) and document the meaning.

```json
{
  "confidence": "MEDIUM"
}
```

*Why?* Enums hide raw metrics while still communicating uncertainty in a controlled vocabulary.

### 3. Ignoring time‑zone differences in BCE/CE conversions  
A record dated “‑221‑01‑01” (221 BCE) interpreted as UTC can drift by centuries when daylight‑saving rules or calendar reforms are applied.

**Fix:** Use `astropy.time` for astronomical‑grade conversions and add unit tests for edge dates.

```python
from astropy.time import Time

t = Time("-221-01-01", scale="utc", format="iso")
iso_str = t.iso  # → '0221-01-01 00:00:00.000'
```

*Why?* `astropy` handles Julian/Gregorian transitions automatically, eliminating off‑by‑day bugs.

### 4. Over‑exposing SQL queries leading to injection  
Returning raw query strings or concatenating user input into `SELECT` statements opens the API to SQL injection attacks.

**Fix:** Implement a DAO layer that uses prepared statements exclusively.

```python
def get_events(conn, dynasty_id):
    sql = "SELECT * FROM events WHERE dynasty_id = %s"
    with conn.cursor() as cur:
        cur.execute(sql, (dynasty_id,))
        return cur.fetchall()
```

*Why?* Prepared statements separate code from data, guaranteeing that input cannot alter query structure.

**Checklist**

- [ ] Validate and normalize all UTF‑8 payloads.  
- [ ] Replace numeric confidence with a documented enum.  
- [ ] Convert BCE/CE dates with `astropy.time`; add tests for `-0001`, `0000`, `+0001`.  
- [ ] Route every DB access through a DAO that uses parameterized queries only.  

**Edge cases & trade‑offs**  
- Normalization may strip rare historic characters; keep a fallback “raw_blob” field for archivists.  
- Enum granularity reduces expressiveness; choose `LOW/MEDIUM/HIGH` only if it matches downstream analytics.  
- `astropy` adds a small runtime dependency but saves months of calendar‑bug debugging.  
- DAO abstraction adds a layer of indirection, increasing code size, but dramatically improves security and testability.

## Production Checklist & Next Steps

- **Enable structured logs (JSON) with request IDs**  
  - Add a request‑ID middleware (e.g., FastAPI `Depends`) that injects a UUID into the `X-Request-ID` header and the logging context.  
  - Configure the logger to emit JSON:

  ```python
  import logging, json, uuid
  from pythonjsonlogger import jsonlogger

  logger = logging.getLogger()
  logHandler = logging.StreamHandler()
  formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s')
  logHandler.setFormatter(formatter)
  logger.addHandler(logHandler)
  logger.setLevel(logging.INFO)

  def request_id_middleware(request, call_next):
      request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
      logger = logging.LoggerAdapter(logging.getLogger(), {'request_id': request_id})
      response = call_next(request)
      response.headers['X-Request-ID'] = request_id
      return response
  ```

  - **Grafana Loki alert** for latency spikes > 500 ms:

  ```yaml
  groups:
    - name: api-latency
      rules:
        - alert: HighLatency
          expr: histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[1m])) by (le)) > 0.5
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "95th‑percentile latency > 500 ms"
  ```

  *Why*: JSON logs are machine‑readable, enabling automated alerting and correlation across services.

- **Add Prometheus metrics**  
  - Instrument the application with `prometheus_client`:

  ```python
  from prometheus_client import Counter, Histogram, Gauge, start_http_server

  REQUEST_COUNT = Counter('api_requests_total', 'Total requests', ['method', 'endpoint'])
  ERROR_COUNT   = Counter('api_errors_total', 'Total error responses', ['method', 'endpoint', 'code'])
  CACHE_HIT     = Counter('api_cache_hits_total', 'Cache hits', ['endpoint'])
  CACHE_MISS    = Counter('api_cache_misses_total', 'Cache misses', ['endpoint'])
  LATENCY       = Histogram('http_request_duration_seconds', 'Request latency', ['method', 'endpoint'])

  @app.middleware("http")
  async def metrics_middleware(request, call_next):
      method, path = request.method, request.url.path
      with LATENCY.labels(method, path).time():
          response = await call_next(request)
      REQUEST_COUNT.labels(method, path).inc()
      if response.status_code >= 500:
          ERROR_COUNT.labels(method, path, response.status_code).inc()
      return response
  ```

  - Expose `/metrics` for scraping:

  ```python
  start_http_server(8000)  # runs on separate thread, /metrics auto‑available
  ```

  *Trade‑off*: Adding histograms increases memory usage; keep bucket count low for high‑traffic endpoints.

- **Run a security scan**  
  - Bandit (static analysis)  

    ```bash
    bandit -r src/ -ll > bandit-report.txt
    ```

  - OWASP ZAP (dynamic scan)  

    ```bash
    zap-baseline.py -t http://localhost:8080 -r zap-report.html
    ```

  - Verify that error payloads never include raw provenance fields (e.g., `source_file`, `line_number`). Replace them with generic messages and log the details internally.

  *Edge case*: False positives from Bandit on third‑party libraries; whitelist only after manual review.

- **Create a CI/CD pipeline**  
  - GitHub Actions workflow (`.github/workflows/ci.yml`):

  ```yaml
  name: CI
  on: [push, pull_request]
  jobs:
    test:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v3
        - name: Set up Python
          uses: actions/setup-python@v4
          with: {python-version: "3.11"}
        - name: Install deps
          run: pip install -r requirements.txt
        - name: Run MWE tests
          run: pytest tests/mwe/
        - name: Migration check
          run: alembic upgrade head --sql
    nightly-integrity:
      runs-on: ubuntu-latest
      schedule: [{cron: '0 2 * * *'}]
      steps: *same as above* + `python scripts/integrity_check.py`
  ```

  *Why*: Automating migration validation prevents schema drift in production.

- **Plan next iteration**  
  - **GraphQL façade**: design a thin GraphQL layer that resolves to existing REST endpoints, enabling scholars to request only needed fields. Consider `ariadne` for schema‑first development; it adds a modest latency overhead (~10 ms) but reduces over‑fetching.  
  - **Vector‑store integration**: index artifact descriptions with OpenAI embeddings and store them in Pinecone or Milvus. Provide a `/search/semantic` endpoint that returns top‑k similar records. Trade‑off: additional storage cost and background indexing pipeline complexity.  
  - **Milestones**:  
    1. Draft GraphQL schema (2 days).  
    2. Implement resolver stubs (3 days).  
    3. Set up vector‑store, run batch embedding (1 week).  
    4. Add integration tests for both features (2 days).  

  *Edge case*: GraphQL queries that request deeply nested relationships may cause N+1 DB calls; mitigate with DataLoader pattern.  

---  

✅ Verify each checklist item before merging to `main`. Once all alerts are green, metrics are visible, security scans pass, and the pipeline runs nightly, the API is ready for production rollout.
