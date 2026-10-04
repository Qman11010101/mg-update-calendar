import json
import unittest

from mg_update_calendar.extractor import extract_article
from mg_update_calendar.llm import LLMError
from mg_update_calendar.models import Article
from test_extractor import ARTICLE, entry, wire_extraction


class Generator:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.requests = []

    def generate_json(self, request):
        self.requests.append(request)
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return output


def payload(entries):
    return json.dumps(wire_extraction({"entries": entries, "cancellations": [], "review_notes": []}))


class RecoveryTests(unittest.TestCase):
    def test_invalid_date_retries_with_field_feedback_and_recovers(self):
        client = Generator([payload([entry(start="2026-02-30")]), payload([entry()])])
        result = extract_article(client, Article.model_validate(ARTICLE), 8192)
        self.assertEqual(result["status"], "extracted")
        self.assertEqual(result["attempts"], 2)
        detail = result["validation_errors"][0]["errors"][0]
        self.assertEqual(detail["loc"], ["entries", 0, "start"])
        self.assertNotIn("input", detail)
        retry = json.loads(client.requests[1].input)
        self.assertEqual(retry["article"], ARTICLE)
        self.assertEqual(retry["validation_errors"], result["validation_errors"][0]["errors"])
        self.assertEqual(client.requests[0].schema, client.requests[1].schema)

    def test_malformed_json_and_missing_fields_can_recover(self):
        for invalid in ['not json', '{"entries":[]}']:
            with self.subTest(invalid=invalid):
                result = extract_article(Generator([invalid, payload([])]), Article.model_validate(ARTICLE), 8192)
                self.assertEqual(result["status"], "extracted")
                self.assertEqual(result["attempts"], 2)

    def test_persistent_failure_is_bounded_and_does_not_save_values(self):
        invalid = entry(start="secret-date", **{"secret-key": "secret-value"})
        client = Generator([payload([invalid])] * 3)
        result = extract_article(client, Article.model_validate(ARTICLE), 8192)
        self.assertEqual(result["error"], "invalid_structured_output")
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(result["entries"], [])
        saved = json.dumps(result)
        for secret in ["secret-date", "secret-key", "secret-value"]:
            self.assertNotIn(secret, saved)

    def test_wrong_game_type_is_retried_and_validated(self):
        result = extract_article(Generator([payload([entry(type="utage_add")]), payload([])]),
                                 Article.model_validate(ARTICLE), 8192)
        self.assertEqual(result["status"], "extracted")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["validation_errors"][0]["errors"][0]["type"], "invalid_game_entry_type")

    def test_refusals_and_transport_errors_are_not_structure_retries(self):
        for code in ["refusal", "AuthenticationError", "response_incomplete"]:
            client = Generator([LLMError(code)])
            result = extract_article(client, Article.model_validate(ARTICLE), 8192)
            self.assertEqual(result["error"], code)
            self.assertEqual(result["attempts"], 1)
            self.assertEqual(len(client.requests), 1)


if __name__ == "__main__":
    unittest.main()
