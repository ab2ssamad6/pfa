import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import OverviewPage from "./pages/Overview";
import { HostDetailPage, HostsPage } from "./pages/Hosts";
import { IncidentDetailPage, IncidentsPage } from "./pages/Incidents";
import { AnomaliesPage, EventsPage } from "./pages/Lists";
import ModelPage from "./pages/Model";
import { Empty } from "./components/StateViews";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="hosts" element={<HostsPage />} />
        <Route path="hosts/:id" element={<HostDetailPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/:id" element={<IncidentDetailPage />} />
        <Route path="anomalies" element={<AnomaliesPage />} />
        <Route path="events" element={<EventsPage />} />
        <Route path="model" element={<ModelPage />} />
        <Route path="*" element={<Empty>Page not found.</Empty>} />
      </Route>
    </Routes>
  );
}
