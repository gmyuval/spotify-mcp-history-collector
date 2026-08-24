"""Validate and summarize sanitized GitHub review-evidence bundles."""

import hashlib
import json
import re
import sys

REQUIRED_POPULATIONS = frozenset({"reviews", "issue_comments", "review_threads", "check_runs", "commit_statuses"})
TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "expected_head_sha",
        "observed_head_sha",
        "pull_request",
        "populations",
        "source_audit",
        "findings",
        "mutations",
    }
)
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


def validate_evidence(document: object, expected_head: str) -> list[str]:
    """Return sanitized diagnostics for an untrusted version-1 evidence bundle."""
    issues: list[str] = []
    if not isinstance(document, dict):
        return ["EVIDENCE_SCHEMA_INVALID: root must be an object"]

    missing_fields = sorted(TOP_LEVEL_FIELDS - document.keys())
    unknown_fields = sorted(document.keys() - TOP_LEVEL_FIELDS)
    issues.extend(f"EVIDENCE_FIELD_MISSING: root.{field}" for field in missing_fields)
    issues.extend(f"EVIDENCE_KEY_UNKNOWN: root.{field}" for field in unknown_fields)

    if document.get("schema_version") != 1:
        issues.append("SCHEMA_VERSION_INVALID: root.schema_version")

    if not isinstance(expected_head, str) or not SHA1_RE.fullmatch(expected_head):
        issues.append("HEAD_INVALID: expected_head")
    for field in ("expected_head_sha", "observed_head_sha"):
        value = document.get(field)
        if not isinstance(value, str) or not SHA1_RE.fullmatch(value):
            issues.append(f"HEAD_INVALID: root.{field}")
    if document.get("expected_head_sha") != expected_head:
        issues.append("HEAD_EXPECTED_MISMATCH: root.expected_head_sha")
    if document.get("observed_head_sha") != document.get("expected_head_sha"):
        issues.append("HEAD_DRIFT: root.observed_head_sha")

    pull_request = document.get("pull_request")
    if isinstance(pull_request, dict) and pull_request.get("mergeable") not in {
        "MERGEABLE",
        "CONFLICTING",
        "UNKNOWN",
    }:
        issues.append("ENUM_INVALID: root.pull_request.mergeable")

    populations = document.get("populations")
    if not isinstance(populations, dict) or set(populations) != REQUIRED_POPULATIONS:
        issues.append("POPULATION_SCHEMA_INVALID: root.populations")
    if isinstance(populations, dict):
        audit_records = document.get("source_audit")
        if isinstance(audit_records, list):
            audit_keys = [
                (record.get("source_population"), record.get("source_node_id"))
                for record in audit_records
                if isinstance(record, dict)
            ]
            if len(audit_keys) != len(set(audit_keys)):
                issues.append("SOURCE_AUDIT_DUPLICATE: root.source_audit")
            findings = document.get("findings")
            if isinstance(findings, list):
                known_sources = set(audit_keys)
                for finding in findings:
                    if not isinstance(finding, dict):
                        continue
                    key = (
                        finding.get("source_population"),
                        finding.get("source_node_id"),
                    )
                    if key not in known_sources:
                        issues.append(f"FINDING_SOURCE_UNKNOWN: {key[0]}.{key[1]}")
                    if finding.get("disposition") not in {"fixed", "rejected", "open"}:
                        issues.append("FINDING_DISPOSITION_INVALID: root.findings")
                    if not finding.get("evidence_reference"):
                        issues.append("FINDING_EVIDENCE_EMPTY: root.findings")
                finding_keys = [
                    (
                        finding.get("source_population"),
                        finding.get("source_node_id"),
                        finding.get("key"),
                    )
                    for finding in findings
                    if isinstance(finding, dict)
                ]
                if len(finding_keys) != len(set(finding_keys)):
                    issues.append("FINDING_KEY_DUPLICATE: root.findings")
                for record in audit_records:
                    if not isinstance(record, dict):
                        continue
                    key = (
                        record.get("source_population"),
                        record.get("source_node_id"),
                    )
                    ordinals = [
                        finding.get("ordinal")
                        for finding in findings
                        if isinstance(finding, dict)
                        and (
                            finding.get("source_population"),
                            finding.get("source_node_id"),
                        )
                        == key
                    ]
                    if ordinals != list(range(1, len(ordinals) + 1)):
                        issues.append(f"FINDING_ORDINAL_INVALID: {key[0]}.{key[1]}")
                for record in audit_records:
                    if not isinstance(record, dict):
                        continue
                    key = (
                        record.get("source_population"),
                        record.get("source_node_id"),
                    )
                    actual = sum(
                        1
                        for finding in findings
                        if isinstance(finding, dict)
                        and (
                            finding.get("source_population"),
                            finding.get("source_node_id"),
                        )
                        == key
                    )
                    if record.get("finding_count") != actual:
                        issues.append(f"FINDING_COUNT_MISMATCH: {key[0]}.{key[1]}")
        issues.extend(
            f"POPULATION_MISSING: root.populations.{name}" for name in sorted(REQUIRED_POPULATIONS - populations.keys())
        )
        for name, population in populations.items():
            if isinstance(population, dict) and population.get("total_count") == 0 and population.get("pages") == []:
                issues.append(f"PAGINATION_EMPTY: root.populations.{name}.pages")
            if isinstance(population, dict):
                pages = population.get("pages")
                if (
                    isinstance(pages, list)
                    and pages
                    and isinstance(pages[-1], dict)
                    and isinstance(pages[-1].get("page_info"), dict)
                    and pages[-1]["page_info"].get("has_next_page") is True
                ):
                    issues.append(f"PAGINATION_INCOMPLETE: root.populations.{name}.pages")
                if isinstance(pages, list):
                    for index in range(1, len(pages)):
                        previous = pages[index - 1]
                        current = pages[index]
                        if (
                            isinstance(previous, dict)
                            and isinstance(current, dict)
                            and isinstance(previous.get("page_info"), dict)
                            and current.get("request_cursor") != previous["page_info"].get("end_cursor")
                        ):
                            issues.append(f"PAGINATION_CURSOR_GAP: root.populations.{name}.pages[{index}]")
                    items = [
                        item
                        for page in pages
                        if isinstance(page, dict) and isinstance(page.get("items"), list)
                        for item in page["items"]
                    ]
                    identifiers = [
                        item.get("node_id")
                        for item in items
                        if isinstance(item, dict) and item.get("node_id") is not None
                    ]
                    if len(identifiers) != len(set(identifiers)):
                        issues.append(f"ITEM_ID_DUPLICATE: root.populations.{name}")
                    if population.get("total_count") != len(items):
                        issues.append(f"COUNT_MISMATCH: root.populations.{name}")
                    if name == "check_runs":
                        required = {"node_id", "name", "status", "conclusion", "head_sha"}
                        for index, item in enumerate(items):
                            if not isinstance(item, dict):
                                continue
                            path = f"root.populations.check_runs.items[{index}]"
                            issues.extend(
                                f"EVIDENCE_FIELD_MISSING: {path}.{field}" for field in sorted(required - item.keys())
                            )
                            issues.extend(
                                f"EVIDENCE_KEY_UNKNOWN: {path}.{field}" for field in sorted(item.keys() - required)
                            )
                            if item.get("status") not in {
                                "QUEUED",
                                "IN_PROGRESS",
                                "COMPLETED",
                                "WAITING",
                                "PENDING",
                                "REQUESTED",
                            }:
                                issues.append(f"ENUM_INVALID: {path}.status")
                    if name == "commit_statuses":
                        for index, item in enumerate(items):
                            if isinstance(item, dict) and item.get("state") not in {
                                "ERROR",
                                "FAILURE",
                                "PENDING",
                                "SUCCESS",
                                "EXPECTED",
                            }:
                                issues.append(f"ENUM_INVALID: root.populations.commit_statuses.items[{index}].state")
                    if name == "review_threads":
                        for index, thread in enumerate(items):
                            if not isinstance(thread, dict):
                                continue
                            comments = thread.get("comments")
                            if (
                                isinstance(comments, dict)
                                and comments.get("total_count") == 0
                                and comments.get("pages") == []
                            ):
                                issues.append(
                                    f"PAGINATION_EMPTY: root.populations.review_threads.items[{index}].comments.pages"
                                )
                            if isinstance(comments, dict):
                                comment_pages = comments.get("pages")
                                if (
                                    isinstance(comment_pages, list)
                                    and comment_pages
                                    and isinstance(comment_pages[-1], dict)
                                    and isinstance(comment_pages[-1].get("page_info"), dict)
                                    and comment_pages[-1]["page_info"].get("has_next_page") is True
                                ):
                                    issues.append(
                                        "PAGINATION_INCOMPLETE: "
                                        "root.populations.review_threads."
                                        f"items[{index}].comments.pages"
                                    )
                                if isinstance(comment_pages, list):
                                    for page_index in range(1, len(comment_pages)):
                                        previous = comment_pages[page_index - 1]
                                        current = comment_pages[page_index]
                                        if (
                                            isinstance(previous, dict)
                                            and isinstance(current, dict)
                                            and isinstance(previous.get("page_info"), dict)
                                            and current.get("request_cursor") != previous["page_info"].get("end_cursor")
                                        ):
                                            issues.append(
                                                "PAGINATION_CURSOR_GAP: "
                                                "root.populations.review_threads."
                                                f"items[{index}].comments.pages[{page_index}]"
                                            )
                                    comment_items = [
                                        item
                                        for page in comment_pages
                                        if isinstance(page, dict) and isinstance(page.get("items"), list)
                                        for item in page["items"]
                                    ]
                                    identifiers = [
                                        item.get("node_id")
                                        for item in comment_items
                                        if isinstance(item, dict) and item.get("node_id") is not None
                                    ]
                                    path = f"root.populations.review_threads.items[{index}].comments"
                                    if len(identifiers) != len(set(identifiers)):
                                        issues.append(f"ITEM_ID_DUPLICATE: {path}")
                                    if comments.get("total_count") != len(comment_items):
                                        issues.append(f"COUNT_MISMATCH: {path}")

        reviews = populations.get("reviews")
        if isinstance(reviews, dict) and isinstance(reviews.get("pages"), list):
            audited = {
                (record.get("source_population"), record.get("source_node_id"))
                for record in document.get("source_audit", [])
                if isinstance(record, dict)
            }
            for page in reviews["pages"]:
                if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                    continue
                for item in page["items"]:
                    if (
                        isinstance(item, dict)
                        and isinstance(item.get("body"), str)
                        and ("reviews", item.get("node_id")) not in audited
                    ):
                        issues.append(f"SOURCE_UNAUDITED: reviews.{item.get('node_id')}")

        threads = populations.get("review_threads")
        if isinstance(threads, dict) and isinstance(threads.get("pages"), list):
            audits = {
                (record.get("source_population"), record.get("source_node_id")): record
                for record in document.get("source_audit", [])
                if isinstance(record, dict)
            }
            for page in threads["pages"]:
                if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                    continue
                for thread in page["items"]:
                    comments = thread.get("comments") if isinstance(thread, dict) else None
                    if not isinstance(comments, dict) or not isinstance(comments.get("pages"), list):
                        continue
                    for comment_page in comments["pages"]:
                        for comment in comment_page.get("items", []) if isinstance(comment_page, dict) else []:
                            if not isinstance(comment, dict):
                                continue
                            audit = audits.get(("review_thread_comments", comment.get("node_id")))
                            if isinstance(audit, dict) and audit.get("body_sha256") != comment.get("body_sha256"):
                                issues.append(f"SOURCE_HASH_MISMATCH: review_thread_comments.{comment.get('node_id')}")
                            if isinstance(comment.get("body"), str) and hashlib.sha256(
                                comment["body"].encode("utf-8")
                            ).hexdigest() != comment.get("body_sha256"):
                                issues.append(
                                    f"SOURCE_BODY_HASH_MISMATCH: review_thread_comments.{comment.get('node_id')}"
                                )

        if isinstance(threads, dict) and isinstance(threads.get("pages"), list):
            thread_ids = {
                thread.get("node_id")
                for page in threads["pages"]
                if isinstance(page, dict) and isinstance(page.get("items"), list)
                for thread in page["items"]
                if isinstance(thread, dict)
            }
            for mutation in document.get("mutations", []):
                if not isinstance(mutation, dict):
                    continue
                if mutation.get("expected_head_sha") != document.get("expected_head_sha") or mutation.get(
                    "observed_head_before"
                ) != document.get("observed_head_sha"):
                    issues.append("MUTATION_HEAD_DRIFT: root.mutations")
                operations = mutation.get("operations", [])
                if not isinstance(operations, list) or len(operations) != 2:
                    issues.append("MUTATION_OPERATION_COUNT: root.mutations.operations")
                elif [operation.get("kind") if isinstance(operation, dict) else None for operation in operations] != [
                    "reply",
                    "resolve",
                ]:
                    issues.append("MUTATION_ORDER_INVALID: root.mutations.operations")
                for operation in operations if isinstance(operations, list) else []:
                    if isinstance(operation, dict) and operation.get("thread_node_id") not in thread_ids:
                        issues.append("MUTATION_THREAD_UNKNOWN: root.mutations.operations")
                    created = operation.get("created_comment") if isinstance(operation, dict) else None
                    if isinstance(created, dict) and created.get("node_id") in thread_ids:
                        issues.append("MUTATION_COMMENT_ID_INVALID: root.mutations.operations")
                    readback = operation.get("readback") if isinstance(operation, dict) else None
                    if (
                        isinstance(operation, dict)
                        and operation.get("kind") in {"reply", "resolve"}
                        and not isinstance(readback, dict)
                    ):
                        issues.append("MUTATION_READBACK_INCOMPLETE: root.mutations.operations")
                    if (
                        isinstance(operation, dict)
                        and operation.get("kind") == "reply"
                        and isinstance(readback, dict)
                        and readback.get("body_sha256") != operation.get("expected_body_sha256")
                    ):
                        issues.append("MUTATION_REPLY_HASH_MISMATCH: root.mutations.operations")
                    if (
                        isinstance(operation, dict)
                        and operation.get("kind") == "reply"
                        and isinstance(created, dict)
                        and isinstance(readback, dict)
                        and (
                            created.get("node_id") != readback.get("node_id")
                            or created.get("database_id") != readback.get("database_id")
                        )
                    ):
                        issues.append("MUTATION_REPLY_ID_MISMATCH: root.mutations.operations")
                    response = operation.get("response") if isinstance(operation, dict) else None
                    if (
                        isinstance(operation, dict)
                        and operation.get("kind") == "resolve"
                        and isinstance(response, dict)
                        and isinstance(readback, dict)
                        and (
                            response.get("thread_node_id") != operation.get("thread_node_id")
                            or readback.get("thread_node_id") != operation.get("thread_node_id")
                        )
                    ):
                        issues.append("MUTATION_RESOLUTION_ID_MISMATCH: root.mutations.operations")
                    if (
                        isinstance(operation, dict)
                        and operation.get("kind") == "resolve"
                        and isinstance(response, dict)
                        and isinstance(readback, dict)
                        and (response.get("is_resolved") is not True or readback.get("is_resolved") is not True)
                    ):
                        issues.append("MUTATION_RESOLUTION_UNPROVEN: root.mutations.operations")

    return issues


