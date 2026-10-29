/**
 * Per-agent views, looked up by agent id:
 * - result views: an agent without one gets the generic viewer, which works for every
 *   AgentResult;
 * - intros: an optional panel on the agent's page that explains what the agent does,
 *   shown under its name. Agents without one just show their description.
 * The AI Code Detector has both, built in.
 */
import type { ComponentType } from "react";
import type { AgentInfo, AgentResult, RunView } from "../api/client";
import { DetectorIntro } from "./detector/DetectorIntro";
import { DetectorResult } from "./detector/DetectorResult";
import { GenericResult } from "./GenericResult";
import { StorytellerResult } from "./storyteller/StorytellerResult";

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
