/**
 * The three failure modes the console distinguishes.
 *
 * They are separate classes rather than one error with a `kind` field because
 * every call site has to decide between them, and the type system should make
 * a forgotten branch visible. The distinction matters editorially, not just
 * technically:
 *
 *  - `ApiUnavailableError` means the engine could not be reached or has not
 *    implemented an endpoint. The console shows "unavailable", never zero.
 *  - `MalformedResponseError` means the engine answered with something that
 *    does not satisfy the contract. The console refuses to render it rather
 *    than guessing what was meant.
 *  - `AccessDeniedError` means the caller is not permitted to see it. The
 *    console says so explicitly instead of showing an empty list, because an
 *    empty list reads as "there is nothing there".
 */

export class ApiUnavailableError extends Error {
  readonly endpoint: string;
  readonly cause?: unknown;

  constructor(endpoint: string, message?: string, cause?: unknown) {
    super(message ?? `Endpoint is unavailable: ${endpoint}`);
    this.name = "ApiUnavailableError";
    this.endpoint = endpoint;
    this.cause = cause;
  }
}

export class MalformedResponseError extends Error {
  readonly endpoint: string;
  /** Human-readable contract violations, one per line. */
  readonly issues: string[];

  constructor(endpoint: string, issues: string[]) {
    super(`Response from ${endpoint} does not satisfy the forecast contract`);
    this.name = "MalformedResponseError";
    this.endpoint = endpoint;
    this.issues = issues;
  }
}

export class AccessDeniedError extends Error {
  readonly resource: string;
  /** What the caller would need. Shown to the analyst so the ask is concrete. */
  readonly requiredRole?: string;

  constructor(resource: string, requiredRole?: string) {
    super(
      requiredRole
        ? `Access to ${resource} requires the ${requiredRole} role`
        : `Access to ${resource} is denied`,
    );
    this.name = "AccessDeniedError";
    this.resource = resource;
    this.requiredRole = requiredRole;
  }
}

export type ApiError = ApiUnavailableError | MalformedResponseError | AccessDeniedError;

export function isApiError(error: unknown): error is ApiError {
  return (
    error instanceof ApiUnavailableError ||
    error instanceof MalformedResponseError ||
    error instanceof AccessDeniedError
  );
}
