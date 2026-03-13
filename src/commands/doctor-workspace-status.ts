import { resolveAgentWorkspaceDir, resolveDefaultAgentId } from "../agents/agent-scope.js";
import { buildWorkspaceSkillStatus } from "../agents/skills-status.js";
import type { OpenClawConfig } from "../config/config.js";
import { note } from "../terminal/note.js";
import { detectLegacyWorkspaceDirs, formatLegacyWorkspaceWarning } from "./doctor-workspace.js";

export function noteWorkspaceStatus(cfg: OpenClawConfig) {
  const workspaceDir = resolveAgentWorkspaceDir(cfg, resolveDefaultAgentId(cfg));
  const legacyWorkspace = detectLegacyWorkspaceDirs({ workspaceDir });
  if (legacyWorkspace.legacyDirs.length > 0) {
    note(formatLegacyWorkspaceWarning(legacyWorkspace), "Extra workspace");
  }

  const skillsReport = buildWorkspaceSkillStatus(workspaceDir, { config: cfg });
  note(
    [
      `Eligible: ${skillsReport.skills.filter((s) => s.eligible).length}`,
      `Missing requirements: ${
        skillsReport.skills.filter((s) => !s.eligible && !s.disabled && !s.blockedByAllowlist)
          .length
      }`,
      `Blocked by allowlist: ${skillsReport.skills.filter((s) => s.blockedByAllowlist).length}`,
    ].join("\n"),
    "Skills status",
  );

  return { workspaceDir };
}
