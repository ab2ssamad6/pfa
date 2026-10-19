import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import type { ReactElement } from "react";

type Handler = (url: string, init?: RequestInit) => unknown | Response;

/** Route-table fetch mock: keys are exact paths (query string ignored); values return JSON bodies or a Response. */
export function mockFetch(routes: Record<string, Handler>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const path = url.split("?")[0];
    const exact = routes[path];
    if (!exact) return new Response(JSON.stringify({ detail: `no mock for ${path}` }), { status: 404 });
    const out = await exact(url, init);
    return out instanceof Response ? out : new Response(JSON.stringify(out), { status: 200 });
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

export function renderAt(path: string, element: ReactElement, routePath = "*") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path={routePath} element={element} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
