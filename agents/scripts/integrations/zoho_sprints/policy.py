"""Deterministic Zoho Sprints policy resolver and formatting templates."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

ALLOWED_LANGUAGES = frozenset({"en_titles_ar_comments", "all_en", "all_ar"})
DENIED_TERMINAL_STATUSES = frozenset({"done", "solved", "closed", "completed"})


class ZohoPolicyResolver:
    """Deterministic policy resolver for Zoho Sprints tracker actions."""

    @staticmethod
    def resolve(
        item_type: str,
        task_state: str,
        delivery_state: str = "NONE",
        approved_external_write_scope: Iterable[str] = (),
        configured_language: str = "en_titles_ar_comments",
        commit_hash: str | None = None,
    ) -> dict[str, Any]:
        scopes = set(approved_external_write_scope)
        if "zoho_sprints" not in scopes:
            return {
                "allowed": False,
                "action": "NONE",
                "secondary_action": None,
                "status": None,
                "template": None,
                "requires_commit_hash": False,
                "denied_reason": (
                    "EXTERNAL_WRITE_SCOPE_REQUIRED: zoho_sprints external write scope is required. "
                    "Run 'workflow.py revise --external-write zoho_sprints' and obtain developer approval."
                ),
            }

        itype = str(item_type or "").strip().lower()
        is_bug = itype in ("bug", "defect", "issue")

        # 1. Implementation start transition
        if task_state == "IMPLEMENTING" and delivery_state not in ("GATES_PASSED", "VERIFIED", "READY_FOR_DELIVERY", "DELIVERED"):
            return {
                "allowed": True,
                "action": "UPDATE_STATUS",
                "secondary_action": None,
                "status": "In progress",
                "template": None,
                "requires_commit_hash": False,
                "denied_reason": None,
            }

        # 2. Delivery transition
        is_delivery = (
            delivery_state in ("GATES_PASSED", "VERIFIED", "READY_FOR_DELIVERY", "DELIVERED")
            or task_state in ("READY_FOR_DELIVERY", "DELIVERED")
        )

        if is_delivery:
            if is_bug:
                # ZOHO-001 & ZOHO-002: Bug delivery never edits Description; report goes to Comment
                return {
                    "allowed": True,
                    "action": "ADD_COMMENT",
                    "secondary_action": None,
                    "status": "Ready To ReTest",
                    "template": "BUG_COMMENT",
                    "requires_commit_hash": True,
                    "denied_reason": None,
                }
            else:
                # ZOHO-003 & ZOHO-004: Task/Story report goes to Description; short commit Comment
                tmpl = "STORY_DESCRIPTION" if itype in ("story", "user_story") else "TASK_DESCRIPTION"
                return {
                    "allowed": True,
                    "action": "UPDATE_DESCRIPTION",
                    "secondary_action": "ADD_COMMENT",
                    "status": "Ready To ReTest",
                    "template": tmpl,
                    "requires_commit_hash": True,
                    "denied_reason": None,
                }

        return {
            "allowed": True,
            "action": "NONE",
            "secondary_action": None,
            "status": None,
            "template": None,
            "requires_commit_hash": False,
            "denied_reason": None,
        }

    @staticmethod
    def render_template(
        template_name: str,
        language: str,
        commit_hash: str,
        root_cause_or_objective: str,
        solution_or_changes: str,
        blast_radius: list[str] | str,
        test_cases: list[str] | str,
    ) -> str:
        lang = language if language in ALLOWED_LANGUAGES else "en_titles_ar_comments"
        is_english = (lang == "all_en")

        if isinstance(blast_radius, list):
            blast_str = "\n".join(f"- {b}" for b in blast_radius)
        else:
            blast_str = str(blast_radius or "")

        if isinstance(test_cases, list):
            tc_str = "\n".join(f"{idx}. {tc}" for idx, tc in enumerate(test_cases, 1))
        else:
            tc_str = str(test_cases or "")

        c_hash = str(commit_hash or "").strip()

        if is_english:
            is_bug = "BUG" in template_name
            sec1_header = "Root Cause:" if is_bug else "Objective:"
            sec2_header = "Solution:" if is_bug else "What Changed:"
            return (
                f"Commit: {c_hash}\n\n"
                f"{sec1_header}\n{root_cause_or_objective.strip()}\n\n"
                f"{sec2_header}\n{solution_or_changes.strip()}\n\n"
                f"Impact Area (Blast Radius):\n{blast_str.strip()}\n\n"
                f"Test Cases & Verification Steps:\n{tc_str.strip()}"
            )
        else:
            # Arabic headers
            is_bug = "BUG" in template_name
            sec1_header = "سبب المشكلة:" if is_bug else "الهدف من المهمة:"
            sec2_header = "الحل المطبق:" if is_bug else "ما تم تنفيذه:"
            return (
                f"Commit: {c_hash}\n\n"
                f"{sec1_header}\n{root_cause_or_objective.strip()}\n\n"
                f"{sec2_header}\n{solution_or_changes.strip()}\n\n"
                f"نطاق التأثير (Impact Area):\n{blast_str.strip()}\n\n"
                f"خطوات الفحص وحالات الاختبار (Test Cases):\n{tc_str.strip()}"
            )