def summarize_evidence(document: object) -> dict[str, object]:
    """Return a sanitized summary after validation succeeds."""
    if not isinstance(document, dict):
        return {}
    populations = document["populations"]
    findings = document["findings"]
    mutations = document["mutations"]
    return {
        "expected_head_sha": document["expected_head_sha"],
        "observed_head_sha": document["observed_head_sha"],
        "pull_request_number": document["pull_request"]["number"],
        "population_counts": {name: population["total_count"] for name, population in populations.items()},
        "finding_count": len(findings),
        "unresolved_finding_count": sum(finding["disposition"] == "open" for finding in findings),
        "review_in_flight": document["pull_request"]["review_in_flight"],
        "mutation_proof_count": len(mutations),
    }


def main(argv: list[str] | None = None) -> int:
    """Run the review-evidence command-line validator."""
    arguments = sys.argv[1:] if argv is None else argv
    try:
        with open(arguments[0], encoding="utf-8") as evidence_file:
            document = json.loads(evidence_file.read())
    except OSError:
        print("EVIDENCE_UNREADABLE: input", file=sys.stderr)
        return 1
    except UnicodeDecodeError:
        print("EVIDENCE_ENCODING_INVALID: input", file=sys.stderr)
        return 1
    except json.JSONDecodeError:
        print("EVIDENCE_JSON_INVALID: input", file=sys.stderr)
        return 1
    expected_head = document.get("expected_head_sha") if isinstance(document, dict) else None
    issues = validate_evidence(document, expected_head)
    if issues:
        print("\n".join(issues), file=sys.stderr)
        return 1
    print(json.dumps(summarize_evidence(document), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
