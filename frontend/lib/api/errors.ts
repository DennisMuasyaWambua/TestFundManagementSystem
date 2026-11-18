/** The single error shape the backend uses, and the status codes it pairs with. */

export type ApiErrorBody = {
  error: { code: string; message: string; details?: Record<string, unknown> };
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** 401 means the token is gone or expired: the UI sends the user back to /login. */
  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  /** 403 is the authoritative permission answer; the UI only *hides* what it can. */
  get isForbidden(): boolean {
    return this.status === 403;
  }

  static async fromResponse(response: Response): Promise<ApiError> {
    let code = "UNEXPECTED";
    let message = `the API returned ${response.status}`;
    let details: Record<string, unknown> = {};
    try {
      const body = (await response.json()) as Partial<ApiErrorBody>;
      if (body.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
        details = body.error.details ?? {};
      }
    } catch {
      // A proxy or a crash can return HTML or nothing at all; keep the status message.
    }
    return new ApiError(response.status, code, message, details);
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "something went wrong";
}
