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

    def test_invalid_pull_request_check_and_status_enums_fail_closed(self) -> None:
        with self.subTest("pull request"):
            document = deepcopy(complete_bundle())
            document["pull_request"]["mergeable"] = "NOT_A_STATE"
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
                result = main([str(path)])

        self.assertNotEqual(0, result)
        self.assertIn("EVIDENCE_JSON_INVALID", stderr.getvalue())

    def test_cli_partial_top_level_object_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "evidence.json"
            path.write_text('{"schema_version": 1}', encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = main([str(path)])

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
                        result = main([str(path)])
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
                result = main([str(path)])

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
                result = main([str(path)])

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
        with self.subTest("check run"):
            document = deepcopy(complete_bundle())
            document["populations"]["check_runs"]["pages"][0]["items"][0]["status"] = "NOPE"
            self.assertTrue(any(issue.startswith("ENUM_INVALID:") for issue in validate_evidence(document, "0" * 40)))
        with self.subTest("commit status"):
            document = deepcopy(complete_bundle())
            document["populations"]["commit_statuses"]["pages"][0]["items"][0]["state"] = "NOPE"
            self.assertTrue(any(issue.startswith("ENUM_INVALID:") for issue in validate_evidence(document, "0" * 40)))
        with self.subTest("missing field"):
            document = deepcopy(complete_bundle())
            del document["populations"]["check_runs"]["pages"][0]["items"][0]["name"]
            self.assertTrue(
                any(issue.startswith("EVIDENCE_FIELD_MISSING:") for issue in validate_evidence(document, "0" * 40))
            )


if __name__ == "__main__":
    unittest.main()
