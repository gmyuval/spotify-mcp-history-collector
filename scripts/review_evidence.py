"""Validate and summarize sanitized GitHub review-evidence bundles."""

import hashlib
import json
import re
import sys
from collections.abc import Callable

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
SOURCE_POPULATIONS = frozenset({"reviews", "issue_comments", "review_thread_comments"})
MERGEABLE_VALUES = frozenset({"MERGEABLE", "CONFLICTING", "UNKNOWN"})
REVIEW_DECISION_VALUES = frozenset({"APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED", None})
CHECK_STATUS_VALUES = frozenset({"QUEUED", "IN_PROGRESS", "COMPLETED", "WAITING", "REQUESTED", "PENDING"})
CHECK_CONCLUSION_VALUES = frozenset(
    {
        "SUCCESS",
        "FAILURE",
        "NEUTRAL",
        "CANCELLED",
        "SKIPPED",
        "TIMED_OUT",
        "ACTION_REQUIRED",
        "STALE",
        "STARTUP_FAILURE",
    }
)
COMMIT_STATUS_VALUES = frozenset({"EXPECTED", "ERROR", "FAILURE", "PENDING", "SUCCESS"})
FINDING_DISPOSITIONS = frozenset({"fixed", "rejected", "open"})
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_positive_integer(value: object) -> bool:
    return _is_integer(value) and value > 0


def _is_nonnegative_integer(value: object) -> bool:
    return _is_integer(value) and value >= 0


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _exact_object(
    value: object,
    required: frozenset[str] | set[str],
    optional: frozenset[str] | set[str],
    path: str,
    issues: list[str],
) -> dict[object, object] | None:
    if not isinstance(value, dict):
        issues.append(f"EVIDENCE_TYPE_INVALID: {path}")
        return None
    keys = set(value)
    for field in sorted(set(required) - keys):
        issues.append(f"EVIDENCE_FIELD_MISSING: {path}.{field}")
    if any(key not in set(required) | set(optional) for key in keys):
        issues.append(f"EVIDENCE_KEY_UNKNOWN: {path}")
    return value


def _require_string(value: object, path: str, issues: list[str], *, nonempty: bool = False) -> bool:
    valid = _is_nonempty_string(value) if nonempty else isinstance(value, str)
    if not valid:
        issues.append(f"EVIDENCE_TYPE_INVALID: {path}")
    return valid


def _require_positive_integer(value: object, path: str, issues: list[str]) -> bool:
    if not _is_positive_integer(value):
        issues.append(f"EVIDENCE_VALUE_INVALID: {path}")
        return False
    return True


def _require_nonnegative_integer(value: object, path: str, issues: list[str]) -> bool:
    if not _is_nonnegative_integer(value):
        issues.append(f"EVIDENCE_VALUE_INVALID: {path}")
        return False
    return True


def _require_sha1(value: object, path: str, issues: list[str]) -> bool:
    if not isinstance(value, str) or SHA1_RE.fullmatch(value) is None:
        issues.append(f"HEAD_INVALID: {path}")
        return False
    return True


def _require_sha256(value: object, path: str, issues: list[str]) -> bool:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        issues.append(f"SHA256_INVALID: {path}")
        return False
    return True


ItemValidator = Callable[[object, str], dict[object, object] | None]


