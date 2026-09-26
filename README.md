# GTEXT Real Estate AI Assistant — Live Acquisition Platform

GTEXT is a full-stack real-estate lead intelligence application for finding, monitoring, underwriting and pursuing U.S. acquisition opportunities. Version 3 includes live provider integration, map-based acquisition search, sold comps, AI investment memos, investor authentication, distressed/off-market seller-data ingestion, detailed underwriting, offer generation, controlled seller outreach, pipeline analytics, and portfolio/deal-room workflows.

## What is included

### Lead intelligence
- On-market and off-market lead model
- Deal score from 0–100 using configurable buy-box rules
- ARV, rehab, 70%-rule-style MAO, flip profit/ROI, gross rental yield and wholesale spread
- Strategy fit: Fix & Flip, Buy & Hold, Wholesale
- Risk and distress flags
- Saved/watchlist state
- Source freshness and status history

### Live property feed
The first production connector is **RentCast**. Add `RENTCAST_API_KEY` and the scheduled ingestion job will query the target cities/states defined in the Buy Box. The connector normalizes provider data into the GTEXT property model.

The provider layer is intentionally isolated so MLS/RESO, ATTOM or another licensed/off-market source can be added without redesigning the UI or underwriting model. **BatchData is implemented** for owner lookup and skip-trace on acquisition campaign leads (`POST /campaign/acquisition/enrich-owners`).

### Availability tracking
- Automatic refresh every 6 hours by default (`REFRESH_HOURS=6`)
- `last_seen` timestamp for every property
- Explicit source status is retained when provided
- A listing not observed for `STALE_HOURS` (default 18) is moved to `unconfirmed-off-market` rather than being falsely labeled sold
- Status changes are written to the status-history table

### Acquisition map
- OpenStreetMap/Leaflet map
- Property pins display price and deal score
- Map view uses the same lead database and underwriting results as the lead dashboard
- Backend includes a bounding-box endpoint (`/properties/map`) for scaling to larger datasets

### Automatic sold comps
`GET /properties/{id}/comps`

- Uses RentCast sold property records when a live key is configured
- Radius and sale-date windows are configurable
- Calculates average sale price, median sale price and average price per square foot
- Falls back to the local sold-comp dataset when the live provider is unavailable

### AI property memos
`POST /properties/{id}/memo`

When `OPENAI_API_KEY` is configured, GTEXT requests an investment memo containing:
- Deal snapshot
- Market/comps discussion
- Strategy fit
- Risks
- Negotiation angle
- Next-diligence checklist

The default model is `gpt-5.6-luna`, configurable through `OPENAI_MODEL`.

If no OpenAI key is configured, the endpoint still produces a transparent rule-based memo so the application remains functional.

### Investor alerts
- Create alert rules by minimum score, maximum price, city and strategy
- Rules are evaluated after refreshes or manually
- Alert events are stored even when email delivery is not configured
- Add SMTP settings to deliver qualifying leads by email

### Seller / agent CRM
- Create seller or agent contacts manually
- One-click creation from the property detail screen
- Pipeline statuses: new, contacted, follow-up, negotiating, offer-sent, closed, lost
- Interaction/task data model and API endpoints are included for calls, email notes and follow-ups

## Architecture

```text
Browser / React + Vite
    |
    +-- Lead dashboard
    +-- Leaflet / OpenStreetMap acquisition map
    +-- Sold comps + AI memo panel
    +-- Alert rules
    +-- Seller/agent CRM
    |
FastAPI
    |
    +-- Deal qualification engine
    +-- RentCast provider adapter
    +-- Sold-comp engine
    +-- OpenAI memo service
    +-- SMTP alert service
    +-- 6-hour APScheduler refresh
    |
PostgreSQL
    +-- properties
    +-- status_events
    +-- settings
    +-- memos
    +-- crm_contacts
    +-- crm_interactions
    +-- alert_rules
    +-- alert_events
```

## Quick start with Docker

1. Extract the project.
2. Copy the environment template:

