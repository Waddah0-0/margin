/**
 * Per-agent views, looked up by agent id:
 * - result views: an agent without one gets the generic viewer, which works for every
 *   AgentResult;
 * - intros: an optional panel on the agent's page that explains what the agent does,
 *   shown under its name. Agents without one just show their description.
 * The AI Code Detector has both, built in.
 *
 * The built-in views are loaded when first shown, so their code (charts, the file explorer)
 * stays out of the pages that never need it. Render them inside a Suspense boundary.
 */
import { type ComponentType, lazy } from "react";
import type { AgentInfo, AgentResult, RunView } from "../api/client";
import { GenericResult } from "./GenericResult";

const DetectorResult = lazy(() =>
  import("./detector/DetectorResult").then((m) => ({ default: m.DetectorResult })),
);
const DetectorIntro = lazy(() =>
  import("./detector/DetectorIntro").then((m) => ({ default: m.DetectorIntro })),
);
const StorytellerResult = lazy(() =>
  import("./storyteller/StorytellerResult").then((m) => ({ default: m.StorytellerResult })),
);

export interface ResultViewProps {
  run: RunView;
  result: AgentResult;
}

export interface AgentIntroProps {
  agent: AgentInfo;
}

const views = new Map<string, ComponentType<ResultViewProps>>([
  ["ai-code-detector", DetectorResult],
  ["data-storyteller", StorytellerResult],
]);
const intros = new Map<string, ComponentType<AgentIntroProps>>([["ai-code-detector", DetectorIntro]]);

export function registerResultView(agentId: string, view: ComponentType<ResultViewProps>): void {
  views.set(agentId, view);
}

export function resultViewFor(agentId: string): ComponentType<ResultViewProps> {
  return views.get(agentId) ?? GenericResult;
}

export function registerAgentIntro(agentId: string, intro: ComponentType<AgentIntroProps>): void {
  intros.set(agentId, intro);
}

export function agentIntroFor(agentId: string): ComponentType<AgentIntroProps> | undefined {
  return intros.get(agentId);
}