def _validate_connection(
    value: object,
    path: str,
    item_validator: ItemValidator,
    issues: list[str],
) -> list[dict[object, object]]:
    connection = _exact_object(value, {"total_count", "pages"}, set(), path, issues)
    if connection is None:
        return []
    total_count = connection.get("total_count")
    total_is_valid = _require_nonnegative_integer(total_count, f"{path}.total_count", issues)
    pages = connection.get("pages")
    if not isinstance(pages, list):
        issues.append(f"EVIDENCE_TYPE_INVALID: {path}.pages")
        return []
    if not pages:
        issues.append(f"PAGINATION_EMPTY: {path}.pages")
        return []

    collected: list[dict[object, object]] = []
    page_records: list[dict[object, object] | None] = []
    page_infos: list[dict[object, object] | None] = []
    for page_index, raw_page in enumerate(pages):
        page_path = f"{path}.pages[{page_index}]"
        page = _exact_object(raw_page, {"request_cursor", "items", "page_info"}, set(), page_path, issues)
        page_records.append(page)
        if page is None:
            page_infos.append(None)
            continue
        request_cursor = page.get("request_cursor")
        if request_cursor is not None and not isinstance(request_cursor, str):
            issues.append(f"EVIDENCE_TYPE_INVALID: {page_path}.request_cursor")
        raw_items = page.get("items")
        if not isinstance(raw_items, list):
            issues.append(f"EVIDENCE_TYPE_INVALID: {page_path}.items")
        else:
            for item_index, raw_item in enumerate(raw_items):
                item = item_validator(raw_item, f"{page_path}.items[{item_index}]")
                if item is not None:
                    collected.append(item)
        page_info = _exact_object(
            page.get("page_info"),
            {"has_next_page", "end_cursor"},
            set(),
            f"{page_path}.page_info",
            issues,
        )
        page_infos.append(page_info)
        if page_info is not None:
            if not isinstance(page_info.get("has_next_page"), bool):
                issues.append(f"EVIDENCE_TYPE_INVALID: {page_path}.page_info.has_next_page")
            end_cursor = page_info.get("end_cursor")
            if end_cursor is not None and not isinstance(end_cursor, str):
                issues.append(f"EVIDENCE_TYPE_INVALID: {page_path}.page_info.end_cursor")

    first_page = page_records[0]
    if first_page is not None and first_page.get("request_cursor") is not None:
        issues.append(f"PAGINATION_CURSOR_INVALID: {path}.pages[0]")
    for page_index in range(len(pages) - 1):
        page_info = page_infos[page_index]
        successor = page_records[page_index + 1]
        if page_info is None:
            continue
        if page_info.get("has_next_page") is not True or not isinstance(page_info.get("end_cursor"), str):
            issues.append(f"PAGINATION_INCOMPLETE: {path}.pages[{page_index}]")
        if successor is not None and successor.get("request_cursor") != page_info.get("end_cursor"):
            issues.append(f"PAGINATION_CURSOR_GAP: {path}.pages[{page_index + 1}]")
    final_info = page_infos[-1]
    if final_info is not None and (
        final_info.get("has_next_page") is not False or final_info.get("end_cursor") is not None
    ):
        issues.append(f"PAGINATION_INCOMPLETE: {path}.pages")

    if total_is_valid and total_count != len(collected):
        issues.append(f"COUNT_MISMATCH: {path}")
    identifiers = [item.get("node_id") for item in collected if _is_nonempty_string(item.get("node_id"))]
    if len(identifiers) != len(set(identifiers)):
        issues.append(f"ITEM_ID_DUPLICATE: {path}")
    return collected


