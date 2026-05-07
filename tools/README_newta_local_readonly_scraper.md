# NewTA local read-only scraper

`tools/newta_local_readonly_scraper.py` is a local operator utility for collecting NewTA taxDoc/report data without using the 33income Control Tower server.

## Safety boundary

- GET-only. The tool blocks non-GET methods in its request client.
- It does **not** enqueue Control Tower commands.
- It does **not** call `ta-submit`, expected-tax send, customer-waiting, custom-type, DB, history, POST, PUT, PATCH, or DELETE endpoints.
- Do not paste real tokens into committed files, shell history you keep, screenshots, Discord, or test fixtures.

## Separate venv

The current implementation uses only the Python standard library, so no requirements install is needed.

```bash
cd /home/ubuntu/33income
python3 -m venv .venv-newta-scrape
source .venv-newta-scrape/bin/activate
python --version
```

## Auth input

For the NewTA browser traffic shown in DevTools, the practical auth input is the full `cookie` request header, not only an `Authorization` Bearer token. Paste it only at runtime.

Cookie names observed in the browser request:

- `ch-veil-id`
- `access-token`
- `refresh-token`
- `ch-session-...`

Preferred local options:

```bash
# one-shell-session only; do not save this in files
export NEWTA_COOKIE='REDACTED_COOKIE_HEADER_VALUE'

# or prompt without echo
python tools/newta_local_readonly_scraper.py --prompt-cookie ...
```

Bearer-style auth is still supported for endpoints/environments that accept it:

```bash
export NEWTA_AUTH_TOKEN='REDACTED_AUTH_VALUE'
python tools/newta_local_readonly_scraper.py --auth-token 'REDACTED_AUTH_VALUE' ...
python tools/newta_local_readonly_scraper.py --request-header 'authorization: REDACTED_AUTH_VALUE' ...
```

The output metadata stores only header keys and redacted header presence, not raw token or cookie values.

## Examples

Export `사업형태_공동사업` targets to Excel. This follows the browser flow: first `GET /api/ta/v1/me` with the runtime Cookie to discover `officeId`, then `filter-search` list -> each `taxDocId` profile summary `GET /api/tax/v1/taxdocs/{taxDocId}/summary?isMasking=false` -> write only `taxDocId` and `phoneNumber` to XLSX.

```bash
python tools/newta_local_readonly_scraper.py \
  --export-common-business-free-reason-xlsx \
  --prompt-cookie \
  --workflow-filter-set SUBMIT_READY \
  --assignment-status-filter ALL \
  --tax-doc-custom-type-filter ALL \
  --business-income-type-filter ALL \
  --freelancer-income-amount-type-filter ALL \
  --review-type-filter FREE \
  --tax-doc-service-code-type-filter C0 \
  --year 2025 \
  --sort SUBMIT_REQUEST_DATE_TIME \
  --direction ASC \
  --size 20 \
  --free-reason-type-match '사업형태_공동사업' \
  --output /tmp/newta-common-business-phone.xlsx
```

Interactive prompt mode asks for common filters and output path, then prompts for the cookie if no auth env/arg is present:

```bash
python tools/newta_local_readonly_scraper.py \
  --export-common-business-free-reason-xlsx \
  --interactive
```

Shortest repeated-use command:

```bash
./tools/newta_common_business_phone_export.sh
```

That wrapper uses these defaults and prompts only for the Cookie header unless overridden by env/extra args:

- `officeId=auto from GET /api/ta/v1/me using the runtime Cookie`
- `workflowFilterSet=SUBMIT_READY`
- `taxDocCustomTypeFilter=ALL`
- `reviewTypeFilter=FREE`
- `taxDocServiceCodeTypeFilter=C0`
- `year=2025`
- `size=20`
- `maxTargets=0` = all pages until NewTA `totalPages` ends

Optional examples:

```bash
NEWTA_OUTPUT=/tmp/newta-common-business-phone.xlsx ./tools/newta_common_business_phone_export.sh
NEWTA_PAGE_SIZE=20 ./tools/newta_common_business_phone_export.sh
NEWTA_OFFICE_ID=327 ./tools/newta_common_business_phone_export.sh  # optional manual override
./tools/newta_common_business_phone_export.sh --max-targets 50
```

`size` is page size, not total collection count. With `maxTargets=0`, the scraper follows `totalPages`/short final page and collects every returned `taxDocId` for the selected filters.

Collect submit-ready taxDoc rows for custom type `아`, max 50 targets, and fetch summary/status for those IDs. Without `--office-id`, the tool discovers the office from `GET /api/ta/v1/me` using the runtime Cookie:

```bash
python tools/newta_local_readonly_scraper.py \
  --prompt-cookie \
  --workflow-filter-set SUBMIT_READY \
  --tax-doc-custom-type-filter '아' \
  --review-type-filter NORMAL \
  --year 2025 \
  --max-targets 50 \
  --include-summary \
  --include-submit-status \
  --output /tmp/newta-submit-ready-a.json
```

Fetch only explicit taxDoc IDs, without list scraping:

```bash
python tools/newta_local_readonly_scraper.py \
  --no-list \
  --tax-doc-id 123456,123457 \
  --include-summary \
  --include-submit-status \
  --output /tmp/newta-explicit-taxdocs.json
```

If you need to override the cookie-derived office for debugging, pass `--office-id` explicitly. The normal path is to omit it so the Cookie account's `/api/ta/v1/me.data.officeId` drives `filter-search`:

```bash
python tools/newta_local_readonly_scraper.py \
  --prompt-cookie \
  --office-id 327 \
  --tax-doc-custom-type-filters '아,마' \
  --max-targets 100 \
  --output /tmp/newta-local-scrape.json
```

## Output

Default JSON scrape output path:

```text
local_scrape_outputs/newta_readonly_scrape_<UTC timestamp>.json
```

Default common-business XLSX output path:

```text
local_scrape_outputs/newta_common_business_free_reason_<UTC timestamp>.xlsx
```

The XLSX export intentionally contains only these columns:

```text
taxDocId, phoneNumber
```

Profile summary responses can contain sensitive fields such as names, resident numbers, bank accounts, and HomeTax credentials. The XLSX export does not write raw profile summary JSON.

Top-level JSON scrape shape:

```json
{
  "meta": {
    "readOnly": true,
    "blockedMethods": ["POST", "PUT", "PATCH", "DELETE"],
    "authHeaderKeys": ["authorization"]
  },
  "taxDocIds": [],
  "filterSearch": [],
  "summaries": [],
  "submitStatuses": []
}
```

Treat output files as local sensitive operator artifacts if they contain taxpayer/report data. Do not commit them.
