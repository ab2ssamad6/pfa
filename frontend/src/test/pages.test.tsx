import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OverviewPage from "../pages/Overview";
import { IncidentDetailPage, IncidentsPage } from "../pages/Incidents";
import ModelPage from "../pages/Model";
import { HealthBanner } from "../components/Layout";
import { health, hosts, incident, incidentDetail, model, overview } from "./fixtures";
import { mockFetch, renderAt } from "./utils";

describe("Overview", () => {
  it("shows KPIs, host charts and recent incidents with uncertainty wording", async () => {
    mockFetch({
      "/api/overview": () => overview, "/api/hosts": () => hosts, "/api/health": () => health,
      "/api/incidents": () => ({ total: 1, items: [incident] }),
      "/api/hosts/1/scores": () => [{ ts: "2026-10-18T10:00:00Z", p_attack: 0.97, is_anomaly: true, category: "DDoS" }],
    });
    renderAt("/", <OverviewPage />);
    expect(await screen.findByText("Open incidents")).toBeInTheDocument();
    expect(await screen.findByText("pfSense Edge Firewall")).toBeInTheDocument();
    expect(await screen.findByText(/Suspected/)).toBeInTheDocument();
    expect(screen.getByText("of 1350 windows scored")).toBeInTheDocument();
    expect(await screen.findByTestId("score-chart")).toBeInTheDocument();
  });

  it("shows an error state with retry when the API fails", async () => {
    mockFetch({ "/api/overview": () => new Response("{}", { status: 500 }), "/api/hosts": () => [], "/api/health": () => health,
                "/api/incidents": () => ({ total: 0, items: [] }) });
    renderAt("/", <OverviewPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load data");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(await screen.findByText(/No hosts discovered yet/)).toBeInTheDocument();
  });
});

describe("Health banner", () => {
  it("explains a degraded source", async () => {
    mockFetch({ "/api/health": () => ({ ...health, status: "degraded",
      source: { ...health.source!, state: "degraded", last_error: "history.get: HTTP 503" } }) });
    renderAt("/", <HealthBanner />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/telemetry source degraded: history.get: HTTP 503/);
  });

  it("renders nothing when healthy", async () => {
    mockFetch({ "/api/health": () => health });
    const { container } = renderAt("/", <HealthBanner />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});

describe("Incident workflow", () => {
  it("filters by status and shows empty states", async () => {
    const calls = mockFetch({ "/api/incidents": (url) => (url.includes("status=resolved") ? { total: 0, items: [] } : { total: 1, items: [incident] }) });
    renderAt("/incidents", <IncidentsPage />);
    expect(await screen.findByText("#7")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "resolved" }));
    expect(await screen.findByText("No resolved incidents.")).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("status=open"))).toBe(true);
  });

  it("acknowledges an incident with a note (POST) and refreshes", async () => {
    let status: "open" | "acknowledged" = "open";
    const calls = mockFetch({
      "/api/health": () => health,
      "/api/incidents/7": () => ({ ...incidentDetail, status }),
      "/api/incidents/7/acknowledge": (_u, init) => { status = "acknowledged"; return { ...incident, status, note: JSON.parse(String(init?.body)).note }; },
    });
    renderAt("/incidents/7", <IncidentDetailPage />, "/incidents/:id");
    expect(await screen.findByText("Incident #7")).toBeInTheDocument();
    expect(screen.getByText(/not a confirmed attack/)).toBeInTheDocument();
    expect(screen.getByText("pfSense: Firewall states above 80% of maximum")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Analyst note/), "pentest window");
    await userEvent.click(screen.getByRole("button", { name: "Acknowledge" }));
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/acknowledge"))).toBeDefined());
    const post = calls.find((c) => c.url.endsWith("/acknowledge"))!;
    expect(post.init?.method).toBe("POST");
    expect(JSON.parse(String(post.init?.body))).toEqual({ note: "pentest window" });
    expect(await screen.findByText("acknowledged")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
  });

  it("shows the API conflict message when an action is rejected", async () => {
    mockFetch({
      "/api/health": () => health, "/api/incidents/7": () => incidentDetail,
      "/api/incidents/7/resolve": () => new Response(JSON.stringify({ detail: "incident already resolved" }), { status: 409 }),
    });
    renderAt("/incidents/7", <IncidentDetailPage />, "/incidents/:id");
    await userEvent.click(await screen.findByRole("button", { name: "Resolve" }));
    expect(await screen.findByText("incident already resolved")).toBeInTheDocument();
  });
});

describe("Model page", () => {
  it("shows offline metrics, confusion matrix and handles disabled live accuracy", async () => {
    mockFetch({ "/api/model": () => model,
                "/api/demo/live-accuracy": () => new Response(JSON.stringify({ detail: "disabled" }), { status: 404 }) });
    renderAt("/model", <ModelPage />);
    expect(await screen.findByText(/Active model: random_forest-1/)).toBeInTheDocument();
    expect(screen.getByText("97.34%")).toBeInTheDocument();
    const cm = screen.getByRole("table", { name: "confusion matrix" });
    expect(within(cm).getByText("95")).toBeInTheDocument();
    expect(await screen.findByText(/Live accuracy is disabled/)).toBeInTheDocument();
  });
});
