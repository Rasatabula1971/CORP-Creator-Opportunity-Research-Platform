import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { CreatorsPage } from "./pages/CreatorsPage";
import { CreatorDetailPage } from "./pages/CreatorDetailPage";
import { CampaignsPage } from "./pages/CampaignsPage";
import { CampaignDetailPage } from "./pages/CampaignDetailPage";
import { RunsPage } from "./pages/RunsPage";
import { JobsPage } from "./pages/JobsPage";
import { RescanPage } from "./pages/RescanPage";
import { NotFoundPage } from "./pages/NotFoundPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<CreatorsPage />} />
        <Route path="/creators/:id" element={<CreatorDetailPage />} />
        <Route path="/campaigns" element={<CampaignsPage />} />
        <Route path="/campaigns/:id" element={<CampaignDetailPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/rescan" element={<RescanPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
