import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { CreatorsPage } from "./pages/CreatorsPage";
import { CreatorDetailPage } from "./pages/CreatorDetailPage";
import { RunsPage } from "./pages/RunsPage";
import { JobsPage } from "./pages/JobsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<CreatorsPage />} />
        <Route path="/creators/:id" element={<CreatorDetailPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/jobs" element={<JobsPage />} />
      </Route>
    </Routes>
  );
}
