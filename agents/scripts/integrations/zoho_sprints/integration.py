"""Zoho Sprints external integration implementation."""
from __future__ import annotations

from typing import Any, Mapping
from integrations.base import ExternalIntegration

ZOHO_MUTATION_TOOLS = frozenset({
    "zoho_create_task",
    "zoho_update_task_status",
    "zoho_add_comment",
    "zoho_update_task_description",
})

ZOHO_READ_TOOLS = frozenset({
    "zoho_list_sprints",
    "zoho_list_tasks",
    "zoho_get_task_details",
    "zoho_list_task_attachments",
})

ZOHO_MUTATION_VERBS = ("create", "update", "delete", "close", "add_comment")


class ZohoSprintsIntegration(ExternalIntegration):
    """ExternalIntegration implementation for Zoho Sprints."""

    name = "zoho_sprints"
    display_name = "Zoho"

    def matches(self, server: str, tool_name: str) -> bool:
        server_lower = (server or "").lower().strip()
        tool_lower = (tool_name or "").lower().strip()
        if "zoho-projects" in server_lower or "zoho_projects" in server_lower or tool_lower.startswith("zohoprojects_"):
            return False
        if "zoho" in server_lower or "zoho" in tool_lower:
            return True
        if tool_lower in ZOHO_MUTATION_TOOLS or tool_lower in ZOHO_READ_TOOLS:
            return True
        return False

    def is_read_only(self, tool_name: str, args: Mapping[str, Any]) -> bool:
        tool_lower = (tool_name or "").lower().strip()
        if tool_lower in ZOHO_READ_TOOLS:
            return True
        if tool_lower in ZOHO_MUTATION_TOOLS:
            return False
        if any(verb in tool_lower for verb in ZOHO_MUTATION_VERBS):
            return False
        return True

    def validate_mutation(
        self,
        tool_name: str,
        args: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> tuple[bool, str]:
        status_req = str(args.get("status") or "").strip().lower()
        if status_req in ("done", "solved", "closed", "completed"):
            return False, "ZOHO_POLICY_VIOLATION: Terminal tracker states (Done/Solved) are developer-owned and cannot be automated."

        z_link = plan.get("zoho_link") if isinstance(plan, Mapping) and isinstance(plan.get("zoho_link"), Mapping) else {}
        item_type = str(args.get("item_type") or args.get("type") or z_link.get("item_type") or "").strip().lower()
        if str(tool_name or "").strip().lower() == "zoho_update_task_description" and item_type in ("bug", "defect", "issue"):
            return False, "ZOHO_POLICY_VIOLATION: Editing Bug description is strictly prohibited. Bug delivery reports must be added as a Comment to preserve QA original bug report."

        if status_req in ("ready to retest", "ready for retest"):
            content = str(args.get("comment") or args.get("description") or args.get("content") or "")
            commit_hash = str(args.get("commit_hash") or args.get("commit") or "")
            if not commit_hash and "commit:" not in content.lower():
                return False, "ZOHO_POLICY_VIOLATION: Ready To ReTest delivery report requires a valid Git commit hash."

        ok, notes_reason = self._validate_project_notes_zoho_rules(tool_name, args, plan, item_type)
        if not ok:
            return False, notes_reason

        return True, ""

    @staticmethod
    def _validate_project_notes_zoho_rules(
        tool_name: str,
        args: Mapping[str, Any],
        plan: Mapping[str, Any],
        item_type: str = "",
    ) -> tuple[bool, str]:
        import os
        import re
        from pathlib import Path
        from pm_discovery import classify_pm_tool

        repo_raw = (
            (plan.get("repository") or plan.get("repo_root")) if isinstance(plan, Mapping) else None
        ) or os.environ.get("HARNESS_REPO")
        repo_path: Path | None = None
        if repo_raw:
            cand = Path(str(repo_raw))
            if cand.is_dir():
                repo_path = cand
        if repo_path is None:
            try:
                from _repo_files import REPO
                if REPO.is_dir():
                    repo_path = REPO
            except (ImportError, OSError):
                repo_path = None
        if repo_path is None:
            return True, ""

        try:
            from project_context import extract_pm_notes_section, load_project_notes
            notes = load_project_notes(repo_path)
            if not notes.get("has_custom_notes"):
                return True, ""
            zoho_section = extract_pm_notes_section(notes.get("content") or "")
        except (ImportError, OSError, ValueError, KeyError):
            return True, ""

        if not zoho_section:
            return True, ""

        zoho_lower = zoho_section.lower()
        tl = str(tool_name or "").strip().lower()
        tool_class = classify_pm_tool(tl, args)

        fields_obj = args.get("fields") if isinstance(args.get("fields"), Mapping) else {}
        if not item_type:
            item_type = str(
                args.get("item_type")
                or args.get("type")
                or args.get("issue_type")
                or args.get("issuetype")
                or (fields_obj.get("issuetype", {}).get("name") if isinstance(fields_obj.get("issuetype"), Mapping) else "")
                or ""
            ).strip().lower()
        is_bug = item_type in ("bug", "defect", "issue") or "issue" in tl or "bug" in tl

        desc = str(
            args.get("description")
            or fields_obj.get("description")
            or ""
        ).strip()
        comment_or_body = str(
            desc
            or args.get("comment")
            or args.get("notes")
            or args.get("body")
            or args.get("content")
            or fields_obj.get("comment")
            or ""
        ).strip()

        is_desc_mutation = (
            tl in ("zoho_create_task", "zoho_update_task_description")
            or (tool_class in ("CREATE", "UPDATE_DESCRIPTION") and bool(desc))
            or (tool_class == "WRITE" and bool(desc))
        )
        requires_rtl_html = ("<div dir=\"rtl\"" in zoho_section or "<div dir='rtl'" in zoho_section)
        if requires_rtl_html and is_desc_mutation and not is_bug:
            requires_table = "<table" in zoho_lower
            has_rtl_div = ("<div dir=\"rtl\"" in desc or "<div dir='rtl'" in desc)
            if not desc or not has_rtl_div or "<h3>" not in desc or (requires_table and "<table" not in desc):
                return False, (
                    "ZOHO_PROJECT_NOTES_VIOLATION: .agents/project-context/project-notes.md requires Task/Story "
                    "descriptions to use the mandatory 5-section Arabic HTML template (<div dir=\"rtl\" ...> with "
                    "<h3> headings and a Manual QA <table>). Read .agents/project-context/project-notes.md and "
                    "format the description using the exact HTML template."
                )

        if (
            "no code/file artifacts" in zoho_lower
            or "no code or file artifacts" in zoho_lower
            or "forbid raw class" in zoho_lower
            or "raw class/function names" in zoho_lower
        ) and bool(comment_or_body):
            raw_body = comment_or_body
            if raw_body and not re.fullmatch(r"Commit:\s*[0-9a-fA-F]{7,40}", raw_body, re.I):
                plain = re.sub(r"<[^>]+>", " ", raw_body)
                file_hits = re.findall(r"\b[A-Za-z0-9_/-]+\.(?:kt|java|xml|kts|gradle)\b", plain)
                class_hits = re.findall(
                    r"\b[A-Za-z0-9_]+(?:ViewModel|Fragment|Activity|Repository|RepositoryImpl|RepositoryTest|"
                    r"DataSource|UseCase|BottomSheet|BannerCard|Composable|Adapter|Dao|Entity|Helper)\b",
                    plain,
                )
                allowed_terms = {
                    "JetpackCompose", "MaterialTheme", "ZohoSprints", "ZohoProjects", "GooglePlay", "PlayStore",
                    "HealthConnect", "CustomTabs", "DeepLink", "DarkMode", "UnitTests", "ManualQA",
                    "BlastRadius", "RootCause", "WhatChanged", "ImpactArea", "TestCases", "AcceptanceCriteria",
                }
                camel_hits = [
                    m for m in re.findall(
                        r"\b(?:[A-Z][a-z0-9]+){2,}[A-Za-z0-9]*\b|\b[a-z]+(?:[A-Z][a-z0-9]+){2,}[A-Za-z0-9]*\b",
                        plain,
                    )
                    if m not in allowed_terms
                ]
                found = list(dict.fromkeys(file_hits + class_hits + camel_hits))
                if found:
                    return False, (
                        "ZOHO_PROJECT_NOTES_VIOLATION: .agents/project-context/project-notes.md strictly forbids "
                        f"raw code/class/file names in PM descriptions/comments (found: {', '.join(found[:5])}). "
                        "Replace them with user-facing Arabic functional names as required by .agents/project-context/project-notes.md."
                    )

        if ("dark mode compatibility" in zoho_lower or "#2c3e50" in zoho_lower) and bool(comment_or_body):
            raw_lower = comment_or_body.lower()
            if "#2c3e50" in raw_lower or "#000000" in raw_lower:
                return False, (
                    "ZOHO_PROJECT_NOTES_VIOLATION: .agents/project-context/project-notes.md forbids hardcoded dark "
                    "colors (#2c3e50, #000000) for Dark Mode compatibility. Use inherit / rgba(128,128,128,0.15) "
                    "as specified in .agents/project-context/project-notes.md."
                )

        return True, ""
