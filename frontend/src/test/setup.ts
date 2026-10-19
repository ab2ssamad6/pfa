import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// Recharts' ResponsiveContainer needs ResizeObserver, absent in jsdom.
class RO { observe() {} unobserve() {} disconnect() {} }
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