```bash
cp .env.example .env
```

3. Add at minimum a property-data key to `.env` for live listings:

```env
RENTCAST_API_KEY=your_real_key
```

Optionally add:

```env
OPENAI_API_KEY=your_openai_key
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=alerts@example.com
SMTP_PASSWORD=your_password
SMTP_FROM=alerts@example.com
BATCHDATA_API_KEY=your_batchdata_key
BATCHDATA_BASE_URL=https://api.batchdata.com/api/v1
```

4. Start the stack:

```bash
docker compose up --build
```

5. Open:

- Web application: `http://localhost:8080`
- FastAPI: `http://localhost:8000`
- Interactive API docs: `http://localhost:8000/docs`

## Existing v1 database

Version 2 adds database fields and tables. If you only used the previous demo locally and do not need that test data, the cleanest upgrade is:

```bash
docker compose down -v
docker compose up --build
```

For a production database containing real records, use a schema migration process before deploying v2 rather than deleting the volume.

## Configure target acquisition markets

Open **Buy Box** in the web application. The default cities are:

- Prosper, TX
- Frisco, TX
- McKinney, TX
- Plano, TX
- Little Elm, TX

Change the target cities and underwriting thresholds in the UI, then save. The next scheduled or manual refresh uses those target markets.

## Live provider behavior

RentCast is used for the implemented live adapter because the API exposes sale listings, property records and sold-property queries. A provider API key is required. GTEXT does not scrape consumer listing websites.

Off-market investor datasets often require a separate licensed source. The existing GTEXT model can ingest those records as `market_type=off-market`; the next connector can map absentee-owner, high-equity, pre-foreclosure, tax-delinquency, probate or other licensed signals into `distress_signals`.

### BatchData owner enrichment

Acquisition campaign leads can be enriched with licensed owner and skip-trace data from BatchData. Add the following to `.env` (placeholders only — never commit a real key):

```env
BATCHDATA_API_KEY=your_batchdata_key
BATCHDATA_BASE_URL=https://api.batchdata.com/api/v1
```

`docker compose` passes both variables into the `api` container. With a key present:

- `GET /providers` reports BatchData `enabled: true`
- `GET /health` includes `providers.batchdata`
- `POST /campaign/acquisition/enrich-owners` runs property lookup plus skip-trace for every `lead_status=active` campaign lead

When BatchData returns a DNC or TCPA-litigator flag, related outreach drafts are marked `suppressed`. Delivery still requires `consent_confirmed=true` and a configured SMTP or Twilio provider. Use only licensed data and confirm you have permission to contact a person before sending.

## Security and production notes

Before public internet deployment:
- Put the API behind HTTPS and a reverse proxy/load balancer.
- Add user authentication and role-based authorization.
- Store provider/API/SMTP secrets in a managed secret store, not source control.
- Restrict CORS to the production domain.
- Add PostgreSQL backups and migration tooling.
- Confirm the licensing/redistribution terms for every property-data provider.
- Do not expose owner/contact information unless your data license and applicable laws permit the intended use.

## Validation performed in this build

The backend source passed Python syntax validation. Core API flows were exercised against a temporary SQLite database: health/provider state, dashboard, properties, settings, sold comps, memo generation, CRM contact creation, alert-rule creation and alert evaluation.

The frontend dependency download could not complete in the build environment because outbound package-network access timed out. The project includes the complete Vite/React source and Dockerfile; `docker compose up --build` in a normal networked environment will install the dependencies during the image build.

---

## Version 3 — Investor Operations Layer

The current build adds the operational features needed to move from lead discovery into acquisition and portfolio management.

### Investor authentication and accounts

Authentication is enabled by default with `AUTH_REQUIRED=true`. The web app opens on a sign-in/create-account screen. Passwords are stored as salted PBKDF2-SHA256 hashes; session tokens are random server-side bearer tokens with a 30-day expiry. No plaintext passwords or API credentials are stored in the browser.

For local API development only, authentication can be disabled with:

```env
AUTH_REQUIRED=false
```

