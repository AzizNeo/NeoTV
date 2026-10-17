import { messageFor } from '@/core/i18n';

/** Every failed API call surfaces as an ApiError with a stable machine `code`. */
export class ApiError extends Error {
  constructor({ status, code, message, details, requestId, traceId }) {
    super(message ?? code);
    this.name = 'ApiError';
    this.status = status;
    this.code = code ?? 'UNKNOWN';
    this.details = details ?? null;
    this.requestId = requestId ?? null;
    /** W3C trace id this call was sent with: matches the API's trace and log lines (trace_id). */
    this.traceId = traceId ?? null;
  }

  /** Human text for the UI (i18n by code — backend prose is never shown verbatim). */
  get userMessage() {
    return messageFor(this.code, this.message);
  }

  static async fromResponse(response) {
    let body = null;
    try {
      body = await response.json();
    } catch {
      /* non-JSON error (proxy, nginx) */
    }
    const error = body?.error ?? {};
    return new ApiError({
      status: response.status,
      code: error.code ?? `HTTP_${response.status}`,
      message: error.message,
      details: error.details,
      requestId: error.request_id ?? response.headers.get('X-Request-ID'),
    });
  }

  static network(cause) {
    const err = new ApiError({ status: 0, code: 'NETWORK', message: cause?.message });
    err.cause = cause;
    return err;
  }
}
