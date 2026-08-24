"""Contract tests for the complete SPM-32 review-evidence bundle."""

import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.review_evidence import main, validate_evidence

FIXTURES = Path(__file__).parent / "fixtures" / "review-evidence"


def complete_bundle() -> dict[str, object]:
    return json.loads((FIXTURES / "complete.json").read_text(encoding="utf-8"))


def full_domain_bundle() -> dict[str, object]:
    """Return a valid bundle containing every optional record domain."""
    document = complete_bundle()
    reviews = document["populations"]["reviews"]
    reviews["total_count"] = 1
    reviews["pages"][0]["items"] = [
        {
            "node_id": "review-node-1",
            "submitted_commit_sha": "0" * 40,
            "body_sha256": "c" * 64,
        }
    ]
    issue_comments = document["populations"]["issue_comments"]
    issue_comments["total_count"] = 1
    issue_comments["pages"][0]["items"] = [
        {
            "node_id": "issue-comment-node-1",
            "database_id": 201,
            "body_sha256": "d" * 64,
        }
    ]
    document["source_audit"].extend(
        [
            {
                "source_population": "reviews",
                "source_node_id": "review-node-1",
                "body_sha256": "c" * 64,
                "finding_count": 1,
            },
            {
                "source_population": "issue_comments",
                "source_node_id": "issue-comment-node-1",
                "body_sha256": "d" * 64,
                "finding_count": 0,
            },
        ]
    )
    document["findings"] = [
        {
            "key": "finding-1",
            "source_population": "reviews",
            "source_node_id": "review-node-1",
            "ordinal": 1,
            "disposition": "open",
            "evidence_reference": "synthetic-reference",
        }
    ]
    return document


def nested_value(document: object, path: tuple[object, ...]) -> object:
    value = document
    for part in path:
        value = value[part]
    return value


