// 33income Capture Mode browser snippet
// Usage: run local helper first, then paste this into DevTools Console/Snippets on the logged-in page.
// It hooks fetch/XMLHttpRequest and sends sanitized request/response metadata to http://127.0.0.1:33133/capture.
(() => {
  if (window.__income33CaptureInstalled) {
    console.warn('[33income-capture] already installed');
    return;
  }
  window.__income33CaptureInstalled = true;

  const HELPER_URL = 'http://127.0.0.1:33133/capture';
  const MAX_BODY_CHARS = 500000;
  const SENSITIVE_HEADER_RE = /^(cookie|authorization|proxy-authorization|set-cookie)$/i;
  const PARTIAL_SENSITIVE_HEADER_RE = /(token|secret|session|auth|csrf|xsrf)/i;
  let sequence = 0;

  function truncateText(value) {
    if (value == null) return null;
    const text = typeof value === 'string' ? value : String(value);
    if (text.length <= MAX_BODY_CHARS) return text;
    return text.slice(0, MAX_BODY_CHARS) + `\n...[truncated ${text.length - MAX_BODY_CHARS} chars]`;
  }

  function cookieNames(value) {
    if (!value) return [];
    const names = [];
    String(value).split(/;|,\s*(?=[^;,=]+=)/).forEach(part => {
      const idx = part.indexOf('=');
      if (idx <= 0) return;
      const name = part.slice(0, idx).trim();
      if (!/^(path|domain|expires|max-age|secure|httponly|samesite)$/i.test(name)) names.push(name);
    });
    return Array.from(new Set(names)).sort();
  }

  function sanitizeHeaders(headers) {
    const out = {};
    try {
      const h = new Headers(headers || {});
      h.forEach((value, key) => {
        if (SENSITIVE_HEADER_RE.test(key)) {
          out[key] = { redacted: true, cookie_names: /cookie/i.test(key) ? cookieNames(value) : undefined, present: true };
        } else if (PARTIAL_SENSITIVE_HEADER_RE.test(key)) {
          out[key] = { redacted: true, present: !!value };
        } else {
          out[key] = value;
        }
      });
    } catch (e) {
      out.__parse_error = String(e);
    }
    return out;
  }

  async function bodyToText(body) {
    if (body == null) return null;
    if (typeof body === 'string') return truncateText(body);
    if (body instanceof URLSearchParams) return truncateText(body.toString());
    if (body instanceof FormData) {
      const entries = [];
      body.forEach((value, key) => {
        entries.push([key, value instanceof File ? `[File name=${value.name} size=${value.size}]` : String(value)]);
      });
      return truncateText(JSON.stringify(entries));
    }
    if (body instanceof Blob) return `[Blob type=${body.type} size=${body.size}]`;
    if (body instanceof ArrayBuffer) return `[ArrayBuffer bytes=${body.byteLength}]`;
    return truncateText(String(body));
  }

  function sendEvent(event) {
    const payload = JSON.stringify(event);
    if (navigator.sendBeacon) {
      try {
        const ok = navigator.sendBeacon(HELPER_URL, new Blob([payload], { type: 'application/json' }));
        if (ok) return;
      } catch (_) {}
    }
    fetch(HELPER_URL, {
      method: 'POST',
      mode: 'no-cors',
      keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: payload,
    }).catch(() => {});
  }

  const originalFetch = window.fetch;
  window.fetch = async function patchedFetch(input, init = {}) {
    const started = performance.now();
    const seq = ++sequence;
    const req = input instanceof Request ? input : null;
    const url = req ? req.url : String(input);
    const method = (init.method || (req && req.method) || 'GET').toUpperCase();
    const requestHeaders = sanitizeHeaders(init.headers || (req && req.headers) || {});
    let requestBody = null;
    try {
      requestBody = await bodyToText(init.body || null);
    } catch (e) {
      requestBody = `[request body read failed: ${e}]`;
    }

    try {
      const response = await originalFetch.apply(this, arguments);
      const clone = response.clone();
      let responseBody = null;
      try {
        responseBody = truncateText(await clone.text());
      } catch (e) {
        responseBody = `[response body read failed: ${e}]`;
      }
      sendEvent({
        sequence: seq,
        source: 'browser-snippet-fetch',
        page_url: location.href,
        method,
        url,
        request_headers: requestHeaders,
        request_body: requestBody,
        response_status: response.status,
        response_headers: sanitizeHeaders(response.headers),
        response_body: responseBody,
        duration_ms: Math.round((performance.now() - started) * 10) / 10,
      });
      return response;
    } catch (e) {
      sendEvent({
        sequence: seq,
        source: 'browser-snippet-fetch',
        page_url: location.href,
        method,
        url,
        request_headers: requestHeaders,
        request_body: requestBody,
        duration_ms: Math.round((performance.now() - started) * 10) / 10,
        error: String(e),
      });
      throw e;
    }
  };

  const OriginalXHR = window.XMLHttpRequest;
  function PatchedXHR() {
    const xhr = new OriginalXHR();
    const seq = ++sequence;
    const started = performance.now();
    const requestHeaders = {};
    let method = 'GET';
    let url = '';
    let requestBody = null;

    const originalOpen = xhr.open;
    xhr.open = function(m, u) {
      method = String(m || 'GET').toUpperCase();
      url = String(u || '');
      return originalOpen.apply(xhr, arguments);
    };

    const originalSetRequestHeader = xhr.setRequestHeader;
    xhr.setRequestHeader = function(key, value) {
      requestHeaders[key] = value;
      return originalSetRequestHeader.apply(xhr, arguments);
    };

    const originalSend = xhr.send;
    xhr.send = function(body) {
      bodyToText(body).then(text => { requestBody = text; }).catch(e => { requestBody = `[request body read failed: ${e}]`; });
      xhr.addEventListener('loadend', () => {
        let responseBody = null;
        try {
          responseBody = typeof xhr.responseText === 'string' ? truncateText(xhr.responseText) : `[responseType=${xhr.responseType}]`;
        } catch (e) {
          responseBody = `[response body read failed: ${e}]`;
        }
        sendEvent({
          sequence: seq,
          source: 'browser-snippet-xhr',
          page_url: location.href,
          method,
          url: new URL(url, location.href).href,
          request_headers: sanitizeHeaders(requestHeaders),
          request_body: requestBody,
          response_status: xhr.status,
          response_headers: {},
          response_body: responseBody,
          duration_ms: Math.round((performance.now() - started) * 10) / 10,
        });
      });
      return originalSend.apply(xhr, arguments);
    };
    return xhr;
  }
  window.XMLHttpRequest = PatchedXHR;
  console.info('[33income-capture] installed. Run your workflow, then check captures/YYYYMMDD/captures.jsonl');
})();
