import { describe, expect, it, vi } from "vitest";
import { api, ApiError, qs } from "../api/client";

describe("api client", () => {
  it("builds query strings, skipping empty values", () => {
    expect(qs({ a: 1, b: undefined, c: "", d: "x" })).toBe("?a=1&d=x");
    expect(qs({})).toBe("");
  });

  it("surfaces FastAPI error details", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "incident 9 not found" }), { status: 404 })));
    await expect(api("/api/incidents/9")).rejects.toMatchObject({ status: 404, message: "incident 9 not found" });
  });

  it("reports an unreachable backend clearly", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const err = (await api("/api/health").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.message).toMatch(/unreachable/);
  });
});