def validate_evidence(document: object, expected_head: str) -> list[str]:
    """Return fixed-code, fixed-path diagnostics for an untrusted bundle."""
    issues: list[str] = []
    root = _exact_object(document, TOP_LEVEL_FIELDS, set(), "root", issues)
    if root is None:
        return issues
    if not _is_integer(root.get("schema_version")) or root.get("schema_version") != 1:
        issues.append("SCHEMA_VERSION_INVALID: root.schema_version")
    expected_is_valid = _require_sha1(expected_head, "expected_head", issues)
    _require_sha1(root.get("expected_head_sha"), "root.expected_head_sha", issues)
    _require_sha1(root.get("observed_head_sha"), "root.observed_head_sha", issues)
    if root.get("expected_head_sha") != expected_head:
        issues.append("HEAD_EXPECTED_MISMATCH: root.expected_head_sha")
    if root.get("observed_head_sha") != expected_head:
        issues.append("HEAD_DRIFT: root.observed_head_sha")

    pull_request = _exact_object(
        root.get("pull_request"),
        {"number", "mergeable", "review_decision", "review_in_flight"},
        set(),
        "root.pull_request",
        issues,
    )
    if pull_request is not None:
        _require_positive_integer(pull_request.get("number"), "root.pull_request.number", issues)
        mergeable = pull_request.get("mergeable")
        if not isinstance(mergeable, str) or mergeable not in MERGEABLE_VALUES:
            issues.append("ENUM_INVALID: root.pull_request.mergeable")
        review_decision = pull_request.get("review_decision")
        if review_decision is not None and (
            not isinstance(review_decision, str) or review_decision not in REVIEW_DECISION_VALUES
        ):
            issues.append("ENUM_INVALID: root.pull_request.review_decision")
        if not isinstance(pull_request.get("review_in_flight"), bool):
            issues.append("EVIDENCE_TYPE_INVALID: root.pull_request.review_in_flight")

    populations = _exact_object(root.get("populations"), REQUIRED_POPULATIONS, set(), "root.populations", issues)
    if populations is None:
        issues.append("POPULATION_SCHEMA_INVALID: root.populations")
        populations = {}
    else:
        for name in sorted(REQUIRED_POPULATIONS - set(populations)):
            issues.append(f"POPULATION_MISSING: root.populations.{name}")
        if set(populations) != REQUIRED_POPULATIONS:
            issues.append("POPULATION_SCHEMA_INVALID: root.populations")

    sources: dict[tuple[str, str], object] = {}
    review_comment_ids: list[str] = []

    def validate_content_body(record: dict[object, object], path: str) -> None:
        body_hash = record.get("body_sha256")
        _require_sha256(body_hash, f"{path}.body_sha256", issues)
        if "body" in record:
            body = record.get("body")
            if not isinstance(body, str):
                issues.append(f"EVIDENCE_TYPE_INVALID: {path}.body")
            elif hashlib.sha256(body.encode("utf-8")).hexdigest() != body_hash:
                issues.append(f"SOURCE_BODY_HASH_MISMATCH: {path}")

    def validate_review(value: object, path: str) -> dict[object, object] | None:
        record = _exact_object(value, {"node_id", "submitted_commit_sha", "body_sha256"}, {"body"}, path, issues)
        if record is None:
            return None
        node_id = record.get("node_id")
        _require_string(node_id, f"{path}.node_id", issues, nonempty=True)
        _require_sha1(record.get("submitted_commit_sha"), f"{path}.submitted_commit_sha", issues)
        if record.get("submitted_commit_sha") != expected_head:
            issues.append(f"HEAD_DRIFT: {path}.submitted_commit_sha")
        validate_content_body(record, path)
        if isinstance(node_id, str):
            sources[("reviews", node_id)] = record.get("body_sha256")
        return record

    def validate_issue_comment(value: object, path: str) -> dict[object, object] | None:
        record = _exact_object(value, {"node_id", "database_id", "body_sha256"}, {"body"}, path, issues)
        if record is None:
            return None
        node_id = record.get("node_id")
        _require_string(node_id, f"{path}.node_id", issues, nonempty=True)
        _require_positive_integer(record.get("database_id"), f"{path}.database_id", issues)
        validate_content_body(record, path)
        if isinstance(node_id, str):
            sources[("issue_comments", node_id)] = record.get("body_sha256")
        return record

    def validate_review_comment(value: object, path: str) -> dict[object, object] | None:
        record = _exact_object(
            value,
            {"node_id", "database_id", "reply_to_node_id", "body_sha256"},
            {"body"},
            path,
            issues,
        )
        if record is None:
            return None
        node_id = record.get("node_id")
        _require_string(node_id, f"{path}.node_id", issues, nonempty=True)
        _require_positive_integer(record.get("database_id"), f"{path}.database_id", issues)
        reply_to = record.get("reply_to_node_id")
        if reply_to is not None:
            _require_string(reply_to, f"{path}.reply_to_node_id", issues, nonempty=True)
        validate_content_body(record, path)
        if isinstance(node_id, str):
            sources[("review_thread_comments", node_id)] = record.get("body_sha256")
            review_comment_ids.append(node_id)
        return record

    def validate_thread(value: object, path: str) -> dict[object, object] | None:
        record = _exact_object(value, {"node_id", "is_resolved", "comments"}, set(), path, issues)
        if record is None:
            return None
        _require_string(record.get("node_id"), f"{path}.node_id", issues, nonempty=True)
        if not isinstance(record.get("is_resolved"), bool):
            issues.append(f"EVIDENCE_TYPE_INVALID: {path}.is_resolved")
        _validate_connection(record.get("comments"), f"{path}.comments", validate_review_comment, issues)
        return record

    def validate_check_run(value: object, path: str) -> dict[object, object] | None:
        record = _exact_object(
            value,
            {"node_id", "name", "status", "conclusion", "head_sha"},
            set(),
            path,
            issues,
        )
        if record is None:
            return None
        _require_string(record.get("node_id"), f"{path}.node_id", issues, nonempty=True)
        _require_string(record.get("name"), f"{path}.name", issues)
        status = record.get("status")
        conclusion = record.get("conclusion")
        if not isinstance(status, str) or status not in CHECK_STATUS_VALUES:
            issues.append(f"ENUM_INVALID: {path}.status")
        if (
            status == "COMPLETED" and (not isinstance(conclusion, str) or conclusion not in CHECK_CONCLUSION_VALUES)
        ) or (status != "COMPLETED" and conclusion is not None):
            issues.append(f"ENUM_INVALID: {path}.conclusion")
        _require_sha1(record.get("head_sha"), f"{path}.head_sha", issues)
        if record.get("head_sha") != expected_head:
            issues.append("HEAD_DRIFT: root.populations.check_runs")
        return record

    def validate_commit_status(value: object, path: str) -> dict[object, object] | None:
        record = _exact_object(value, {"node_id", "context", "state", "commit_sha"}, set(), path, issues)
        if record is None:
            return None
        _require_string(record.get("node_id"), f"{path}.node_id", issues, nonempty=True)
        _require_string(record.get("context"), f"{path}.context", issues)
        state = record.get("state")
        if not isinstance(state, str) or state not in COMMIT_STATUS_VALUES:
            issues.append(f"ENUM_INVALID: {path}.state")
        _require_sha1(record.get("commit_sha"), f"{path}.commit_sha", issues)
        if record.get("commit_sha") != expected_head:
            issues.append("HEAD_DRIFT: root.populations.commit_statuses")
        return record

    validators: dict[str, ItemValidator] = {
        "reviews": validate_review,
        "issue_comments": validate_issue_comment,
        "review_threads": validate_thread,
        "check_runs": validate_check_run,
        "commit_statuses": validate_commit_status,
    }
    population_items: dict[str, list[dict[object, object]]] = {}
    for name in sorted(REQUIRED_POPULATIONS):
        if name in populations:
            population_items[name] = _validate_connection(
                populations.get(name), f"root.populations.{name}", validators[name], issues
            )
        else:
            population_items[name] = []
    if len(review_comment_ids) != len(set(review_comment_ids)):
        issues.append("ITEM_ID_DUPLICATE: root.populations.review_threads.comments")

    audits_value = root.get("source_audit")
    if not isinstance(audits_value, list):
        issues.append("EVIDENCE_TYPE_INVALID: root.source_audit")
        audits_value = []
    audit_records: dict[tuple[str, str], dict[object, object]] = {}
    for audit_index, value in enumerate(audits_value):
        path = f"root.source_audit[{audit_index}]"
        audit = _exact_object(
            value,
            {"source_population", "source_node_id", "body_sha256", "finding_count"},
            set(),
            path,
            issues,
        )
        if audit is None:
            continue
        source_population = audit.get("source_population")
        source_node_id = audit.get("source_node_id")
        if not isinstance(source_population, str) or source_population not in SOURCE_POPULATIONS:
            issues.append(f"ENUM_INVALID: {path}.source_population")
        _require_string(source_node_id, f"{path}.source_node_id", issues, nonempty=True)
        _require_sha256(audit.get("body_sha256"), f"{path}.body_sha256", issues)
        _require_nonnegative_integer(audit.get("finding_count"), f"{path}.finding_count", issues)
        if not isinstance(source_population, str) or not isinstance(source_node_id, str):
            continue
        key = (source_population, source_node_id)
        if key in audit_records:
            issues.append("SOURCE_AUDIT_DUPLICATE: root.source_audit")
        else:
            audit_records[key] = audit
        if key not in sources:
            issues.append("SOURCE_AUDIT_SOURCE_UNKNOWN: root.source_audit")
        elif audit.get("body_sha256") != sources[key]:
            issues.append("SOURCE_HASH_MISMATCH: root.source_audit")
    for key in sources:
        if key not in audit_records:
            issues.append(f"SOURCE_UNAUDITED: {key[0]}")

    findings_value = root.get("findings")
    if not isinstance(findings_value, list):
        issues.append("EVIDENCE_TYPE_INVALID: root.findings")
        findings_value = []
    findings_by_source: dict[tuple[str, str], list[dict[object, object]]] = {}
    finding_keys: set[tuple[str, str, str]] = set()
    for finding_index, value in enumerate(findings_value):
        path = f"root.findings[{finding_index}]"
        finding = _exact_object(
            value,
            {"key", "source_population", "source_node_id", "ordinal", "disposition", "evidence_reference"},
            set(),
            path,
            issues,
        )
        if finding is None:
            continue
        source_population = finding.get("source_population")
        source_node_id = finding.get("source_node_id")
        key_value = finding.get("key")
        if not isinstance(source_population, str) or source_population not in SOURCE_POPULATIONS:
            issues.append(f"ENUM_INVALID: {path}.source_population")
        _require_string(source_node_id, f"{path}.source_node_id", issues, nonempty=True)
        _require_positive_integer(finding.get("ordinal"), f"{path}.ordinal", issues)
        _require_string(key_value, f"{path}.key", issues, nonempty=True)
        if isinstance(source_population, str) and isinstance(source_node_id, str) and isinstance(key_value, str):
            local_key = (source_population, source_node_id, key_value)
            if local_key in finding_keys:
                issues.append("FINDING_KEY_DUPLICATE: root.findings")
            finding_keys.add(local_key)
        disposition = finding.get("disposition")
        if not isinstance(disposition, str) or disposition not in FINDING_DISPOSITIONS:
            issues.append("FINDING_DISPOSITION_INVALID: root.findings")
        if not _is_nonempty_string(finding.get("evidence_reference")):
            issues.append("FINDING_EVIDENCE_EMPTY: root.findings")
        if isinstance(source_population, str) and isinstance(source_node_id, str):
            source_key = (source_population, source_node_id)
            findings_by_source.setdefault(source_key, []).append(finding)
            if source_key not in sources or source_key not in audit_records:
                issues.append("FINDING_SOURCE_UNKNOWN: root.findings")
    for source_key, audit in audit_records.items():
        records = findings_by_source.get(source_key, [])
        if audit.get("finding_count") != len(records):
            issues.append("FINDING_COUNT_MISMATCH: root.source_audit")
        ordinals = [record.get("ordinal") for record in records]
        if not all(_is_positive_integer(ordinal) for ordinal in ordinals) or sorted(ordinals) != list(
            range(1, len(records) + 1)
        ):
            issues.append("FINDING_ORDINAL_INVALID: root.findings")

    thread_ids = {
        item.get("node_id")
        for item in population_items.get("review_threads", [])
        if _is_nonempty_string(item.get("node_id"))
    }
    mutations_value = root.get("mutations")
    if not isinstance(mutations_value, list):
        issues.append("EVIDENCE_TYPE_INVALID: root.mutations")
        mutations_value = []
    for mutation_index, value in enumerate(mutations_value):
        mutation_path = f"root.mutations[{mutation_index}]"
        mutation = _exact_object(
            value,
            {"expected_head_sha", "observed_head_before", "operations"},
            set(),
            mutation_path,
            issues,
        )
        if mutation is None:
            continue
        _require_sha1(mutation.get("expected_head_sha"), f"{mutation_path}.expected_head_sha", issues)
        _require_sha1(mutation.get("observed_head_before"), f"{mutation_path}.observed_head_before", issues)
        if (
            mutation.get("expected_head_sha") != expected_head
            or mutation.get("observed_head_before") != expected_head
            or not expected_is_valid
        ):
            issues.append("MUTATION_HEAD_DRIFT: root.mutations")
        operations = mutation.get("operations")
        if not isinstance(operations, list):
            issues.append(f"EVIDENCE_TYPE_INVALID: {mutation_path}.operations")
            issues.append("MUTATION_OPERATION_COUNT: root.mutations.operations")
            continue
        if len(operations) != 2:
            issues.append("MUTATION_OPERATION_COUNT: root.mutations.operations")
        reply_record = _exact_object(
            operations[0] if operations else None,
            {"sequence", "kind", "thread_node_id", "created_comment", "expected_body_sha256", "readback"},
            set(),
            f"{mutation_path}.operations[0]",
            issues,
        )
        resolve_record = _exact_object(
            operations[1] if len(operations) > 1 else None,
            {"sequence", "kind", "thread_node_id", "response", "readback"},
            set(),
            f"{mutation_path}.operations[1]",
            issues,
        )
        if reply_record is None or resolve_record is None:
            continue
        if (
            not _is_integer(reply_record.get("sequence"))
            or reply_record.get("sequence") != 1
            or reply_record.get("kind") != "reply"
            or not _is_integer(resolve_record.get("sequence"))
            or resolve_record.get("sequence") != 2
            or resolve_record.get("kind") != "resolve"
        ):
            issues.append("MUTATION_ORDER_INVALID: root.mutations.operations")
        reply_thread = reply_record.get("thread_node_id")
        resolve_thread = resolve_record.get("thread_node_id")
        _require_string(reply_thread, f"{mutation_path}.operations[0].thread_node_id", issues, nonempty=True)
        _require_string(resolve_thread, f"{mutation_path}.operations[1].thread_node_id", issues, nonempty=True)
        if (
            not isinstance(reply_thread, str)
            or reply_thread not in thread_ids
            or not isinstance(resolve_thread, str)
            or resolve_thread not in thread_ids
        ):
            issues.append("MUTATION_THREAD_UNKNOWN: root.mutations.operations")
        if reply_thread != resolve_thread:
            issues.append("MUTATION_RESOLUTION_ID_MISMATCH: root.mutations.operations")

        created = _exact_object(
            reply_record.get("created_comment"),
            {"node_id", "database_id"},
            set(),
            f"{mutation_path}.operations[0].created_comment",
            issues,
        )
        if created is None:
            issues.append("MUTATION_FIELD_MISSING: root.mutations.operations.created_comment")
        reply_readback = _exact_object(
            reply_record.get("readback"),
            {"node_id", "database_id", "body_sha256"},
            set(),
            f"{mutation_path}.operations[0].readback",
            issues,
        )
        if reply_readback is None:
            issues.append("MUTATION_READBACK_INCOMPLETE: root.mutations.operations")
        expected_body_hash = reply_record.get("expected_body_sha256")
        _require_sha256(expected_body_hash, f"{mutation_path}.operations[0].expected_body_sha256", issues)
        if created is not None:
            created_node_id = created.get("node_id")
            _require_string(
                created_node_id, f"{mutation_path}.operations[0].created_comment.node_id", issues, nonempty=True
            )
            _require_positive_integer(
                created.get("database_id"), f"{mutation_path}.operations[0].created_comment.database_id", issues
            )
            if isinstance(created_node_id, str) and (
                created_node_id in thread_ids or created_node_id in review_comment_ids
            ):
                issues.append("MUTATION_COMMENT_ID_INVALID: root.mutations.operations")
        if reply_readback is not None:
            _require_string(
                reply_readback.get("node_id"), f"{mutation_path}.operations[0].readback.node_id", issues, nonempty=True
            )
            _require_positive_integer(
                reply_readback.get("database_id"), f"{mutation_path}.operations[0].readback.database_id", issues
            )
            _require_sha256(
                reply_readback.get("body_sha256"), f"{mutation_path}.operations[0].readback.body_sha256", issues
            )
            if reply_readback.get("body_sha256") != expected_body_hash:
                issues.append("MUTATION_REPLY_HASH_MISMATCH: root.mutations.operations")
            if created is not None and (
                created.get("node_id") != reply_readback.get("node_id")
                or created.get("database_id") != reply_readback.get("database_id")
            ):
                issues.append("MUTATION_REPLY_ID_MISMATCH: root.mutations.operations")

        response = _exact_object(
            resolve_record.get("response"),
            {"thread_node_id", "is_resolved"},
            set(),
            f"{mutation_path}.operations[1].response",
            issues,
        )
        if response is None:
            issues.append("MUTATION_FIELD_MISSING: root.mutations.operations.response")
        resolve_readback = _exact_object(
            resolve_record.get("readback"),
            {"thread_node_id", "is_resolved"},
            set(),
            f"{mutation_path}.operations[1].readback",
            issues,
        )
        if resolve_readback is None:
            issues.append("MUTATION_READBACK_INCOMPLETE: root.mutations.operations")
        for name, record in (("response", response), ("readback", resolve_readback)):
            if record is None:
                continue
            _require_string(
                record.get("thread_node_id"),
                f"{mutation_path}.operations[1].{name}.thread_node_id",
                issues,
                nonempty=True,
            )
            if not isinstance(record.get("is_resolved"), bool):
                issues.append(f"EVIDENCE_TYPE_INVALID: {mutation_path}.operations[1].{name}.is_resolved")
        if response is not None and resolve_readback is not None:
            if (
                response.get("thread_node_id") != resolve_thread
                or resolve_readback.get("thread_node_id") != resolve_thread
            ):
                issues.append("MUTATION_RESOLUTION_ID_MISMATCH: root.mutations.operations")
            if response.get("is_resolved") is not True or resolve_readback.get("is_resolved") is not True:
                issues.append("MUTATION_RESOLUTION_UNPROVEN: root.mutations.operations")

    return issues


