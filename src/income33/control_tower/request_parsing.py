from __future__ import annotations

import re
from urllib.parse import parse_qs

from fastapi import HTTPException, Request


async def read_form_value(request: Request, field_name: str) -> str:
    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    return parse_qs(raw_body).get(field_name, [""])[0].strip()


def parse_tax_doc_ids(raw_tax_doc_ids: str) -> list[int]:
    if not raw_tax_doc_ids:
        raise HTTPException(status_code=400, detail="tax_doc_ids is required")

    tokens = [token for token in re.split(r"[\s,]+", raw_tax_doc_ids) if token]
    if not tokens:
        raise HTTPException(status_code=400, detail="tax_doc_ids is required")
    if len(tokens) > 500:
        raise HTTPException(status_code=400, detail="tax_doc_ids exceeds max 500")

    tax_doc_ids: list[int] = []
    for token in tokens:
        try:
            tax_doc_id = int(token)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid tax_doc_id: {token}") from exc
        if tax_doc_id <= 0:
            raise HTTPException(status_code=400, detail=f"invalid tax_doc_id: {token}")
        tax_doc_ids.append(tax_doc_id)

    return list(dict.fromkeys(tax_doc_ids))