### Licensed distressed/off-market seller data

The backend now has a normalized distressed-data layer for records such as tax delinquency, foreclosure/pre-foreclosure, absentee ownership, vacancy, probate/estate, liens, equity signals, and other licensed/public-record indicators. Every record keeps its provider, verification timestamp, filing date, severity, source URL and available owner contact fields.

The platform deliberately does **not** invent seller data. To use real data, configure a licensed provider or normalization service:

```env
OFFMARKET_API_URL=https://your-normalized-provider.example/api/distress
OFFMARKET_API_TOKEN=...
```

The endpoint should return a JSON array, or `{ "records": [...] }`, with fields such as:

```json
{
  "property_id": "rentcast:abc123",
  "provider": "Your Licensed Provider",
  "record_type": "tax_delinquent",
  "severity": 3,
  "amount": 4500,
  "filingDate": "2026-09-01T00:00:00Z",
  "ownerName": "...",
  "ownerEmail": "...",
  "ownerPhone": "...",
  "mailingAddress": "...",
  "equityPct": 42,
  "source_url": "..."
}
```

The six-hour scheduler now refreshes both listings and this normalized distress feed when it is configured.

### Detailed underwriting + mortgage/cash-flow calculators

The Underwriting Lab accepts editable assumptions and calculates:

- Purchase price, rehab and total cash required
- Down payment and loan amount
- Monthly principal + interest
- Vacancy, management, maintenance, taxes, insurance, HOA and utilities
- Monthly/annual NOI
- Monthly/annual cash flow
- Cap rate
- Cash-on-cash return
- DSCR
- Break-even occupancy
- Sales/disposition costs
- Holding/carrying costs
- Net flip profit and flip ROI

Every run is saved as an underwriting case for later audit/history.

### Offer generation

The platform can generate a non-binding acquisition Letter of Intent from an analyzed property, including offer price, earnest money, financing method, inspection period and target close. The generated document explicitly states that it is for discussion purposes and is not a binding purchase agreement. Use local counsel / approved state forms before treating an offer as a contract.

### Seller outreach

Seller/agent communications can be drafted and queued from the CRM. Actual automated delivery is blocked unless:

1. The recipient is not suppressed.
2. `consent_confirmed=true` is recorded for the message.
3. The delivery provider is configured.

Email uses the existing SMTP configuration. SMS can use Twilio:

```env
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM=
```

The compliance gate is intentional. It helps keep scraping/lead ingestion separate from permission to contact a person through an automated channel.

### Lead pipeline analytics

The analytics workspace summarizes CRM stages, outreach sent, offer stages, accepted offers, acceptance rate and deal-room stages. This provides a basic acquisition funnel from new seller/agent contact through offer and closing.

### Portfolio / deal room

Qualified properties can be promoted into a deal room with stages such as underwriting, offer, due diligence, financing, closing, closed, lost and sold. Each deal room has a default diligence checklist, notes, target close, purchase basis and projected value. The portfolio page aggregates active deals, closed deals, purchase basis, projected value and projected equity.

### New API endpoints

Key v3 endpoints include:

```text
POST /auth/register
POST /auth/login
GET  /auth/me
POST /auth/logout

GET  /distress/{property_id}
POST /distress/import
POST /distress/sync

POST /properties/{property_id}/underwrite
GET  /properties/{property_id}/underwriting

POST /properties/{property_id}/offers
GET  /offers
PATCH /offers/{offer_id}/status

POST /outreach
POST /outreach/{message_id}/send
GET  /outreach

GET  /pipeline/analytics
POST /deal-rooms
GET  /deal-rooms
PATCH /deal-rooms/{room_id}
GET  /portfolio
```

### Production recommendation

Before exposing this application publicly, put the API behind HTTPS, move session/authentication to a managed identity service or hardened OAuth/OIDC provider, use a managed PostgreSQL database, store secrets in a cloud secret manager, add database migrations, role-based permissions, audit logs, rate limiting, backups, observability and provider-specific data-retention rules.