def summarize_evidence(document: object) -> dict[str, object]:
    """Return a sanitized summary after validation succeeds."""
    if not isinstance(document, dict):
        return {}
    try:
        populations = document["populations"]
        findings = document["findings"]
        mutations = document["mutations"]
        return {
            "expected_head_sha": document["expected_head_sha"],
            "observed_head_sha": document["observed_head_sha"],
            "pull_request_number": document["pull_request"]["number"],
            "population_counts": {name: populations[name]["total_count"] for name in sorted(REQUIRED_POPULATIONS)},
            "finding_count": len(findings),
            "unresolved_finding_count": sum(finding["disposition"] == "open" for finding in findings),
            "review_in_flight": document["pull_request"]["review_in_flight"],
            "mutation_proof_count": len(mutations),
        }
    except KeyError, TypeError:
        return {}


def main(argv: list[str] | None = None) -> int:
    """Run the review-evidence command-line validator."""
    arguments = sys.argv[1:] if argv is None else argv
    if (
        len(arguments) != 3
        or arguments[1] != "--expected-head"
        or not isinstance(arguments[0], str)
        or not isinstance(arguments[2], str)
    ):
        print("EVIDENCE_ARGUMENTS_INVALID: usage", file=sys.stderr)
        return 1
    expected_head = arguments[2]
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
    issues = validate_evidence(document, expected_head)
    if issues:
        print("\n".join(issues), file=sys.stderr)
        return 1
    print(json.dumps(summarize_evidence(document), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
