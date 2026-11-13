import { createBrowserRouter, Outlet, RouterProvider, ScrollRestoration } from "react-router";
import styles from "./App.module.css";
import { LinkButton } from "./components/Button";
import { Footer, TopBar } from "./components/Shell";
import { EmptyState } from "./components/States";
import { AgentPage } from "./pages/AgentPage";
import { AgentsPage } from "./pages/AgentsPage";
import { HomePage } from "./pages/HomePage";
import { RunPage } from "./pages/RunPage";
import { RunsPage } from "./pages/RunsPage";
import { SettingsPage } from "./pages/SettingsPage";

function Layout() {
  return (
    <div className={styles.shell}>
      <TopBar />
      <main className={styles.main}>
        <Outlet />
      </main>
      <Footer />
      <ScrollRestoration />
    </div>
  );
}

function NotFound() {
  return (
    <EmptyState
      label="Not found"
      title="Nothing here"
      action={
        <LinkButton variant="outlined" to="/" icon="back">
          Home
        </LinkButton>
      }
    >
      <p>This page does not exist.</p>
    </EmptyState>
  );
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <HomePage /> },
      { path: "/agents", element: <AgentsPage /> },
      { path: "/agents/:agentId", element: <AgentPage /> },
      { path: "/runs", element: <RunsPage /> },
      { path: "/runs/:runId", element: <RunPage /> },
      { path: "/settings", element: <SettingsPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}