class ReviewEvidenceTests(unittest.TestCase):
    def test_complete_bundle_is_valid(self) -> None:
        self.assertEqual([], validate_evidence(complete_bundle(), "0" * 40))

    def test_missing_required_population_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        del document["populations"]["issue_comments"]

        self.assertTrue(any(issue.startswith("POPULATION_MISSING:") for issue in validate_evidence(document, "0" * 40)))

    def test_zero_count_without_terminal_page_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        document["populations"]["reviews"]["pages"] = []

        self.assertTrue(any(issue.startswith("PAGINATION_EMPTY:") for issue in validate_evidence(document, "0" * 40)))

    def test_final_page_with_next_page_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        document["populations"]["reviews"]["pages"][-1]["page_info"]["has_next_page"] = True

        self.assertTrue(
            any(issue.startswith("PAGINATION_INCOMPLETE:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_cursor_chain_gap_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        pages = document["populations"]["reviews"]["pages"]
        pages[0]["page_info"] = {"has_next_page": True, "end_cursor": "cursor-1"}
        pages.append(
            {
                "request_cursor": "wrong-cursor",
                "items": [],
                "page_info": {"has_next_page": False, "end_cursor": None},
            }
        )

        self.assertTrue(
            any(issue.startswith("PAGINATION_CURSOR_GAP:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_duplicate_ids_and_total_mismatch_fail_closed(self) -> None:
        document = deepcopy(complete_bundle())
        reviews = document["populations"]["reviews"]
        reviews["total_count"] = 3
        reviews["pages"][0]["items"] = [{"node_id": "review-1"}, {"node_id": "review-1"}]

        issues = validate_evidence(document, "0" * 40)
        self.assertTrue(any(issue.startswith("ITEM_ID_DUPLICATE:") for issue in issues))
        self.assertTrue(any(issue.startswith("COUNT_MISMATCH:") for issue in issues))

    def test_unknown_keys_and_missing_record_fields_fail_closed(self) -> None:
        with self.subTest("unknown key"):
            document = deepcopy(complete_bundle())
            document["populations"]["check_runs"]["pages"][0]["items"][0]["extra"] = True
            self.assertTrue(
                any(issue.startswith("EVIDENCE_KEY_UNKNOWN:") for issue in validate_evidence(document, "0" * 40))
            )
        with self.subTest("missing field"):
            document = deepcopy(complete_bundle())
            del document["populations"]["check_runs"]["pages"][0]["items"][0]["name"]
            self.assertTrue(
                any(issue.startswith("EVIDENCE_FIELD_MISSING:") for issue in validate_evidence(document, "0" * 40))
            )

    def test_invalid_pull_request_check_and_status_enums_fail_closed(self) -> None:
        with self.subTest("pull request"):
            document = deepcopy(complete_bundle())
            document["pull_request"]["mergeable"] = "NOT_A_STATE"
            self.assertTrue(any(issue.startswith("ENUM_INVALID:") for issue in validate_evidence(document, "0" * 40)))
        with self.subTest("check run"):
            document = deepcopy(complete_bundle())
            document["populations"]["check_runs"]["pages"][0]["items"][0]["status"] = "NOPE"
            self.assertTrue(any(issue.startswith("ENUM_INVALID:") for issue in validate_evidence(document, "0" * 40)))
        with self.subTest("commit status"):
            document = deepcopy(complete_bundle())
            document["populations"]["commit_statuses"]["pages"][0]["items"][0]["state"] = "NOPE"
            self.assertTrue(any(issue.startswith("ENUM_INVALID:") for issue in validate_evidence(document, "0" * 40)))

    def test_nested_zero_count_requires_terminal_empty_page(self) -> None:
        document = deepcopy(complete_bundle())
        comments = document["populations"]["review_threads"]["pages"][0]["items"][0]["comments"]
        comments["total_count"] = 0
        comments["pages"] = []

        self.assertTrue(any(issue.startswith("PAGINATION_EMPTY:") for issue in validate_evidence(document, "0" * 40)))

    def test_nested_final_page_with_next_page_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        document["populations"]["review_threads"]["pages"][0]["items"][0]["comments"]["pages"][-1]["page_info"][
            "has_next_page"
        ] = True

        self.assertTrue(
            any(issue.startswith("PAGINATION_INCOMPLETE:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_nested_cursor_chain_gap_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        pages = document["populations"]["review_threads"]["pages"][0]["items"][0]["comments"]["pages"]
        pages[0]["page_info"] = {"has_next_page": True, "end_cursor": "cursor-1"}
        pages.append(
            {
                "request_cursor": "wrong-cursor",
                "items": [],
                "page_info": {"has_next_page": False, "end_cursor": None},
            }
        )

        self.assertTrue(
            any(issue.startswith("PAGINATION_CURSOR_GAP:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_nested_duplicate_ids_and_total_mismatch_fail_closed(self) -> None:
        document = deepcopy(complete_bundle())
        comments = document["populations"]["review_threads"]["pages"][0]["items"][0]["comments"]
        comments["total_count"] = 3
        comments["pages"][0]["items"].append(deepcopy(comments["pages"][0]["items"][0]))

        issues = validate_evidence(document, "0" * 40)
        self.assertTrue(any(issue.startswith("ITEM_ID_DUPLICATE:") for issue in issues))
        self.assertTrue(any(issue.startswith("COUNT_MISMATCH:") for issue in issues))

    def test_every_content_source_is_audited_once(self) -> None:
        document = deepcopy(complete_bundle())
        reviews = document["populations"]["reviews"]
        reviews["total_count"] = 1
        reviews["pages"][0]["items"] = [{"node_id": "review-node-1", "body": "synthetic review"}]

        self.assertTrue(any(issue.startswith("SOURCE_UNAUDITED:") for issue in validate_evidence(document, "0" * 40)))

    def test_duplicate_source_audit_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        document["source_audit"].append(deepcopy(document["source_audit"][0]))

        self.assertTrue(
            any(issue.startswith("SOURCE_AUDIT_DUPLICATE:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_source_body_hash_must_match_audit(self) -> None:
        document = deepcopy(complete_bundle())
        document["source_audit"][0]["body_sha256"] = "c" * 64

        self.assertTrue(
            any(issue.startswith("SOURCE_HASH_MISMATCH:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_optional_body_hash_must_match_content(self) -> None:
        document = deepcopy(complete_bundle())
        comment = document["populations"]["review_threads"]["pages"][0]["items"][0]["comments"]["pages"][0]["items"][0]
        comment["body"] = "synthetic content"

        self.assertTrue(
            any(issue.startswith("SOURCE_BODY_HASH_MISMATCH:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_source_finding_counts_reconcile(self) -> None:
        document = deepcopy(complete_bundle())
        document["source_audit"][0]["finding_count"] = 2
        document["findings"] = [
            {
                "source_population": "review_thread_comments",
                "source_node_id": "review-comment-node-1",
                "ordinal": 1,
                "key": "finding-1",
                "disposition": "open",
                "evidence_reference": "synthetic-ref",
            }
        ]

        self.assertTrue(
            any(issue.startswith("FINDING_COUNT_MISMATCH:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_orphan_finding_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        document["findings"] = [
            {
                "source_population": "reviews",
                "source_node_id": "missing-review",
                "ordinal": 1,
                "key": "finding-1",
                "disposition": "open",
                "evidence_reference": "synthetic-ref",
            }
        ]

        self.assertTrue(
            any(issue.startswith("FINDING_SOURCE_UNKNOWN:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_duplicate_or_missing_finding_ordinal_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        document["source_audit"][0]["finding_count"] = 2
        document["findings"] = [
            {
                "source_population": "review_thread_comments",
                "source_node_id": "review-comment-node-1",
                "ordinal": 1,
                "key": "finding-1",
                "disposition": "open",
                "evidence_reference": "synthetic-ref-1",
            },
            {
                "source_population": "review_thread_comments",
                "source_node_id": "review-comment-node-1",
                "ordinal": 1,
                "key": "finding-2",
                "disposition": "open",
                "evidence_reference": "synthetic-ref-2",
            },
        ]

        self.assertTrue(
            any(issue.startswith("FINDING_ORDINAL_INVALID:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_duplicate_finding_key_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        document["source_audit"][0]["finding_count"] = 2
        document["findings"] = [
            {
                "source_population": "review_thread_comments",
                "source_node_id": "review-comment-node-1",
                "ordinal": 1,
                "key": "same-key",
                "disposition": "open",
                "evidence_reference": "synthetic-ref-1",
            },
            {
                "source_population": "review_thread_comments",
                "source_node_id": "review-comment-node-1",
                "ordinal": 2,
                "key": "same-key",
                "disposition": "open",
                "evidence_reference": "synthetic-ref-2",
            },
        ]

        self.assertTrue(
            any(issue.startswith("FINDING_KEY_DUPLICATE:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_finding_key_may_be_reused_by_distinct_audited_sources(self) -> None:
        document = full_domain_bundle()
        issue_audit = next(
            audit for audit in document["source_audit"] if audit["source_population"] == "issue_comments"
        )
        issue_audit["finding_count"] = 1
        document["findings"].append(
            {
                "source_population": "issue_comments",
                "source_node_id": "issue-comment-node-1",
                "ordinal": 1,
                "key": "finding-1",
                "disposition": "fixed",
                "evidence_reference": "synthetic-issue-reference",
            }
        )

        self.assertEqual([], validate_evidence(document, "0" * 40))

    def test_invalid_finding_disposition_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        document["source_audit"][0]["finding_count"] = 1
        document["findings"] = [
            {
                "source_population": "review_thread_comments",
                "source_node_id": "review-comment-node-1",
                "ordinal": 1,
                "key": "finding-1",
                "disposition": "unknown",
                "evidence_reference": "synthetic-ref",
            }
        ]

        self.assertTrue(
            any(issue.startswith("FINDING_DISPOSITION_INVALID:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_empty_finding_evidence_reference_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        document["source_audit"][0]["finding_count"] = 1
        document["findings"] = [
            {
                "source_population": "review_thread_comments",
                "source_node_id": "review-comment-node-1",
                "ordinal": 1,
                "key": "finding-1",
                "disposition": "open",
                "evidence_reference": "",
            }
        ]

        self.assertTrue(
            any(issue.startswith("FINDING_EVIDENCE_EMPTY:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_check_runs_and_commit_statuses_are_separate_required_populations(self) -> None:
        for name in ("check_runs", "commit_statuses"):
            with self.subTest(name=name):
                document = deepcopy(complete_bundle())
                del document["populations"][name]
                self.assertTrue(
                    any(
                        issue == f"POPULATION_MISSING: root.populations.{name}"
                        for issue in validate_evidence(document, "0" * 40)
                    )
                )

    def test_expected_observed_head_drift_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        document["observed_head_sha"] = "1" * 40

        self.assertTrue(any(issue.startswith("HEAD_DRIFT:") for issue in validate_evidence(document, "0" * 40)))

    def test_mutation_unknown_thread_id_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        document["mutations"][0]["operations"][0]["thread_node_id"] = "unknown-thread"

        self.assertTrue(
            any(issue.startswith("MUTATION_THREAD_UNKNOWN:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_mutation_local_expected_and_observed_heads_must_match(self) -> None:
        for field in ("expected_head_sha", "observed_head_before"):
            with self.subTest(field=field):
                document = deepcopy(complete_bundle())
                document["mutations"][0][field] = "1" * 40
                self.assertTrue(
                    any(issue.startswith("MUTATION_HEAD_DRIFT:") for issue in validate_evidence(document, "0" * 40))
                )

    def test_mutation_requires_exactly_reply_and_resolve_operations(self) -> None:
        for operations in (
            [deepcopy(complete_bundle()["mutations"][0]["operations"][0])],
            deepcopy(complete_bundle()["mutations"][0]["operations"]) + [{}],
        ):
            with self.subTest(count=len(operations)):
                document = deepcopy(complete_bundle())
                document["mutations"][0]["operations"] = operations
                self.assertTrue(
                    any(
                        issue.startswith("MUTATION_OPERATION_COUNT:") for issue in validate_evidence(document, "0" * 40)
                    )
                )

    def test_mutation_reply_uses_review_comment_identifier_domain(self) -> None:
        document = deepcopy(complete_bundle())
        created = document["mutations"][0]["operations"][0]["created_comment"]
        created["node_id"] = "thread-node-1"

        self.assertTrue(
            any(issue.startswith("MUTATION_COMMENT_ID_INVALID:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_mutation_reply_hash_mismatch_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        document["mutations"][0]["operations"][0]["readback"]["body_sha256"] = "c" * 64

        self.assertTrue(
            any(issue.startswith("MUTATION_REPLY_HASH_MISMATCH:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_mutation_resolve_before_reply_fails_closed(self) -> None:
        document = deepcopy(complete_bundle())
        operations = document["mutations"][0]["operations"]
        operations.reverse()

        self.assertTrue(
            any(issue.startswith("MUTATION_ORDER_INVALID:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_mutation_reply_response_and_readback_ids_must_match(self) -> None:
        for field, value in (("node_id", "reply-node-other"), ("database_id", 999)):
            with self.subTest(field=field):
                document = deepcopy(complete_bundle())
                document["mutations"][0]["operations"][0]["readback"][field] = value
                self.assertTrue(
                    any(
                        issue.startswith("MUTATION_REPLY_ID_MISMATCH:")
                        for issue in validate_evidence(document, "0" * 40)
                    )
                )

    def test_mutation_resolution_response_and_readback_thread_must_match(self) -> None:
        for field in ("response", "readback"):
            with self.subTest(field=field):
                document = deepcopy(complete_bundle())
                document["mutations"][0]["operations"][1][field]["thread_node_id"] = "other-thread"
                self.assertTrue(
                    any(
                        issue.startswith("MUTATION_RESOLUTION_ID_MISMATCH:")
                        for issue in validate_evidence(document, "0" * 40)
                    )
                )

    def test_mutation_missing_reply_or_resolution_readback_fails_closed(self) -> None:
        for index in (0, 1):
            with self.subTest(index=index):
                document = deepcopy(complete_bundle())
                del document["mutations"][0]["operations"][index]["readback"]
                self.assertTrue(
                    any(
                        issue.startswith("MUTATION_READBACK_INCOMPLETE:")
                        for issue in validate_evidence(document, "0" * 40)
                    )
                )

    def test_mutation_resolution_response_and_readback_must_be_true(self) -> None:
        for field in ("response", "readback"):
            with self.subTest(field=field):
                document = deepcopy(complete_bundle())
                document["mutations"][0]["operations"][1][field]["is_resolved"] = False
                self.assertTrue(
                    any(
                        issue.startswith("MUTATION_RESOLUTION_UNPROVEN:")
                        for issue in validate_evidence(document, "0" * 40)
                    )
                )

    def test_cli_malformed_json_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "evidence.json"
            path.write_text("{", encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = main([str(path), "--expected-head", "0" * 40])

        self.assertNotEqual(0, result)
        self.assertIn("EVIDENCE_JSON_INVALID", stderr.getvalue())

    def test_cli_partial_top_level_object_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "evidence.json"
            path.write_text('{"schema_version": 1}', encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = main([str(path), "--expected-head", "0" * 40])

        self.assertNotEqual(0, result)
        self.assertIn("EVIDENCE_FIELD_MISSING", stderr.getvalue())

    def test_cli_read_and_unicode_errors_fail_closed(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            for path, code in (
                (directory / "missing.json", "EVIDENCE_UNREADABLE"),
                (directory / "bad.json", "EVIDENCE_ENCODING_INVALID"),
            ):
                with self.subTest(code=code):
                    if code == "EVIDENCE_ENCODING_INVALID":
                        path.write_bytes(b"\xff")
                    stderr = StringIO()
                    with redirect_stderr(stderr):
                        result = main([str(path), "--expected-head", "0" * 40])
                    self.assertNotEqual(0, result)
                    self.assertIn(code, stderr.getvalue())

    def test_cli_never_prints_body_content(self) -> None:
        sentinel = "synthetic-secret-body"
        document = complete_bundle()
        comment = document["populations"]["review_threads"]["pages"][0]["items"][0]["comments"]["pages"][0]["items"][0]
        digest = sha256(sentinel.encode("utf-8")).hexdigest()
        comment["body"] = sentinel
        comment["body_sha256"] = digest
        document["source_audit"][0]["body_sha256"] = digest
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "evidence.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main([str(path), "--expected-head", "0" * 40])

        self.assertEqual(0, result)
        self.assertTrue(stdout.getvalue())
        self.assertNotIn(sentinel, stdout.getvalue())
        self.assertNotIn(sentinel, stderr.getvalue())

    def test_cli_success_prints_only_sanitized_summary(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "evidence.json"
            path.write_text(json.dumps(complete_bundle()), encoding="utf-8")
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = main([str(path), "--expected-head", "0" * 40])

        self.assertEqual(0, result)
        self.assertEqual(
            {
                "expected_head_sha",
                "observed_head_sha",
                "pull_request_number",
                "population_counts",
                "finding_count",
                "unresolved_finding_count",
                "review_in_flight",
                "mutation_proof_count",
            },
            set(json.loads(stdout.getvalue())),
        )

    def test_cli_requires_independent_expected_head(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "evidence.json"
            path.write_text(json.dumps(complete_bundle()), encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr):
                mismatch_result = main([str(path), "--expected-head", "1" * 40])
                missing_argument_result = main([])

        self.assertNotEqual(0, mismatch_result)
        self.assertIn("HEAD_EXPECTED_MISMATCH", stderr.getvalue())
        self.assertNotEqual(0, missing_argument_result)

    def test_malformed_nested_objects_fail_closed_without_leaking_values(self) -> None:
        for path, value in (("pull_request", []), ("source_audit", {}), ("mutations", {})):
            with self.subTest(path=path):
                document = deepcopy(complete_bundle())
                document[path] = value
                issues = validate_evidence(document, "0" * 40)
                self.assertTrue(any(issue.startswith("EVIDENCE_TYPE_INVALID:") for issue in issues))
                self.assertFalse(any("synthetic-secret" in issue for issue in issues))

    def test_every_collected_content_source_requires_an_audit(self) -> None:
        document = deepcopy(complete_bundle())
        document["source_audit"] = []

        self.assertTrue(any(issue.startswith("SOURCE_UNAUDITED:") for issue in validate_evidence(document, "0" * 40)))

    def test_checks_and_statuses_must_bind_to_expected_head(self) -> None:
        for population, field in (("check_runs", "head_sha"), ("commit_statuses", "commit_sha")):
            with self.subTest(population=population):
                document = deepcopy(complete_bundle())
                document["populations"][population]["pages"][0]["items"][0][field] = "1" * 40
                self.assertTrue(any(issue.startswith("HEAD_DRIFT:") for issue in validate_evidence(document, "0" * 40)))

    def test_mutation_reply_and_resolve_required_records_fail_closed(self) -> None:
        for index, field in ((0, "created_comment"), (1, "response")):
            with self.subTest(field=field):
                document = deepcopy(complete_bundle())
                del document["mutations"][0]["operations"][index][field]
                self.assertTrue(
                    any(issue.startswith("MUTATION_FIELD_MISSING:") for issue in validate_evidence(document, "0" * 40))
                )

    def test_pagination_proof_requires_first_and_intermediate_invariants(self) -> None:
        document = deepcopy(complete_bundle())
        pages = document["populations"]["reviews"]["pages"]
        pages[0]["request_cursor"] = "unexpected"
        self.assertTrue(
            any(issue.startswith("PAGINATION_CURSOR_INVALID:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_review_and_issue_comment_audit_coverage_is_body_independent(self) -> None:
        document = deepcopy(complete_bundle())
        for name, node_id in (("reviews", "review-node-1"), ("issue_comments", "issue-node-1")):
            document["populations"][name]["total_count"] = 1
            document["populations"][name]["pages"][0]["items"] = [{"node_id": node_id}]

        self.assertGreaterEqual(
            sum(issue.startswith("SOURCE_UNAUDITED:") for issue in validate_evidence(document, "0" * 40)),
            2,
        )

    def test_diagnostics_never_interpolate_untrusted_identifiers(self) -> None:
        document = deepcopy(complete_bundle())
        document["findings"] = [
            {
                "source_population": "synthetic-secret",
                "source_node_id": "synthetic-secret",
                "ordinal": 1,
                "key": "synthetic-secret",
                "disposition": "open",
                "evidence_reference": "synthetic-secret",
            }
        ]

        self.assertNotIn("synthetic-secret", "\n".join(validate_evidence(document, "0" * 40)))

    def test_nested_pagination_requires_null_first_cursor(self) -> None:
        document = deepcopy(complete_bundle())
        document["populations"]["review_threads"]["pages"][0]["items"][0]["comments"]["pages"][0]["request_cursor"] = (
            "x"
        )
        self.assertTrue(
            any(issue.startswith("PAGINATION_CURSOR_INVALID:") for issue in validate_evidence(document, "0" * 40))
        )

    def test_exact_key_sets_cover_every_schema_object(self) -> None:
        cases = (
            ("pull request", ("pull_request",), "number"),
            ("connection", ("populations", "reviews"), "total_count"),
            ("page", ("populations", "reviews", "pages", 0), "request_cursor"),
            ("page info", ("populations", "reviews", "pages", 0, "page_info"), "has_next_page"),
            ("review", ("populations", "reviews", "pages", 0, "items", 0), "submitted_commit_sha"),
            ("issue comment", ("populations", "issue_comments", "pages", 0, "items", 0), "database_id"),
            ("thread", ("populations", "review_threads", "pages", 0, "items", 0), "is_resolved"),
            (
                "nested connection",
                ("populations", "review_threads", "pages", 0, "items", 0, "comments"),
                "total_count",
            ),
            (
                "nested page",
                ("populations", "review_threads", "pages", 0, "items", 0, "comments", "pages", 0),
                "items",
            ),
            (
                "nested page info",
                (
                    "populations",
                    "review_threads",
                    "pages",
                    0,
                    "items",
                    0,
                    "comments",
                    "pages",
                    0,
                    "page_info",
                ),
                "end_cursor",
            ),
            (
                "review comment",
                (
                    "populations",
                    "review_threads",
                    "pages",
                    0,
                    "items",
                    0,
                    "comments",
                    "pages",
                    0,
                    "items",
                    0,
                ),
                "reply_to_node_id",
            ),
            ("check run", ("populations", "check_runs", "pages", 0, "items", 0), "conclusion"),
            ("commit status", ("populations", "commit_statuses", "pages", 0, "items", 0), "context"),
            ("audit", ("source_audit", 0), "finding_count"),
            ("finding", ("findings", 0), "evidence_reference"),
            ("mutation", ("mutations", 0), "observed_head_before"),
            ("reply", ("mutations", 0, "operations", 0), "created_comment"),
            ("created comment", ("mutations", 0, "operations", 0, "created_comment"), "database_id"),
            ("reply readback", ("mutations", 0, "operations", 0, "readback"), "body_sha256"),
            ("resolve", ("mutations", 0, "operations", 1), "response"),
            ("resolve response", ("mutations", 0, "operations", 1, "response"), "is_resolved"),
            ("resolve readback", ("mutations", 0, "operations", 1, "readback"), "is_resolved"),
        )
        for label, path, required_field in cases:
            with self.subTest(label=label, defect="missing"):
                document = full_domain_bundle()
                del nested_value(document, path)[required_field]
                self.assertTrue(
                    any(issue.startswith("EVIDENCE_FIELD_MISSING:") for issue in validate_evidence(document, "0" * 40))
                )
            with self.subTest(label=label, defect="unknown"):
                document = full_domain_bundle()
                nested_value(document, path)["synthetic-secret-extra"] = True
                issues = validate_evidence(document, "0" * 40)
                self.assertTrue(any(issue.startswith("EVIDENCE_KEY_UNKNOWN:") for issue in issues))
                self.assertNotIn("synthetic-secret-extra", "\n".join(issues))

    def test_field_types_formats_and_integer_constraints_cover_every_domain(self) -> None:
        cases = (
            ("schema version bool", ("schema_version",), True),
            ("expected head uppercase", ("expected_head_sha",), "A" * 40),
            ("observed head short", ("observed_head_sha",), "0" * 39),
            ("pr number bool", ("pull_request", "number"), True),
            ("pr number zero", ("pull_request", "number"), 0),
            ("review in flight", ("pull_request", "review_in_flight"), 0),
            ("connection total bool", ("populations", "reviews", "total_count"), True),
            ("connection total negative", ("populations", "reviews", "total_count"), -1),
            ("connection pages", ("populations", "reviews", "pages"), {}),
            ("page cursor", ("populations", "reviews", "pages", 0, "request_cursor"), 7),
            ("page items", ("populations", "reviews", "pages", 0, "items"), {}),
            ("page info", ("populations", "reviews", "pages", 0, "page_info"), []),
            ("has next", ("populations", "reviews", "pages", 0, "page_info", "has_next_page"), 0),
            ("end cursor", ("populations", "reviews", "pages", 0, "page_info", "end_cursor"), 7),
            ("review node", ("populations", "reviews", "pages", 0, "items", 0, "node_id"), ""),
            (
                "review submitted head",
                ("populations", "reviews", "pages", 0, "items", 0, "submitted_commit_sha"),
                "1" * 40,
            ),
            ("review hash", ("populations", "reviews", "pages", 0, "items", 0, "body_sha256"), "A" * 64),
            (
                "issue database id",
                ("populations", "issue_comments", "pages", 0, "items", 0, "database_id"),
                0,
            ),
            ("thread resolved", ("populations", "review_threads", "pages", 0, "items", 0, "is_resolved"), 0),
            (
                "reply-to id",
                (
                    "populations",
                    "review_threads",
                    "pages",
                    0,
                    "items",
                    0,
                    "comments",
                    "pages",
                    0,
                    "items",
                    0,
                    "reply_to_node_id",
                ),
                5,
            ),
            ("check name", ("populations", "check_runs", "pages", 0, "items", 0, "name"), 5),
            ("status context", ("populations", "commit_statuses", "pages", 0, "items", 0, "context"), 5),
            ("audit population", ("source_audit", 0, "source_population"), "not-a-population"),
            ("audit count bool", ("source_audit", 0, "finding_count"), True),
            ("audit count negative", ("source_audit", 0, "finding_count"), -1),
            ("finding key", ("findings", 0, "key"), ""),
            ("finding ordinal bool", ("findings", 0, "ordinal"), True),
            ("finding ordinal zero", ("findings", 0, "ordinal"), 0),
            ("evidence reference", ("findings", 0, "evidence_reference"), 5),
            ("mutation head", ("mutations", 0, "expected_head_sha"), "A" * 40),
            ("operations type", ("mutations", 0, "operations"), {}),
            ("reply sequence", ("mutations", 0, "operations", 0, "sequence"), True),
            ("reply thread", ("mutations", 0, "operations", 0, "thread_node_id"), ""),
            ("created node", ("mutations", 0, "operations", 0, "created_comment", "node_id"), ""),
            ("created database", ("mutations", 0, "operations", 0, "created_comment", "database_id"), 0),
            ("expected body hash", ("mutations", 0, "operations", 0, "expected_body_sha256"), "A" * 64),
            ("readback database", ("mutations", 0, "operations", 0, "readback", "database_id"), True),
            ("resolve sequence", ("mutations", 0, "operations", 1, "sequence"), 1),
            ("response resolved", ("mutations", 0, "operations", 1, "response", "is_resolved"), 1),
        )
        for label, path, value in cases:
            with self.subTest(label=label):
                document = full_domain_bundle()
                parent = nested_value(document, path[:-1])
                parent[path[-1]] = value
                self.assertNotEqual([], validate_evidence(document, "0" * 40))

    def test_all_enum_domains_and_check_conclusion_state_are_exact(self) -> None:
        valid_values = (
            (("pull_request", "mergeable"), ("MERGEABLE", "CONFLICTING", "UNKNOWN")),
            (("pull_request", "review_decision"), ("APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED", None)),
            (
                ("populations", "check_runs", "pages", 0, "items", 0, "status"),
                ("QUEUED", "IN_PROGRESS", "COMPLETED", "WAITING", "REQUESTED", "PENDING"),
            ),
            (
                ("populations", "commit_statuses", "pages", 0, "items", 0, "state"),
                ("EXPECTED", "ERROR", "FAILURE", "PENDING", "SUCCESS"),
            ),
            (("findings", 0, "disposition"), ("fixed", "rejected", "open")),
        )
        for path, values in valid_values:
            for value in values:
                with self.subTest(path=path, value=value):
                    document = full_domain_bundle()
                    nested_value(document, path[:-1])[path[-1]] = value
                    if path[-1] == "status":
                        document["populations"]["check_runs"]["pages"][0]["items"][0]["conclusion"] = (
                            "SUCCESS" if value == "COMPLETED" else None
                        )
                    self.assertFalse(
                        any(issue.startswith("ENUM_INVALID:") for issue in validate_evidence(document, "0" * 40))
                    )

        conclusions = (
            "SUCCESS",
            "FAILURE",
            "NEUTRAL",
            "CANCELLED",
            "SKIPPED",
            "TIMED_OUT",
            "ACTION_REQUIRED",
            "STALE",
            "STARTUP_FAILURE",
        )
        for conclusion in conclusions:
            with self.subTest(conclusion=conclusion):
                document = full_domain_bundle()
                document["populations"]["check_runs"]["pages"][0]["items"][0]["conclusion"] = conclusion
                self.assertEqual([], validate_evidence(document, "0" * 40))
        for status, conclusion in (("COMPLETED", None), ("PENDING", "SUCCESS"), ("COMPLETED", "NOPE")):
            with self.subTest(status=status, conclusion=conclusion):
                document = full_domain_bundle()
                item = document["populations"]["check_runs"]["pages"][0]["items"][0]
                item["status"], item["conclusion"] = status, conclusion
                self.assertTrue(
                    any(issue.startswith("ENUM_INVALID:") for issue in validate_evidence(document, "0" * 40))
                )

    def test_complete_pagination_proof_rejects_every_unproven_transition(self) -> None:
        def two_pages(document: dict[str, object], nested: bool = False) -> list[dict[str, object]]:
            if nested:
                connection = document["populations"]["review_threads"]["pages"][0]["items"][0]["comments"]
                connection["total_count"] = 1
                pages = connection["pages"]
            else:
                connection = document["populations"]["reviews"]
                connection["total_count"] = 1
                pages = connection["pages"]
                pages[0]["items"] = [full_domain_bundle()["populations"]["reviews"]["pages"][0]["items"][0]]
            pages[0]["page_info"] = {"has_next_page": True, "end_cursor": "cursor-1"}
            pages.append(
                {"request_cursor": "cursor-1", "items": [], "page_info": {"has_next_page": False, "end_cursor": None}}
            )
            return pages

        for nested in (False, True):
            for label, mutate in (
                ("intermediate says terminal", lambda pages: pages[0]["page_info"].update(has_next_page=False)),
                ("intermediate cursor null", lambda pages: pages[0]["page_info"].update(end_cursor=None)),
                ("final cursor nonnull", lambda pages: pages[-1]["page_info"].update(end_cursor="left-open")),
            ):
                with self.subTest(nested=nested, label=label):
                    document = full_domain_bundle()
                    pages = two_pages(document, nested)
                    mutate(pages)
                    self.assertTrue(
                        any(
                            issue.startswith("PAGINATION_INCOMPLETE:")
                            for issue in validate_evidence(document, "0" * 40)
                        )
                    )

    def test_mutation_proof_requires_exact_sequence_kinds_identities_and_shapes(self) -> None:
        cases = (
            (("mutations", 0, "operations", 0, "sequence"), 2, "MUTATION_ORDER_INVALID"),
            (("mutations", 0, "operations", 0, "kind"), "resolve", "MUTATION_ORDER_INVALID"),
            (("mutations", 0, "operations", 1, "sequence"), 1, "MUTATION_ORDER_INVALID"),
            (("mutations", 0, "operations", 1, "kind"), "reply", "MUTATION_ORDER_INVALID"),
            (("mutations", 0, "operations", 0, "readback", "node_id"), "other", "MUTATION_REPLY_ID_MISMATCH"),
            (
                ("mutations", 0, "operations", 1, "response", "thread_node_id"),
                "other",
                "MUTATION_RESOLUTION_ID_MISMATCH",
            ),
            (("mutations", 0, "operations", 1, "readback", "is_resolved"), False, "MUTATION_RESOLUTION_UNPROVEN"),
        )
        for path, value, code in cases:
            with self.subTest(path=path):
                document = full_domain_bundle()
                nested_value(document, path[:-1])[path[-1]] = value
                self.assertTrue(any(issue.startswith(f"{code}:") for issue in validate_evidence(document, "0" * 40)))

    def test_validate_evidence_never_raises_or_echoes_arbitrary_untrusted_input(self) -> None:
        sentinel = "synthetic-secret-value"
        cases = (
            None,
            7,
            sentinel,
            [],
            {},
            {sentinel: sentinel, 7: sentinel},
            {"schema_version": 1, "pull_request": {sentinel: sentinel}},
        )
        for document in cases:
            with self.subTest(document_type=type(document).__name__):
                issues = validate_evidence(document, sentinel)
                self.assertIsInstance(issues, list)
                self.assertTrue(issues)
                self.assertNotIn(sentinel, "\n".join(issues))

        document = full_domain_bundle()
        document["populations"]["check_runs"]["pages"][0]["items"][0]["name"] = sentinel
        document["populations"]["commit_statuses"]["pages"][0]["items"][0]["context"] = sentinel
        document["findings"][0]["key"] = sentinel
        document["findings"][0]["evidence_reference"] = sentinel
        document["source_audit"][0]["source_node_id"] = sentinel
        self.assertNotIn(sentinel, "\n".join(validate_evidence(document, "0" * 40)))

    def test_unhashable_enum_and_identifier_values_never_raise(self) -> None:
        paths = (
            ("pull_request", "mergeable"),
            ("pull_request", "review_decision"),
            ("populations", "check_runs", "pages", 0, "items", 0, "status"),
            ("populations", "check_runs", "pages", 0, "items", 0, "conclusion"),
            ("populations", "commit_statuses", "pages", 0, "items", 0, "state"),
            ("source_audit", 0, "source_population"),
            ("findings", 0, "disposition"),
            ("mutations", 0, "operations", 0, "thread_node_id"),
            ("mutations", 0, "operations", 0, "created_comment", "node_id"),
        )
        for path in paths:
            with self.subTest(path=path):
                document = full_domain_bundle()
                nested_value(document, path[:-1])[path[-1]] = []
                self.assertTrue(validate_evidence(document, "0" * 40))


if __name__ == "__main__":
    unittest.main()
