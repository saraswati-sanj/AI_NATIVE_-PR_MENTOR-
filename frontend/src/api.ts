import type { Mode, ReviewResponse } from "./types";

const API_URL = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

/** Longer than the backend's own 20s Gemini timeout, so the server answers first. */
const TIMEOUT_MS = 30_000;

/** An error with a message that is safe and useful to show the user. */
export class ReviewError extends Error {}

/**
 * Pull a human-readable message out of an error response.
 *
 * The backend sends {"detail": "..."} for its own errors, but slowapi's rate
 * limiter sends {"error": "..."}, so both keys are checked.
 */
async function messageFor(response: Response): Promise<string> {
  let detail = "";
  try {
    const body = (await response.json()) as { detail?: string; error?: string };
    detail = body.detail ?? body.error ?? "";
  } catch {
    // Body was not JSON; fall through to the status-based message.
  }

  switch (response.status) {
    case 400:
    case 413:
      // These messages are written for the user, so pass them straight through.
      return detail || "That input could not be reviewed. Check it and try again.";
    case 429:
      return "Too many reviews in one minute. Wait a moment, then try again.";
    case 500:
      return "The review service hit an unexpected error. Please try again.";
    default:
      return detail || `The review service returned an error (${response.status}).`;
  }
}

/** Run a review. Throws ReviewError with a user-facing message on any failure. */
export async function review(input: string, mode: Mode = "auto"): Promise<ReviewResponse> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch(`${API_URL}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input, mode }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new ReviewError(await messageFor(response));
    }

    return (await response.json()) as ReviewResponse;
  } catch (error) {
    if (error instanceof ReviewError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ReviewError("The review took longer than 30 seconds. Try a smaller snippet.");
    }
    throw new ReviewError(
      `Could not reach the review service at ${API_URL}. Check that the backend is running.`,
    );
  } finally {
    window.clearTimeout(timer);
  }
}
