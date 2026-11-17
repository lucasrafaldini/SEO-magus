"""
Pluggable link classifiers: configuration, factory, HTTP providers (exercised
against fake provider servers on localhost), plugins, fallback and the
optimizer integration.
"""

import json
import threading
import unittest
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import pytest

from src.benchmarks import mock_sites
from src.config import SiteConfig, load_site_config
from src.engines.classifiers import (
    ClassifierConfig, ClassifierError, FallbackClassifier, HeuristicClassifier, LinkCandidate, LinkJudgement,
    build_classifier,
)
from src.engines.classifiers.jev import JevClassifier
from src.engines.classifiers.llm import AnthropicClassifier, OpenAICompatibleClassifier, parse_judgement
from src.workflows.linking_optimizer import LinkingOptimizer

CANDIDATE = LinkCandidate(
    source_url="https://x.example/a", source_paragraph="Read the complete composting guide first.",
    target_url="https://x.example/guide", target_title="Complete Composting Guide",
    target_topic="Complete Composting Guide", target_queries=("composting guide",),
)


class FakeProvider:
    """Tiny HTTP server standing in for an LLM / Jev API. `reply(path, body)` -> (status, json)."""

    def __init__(self, reply):
        outer = self
        self.requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "body": body,
                                       "headers": {k.lower(): v for k, v in self.headers.items()}})
                status, payload = reply(self.path, body)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def openai_reply(content):
    return lambda path, body: (200, {"choices": [{"message": {"role": "assistant", "content": content}}]})


@pytest.mark.integration
class ProviderTestCase(unittest.TestCase):
    def provider(self, reply) -> FakeProvider:
        fake = FakeProvider(reply)
        self.addCleanup(fake.close)
        return fake


class TestJudgementParsing(unittest.TestCase):
    def test_values_are_clamped(self):
        self.assertEqual(LinkJudgement(True, 1.7, 14), LinkJudgement(True, 1.0, 10.0))
        self.assertEqual(LinkJudgement(False, -1, 0).score, 1.0)

    def test_json_in_prose_or_code_fences(self):
        for text in ('{"relevant": true, "confidence": 0.9, "score": 8}',
                     'Sure!\n```json\n{"relevant": "yes", "confidence": "0.9", "score": 8}\n```',
                     'Thinking {not json} then {"relevant": true, "confidence": 0.9, "score": 8}'):
            with self.subTest(text=text):
                self.assertEqual(parse_judgement(text, "p"), LinkJudgement(True, 0.9, 8.0, "p"))

    def test_unusable_answers_raise(self):
        for text in ("I think so.", '{"relevant": true}', '{"relevant": true, "confidence": "high", "score": 8}'):
            with self.subTest(text=text), self.assertRaises(ClassifierError):
                parse_judgement(text, "p")


class TestConfiguration(unittest.TestCase):
    def test_defaults_and_strictness(self):
        self.assertEqual(ClassifierConfig.from_config({}), ClassifierConfig())
        self.assertEqual(ClassifierConfig().provider, "auto")
        self.assertEqual(ClassifierConfig.from_config({"classifier": {"provider": "Ollama"}}).provider, "ollama")
        for bad in ({"classifier": {"provider": "skynet"}}, {"classifier": {"fallback": "retry"}},
                    {"classifier": {"model_name": "x"}}, {"classifier": {"timeout": 0}}, {"classifier": ["openai"]}):
            with self.subTest(config=bad), self.assertRaises(ValueError):
                ClassifierConfig.from_config(bad)

    def test_api_keys_are_never_read_from_config(self):
        with self.assertRaisesRegex(ValueError, "Do not put API keys in config files; set classifier.api_key_env"):
            ClassifierConfig.from_config({"classifier": {"provider": "openai", "api_key": "placeholder-value"}})

    def test_site_configs_choose_their_classifier(self):
        self.assertEqual(load_site_config("config/sites/greenleaf.yaml").classifier.provider, "heuristic")
        self.assertEqual(SiteConfig().classifier, ClassifierConfig())


class TestFactory(unittest.TestCase):
    def build(self, environ=None, **config):
        with warnings.catch_warnings(), self.assertNoLogs("seo_magus.engines.classifiers.factory", "ERROR"):
            return build_classifier(ClassifierConfig(**config), environ=environ or {})

    def test_auto_uses_jev_only_when_its_key_is_set(self):
        # Zero-config: the offline heuristic, silently (no "unusable provider" warning).
        with self.assertNoLogs("seo_magus", "WARNING"):
            self.assertIsInstance(build_classifier(ClassifierConfig(), environ={}), HeuristicClassifier)
        classifier = self.build({"TYPESAFE_API_KEY": "k"})
        self.assertIsInstance(classifier, FallbackClassifier)
        self.assertIsInstance(classifier.primary, JevClassifier)
        self.assertEqual(classifier.cost_per_call_usd, 0.000025)

    def test_paid_provider_without_key_falls_back_or_fails(self):
        with self.assertLogs("seo_magus.engines.classifiers.factory", "WARNING") as logs:
            self.assertIsInstance(build_classifier(ClassifierConfig(provider="openai", model="m"), environ={}), HeuristicClassifier)
        self.assertIn("OPENAI_API_KEY is not set", logs.output[0])
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            build_classifier(ClassifierConfig(provider="openai", model="m", fallback="none"), environ={})

    def test_presets(self):
        cases = {
            "openai": (OpenAICompatibleClassifier, "https://api.openai.com/v1", {"OPENAI_API_KEY": "k"}),
            "gemini": (OpenAICompatibleClassifier, "https://generativelanguage.googleapis.com/v1beta/openai", {"GEMINI_API_KEY": "k"}),
            "groq": (OpenAICompatibleClassifier, "https://api.groq.com/openai/v1", {"GROQ_API_KEY": "k"}),
            "openrouter": (OpenAICompatibleClassifier, "https://openrouter.ai/api/v1", {"OPENROUTER_API_KEY": "k"}),
            "anthropic": (AnthropicClassifier, "https://api.anthropic.com/v1", {"ANTHROPIC_API_KEY": "k"}),
            "ollama": (OpenAICompatibleClassifier, "http://localhost:11434/v1", {}),
            "lmstudio": (OpenAICompatibleClassifier, "http://localhost:1234/v1", {}),
        }
        for provider, (cls, base_url, env) in cases.items():
            with self.subTest(provider=provider):
                classifier = self.build(env, provider=provider, model="some-model")
                self.assertIsInstance(classifier.primary, cls)
                self.assertEqual(classifier.primary.base_url, base_url)
        self.assertEqual(self.build(provider="ollama").primary.model, "llama3.2:3b")  # local default model

    def test_model_is_required_and_overrides_apply(self):
        with self.assertRaisesRegex(ValueError, "model"):
            build_classifier(ClassifierConfig(provider="openai"), environ={"OPENAI_API_KEY": "k"})
        classifier = self.build({"MY_KEY": "k"}, provider="openai_compatible", model="m", base_url="http://gpu:8000/v1/",
                                api_key_env="MY_KEY", cost_per_call_usd=0.001, fallback="none")
        self.assertIsInstance(classifier, OpenAICompatibleClassifier)
        self.assertEqual((classifier.base_url, classifier.api_key, classifier.cost_per_call_usd),
                         ("http://gpu:8000/v1", "k", 0.001))

    def test_plugins(self):
        plugin = self.build(provider="python:tests.classifier_plugin:KeywordClassifier", fallback="none")
        self.assertEqual(plugin.evaluate(CANDIDATE), LinkJudgement(True, 0.95, 9.0, "KeywordClassifier"))
        for spec in ("python:tests.classifier_plugin:NoEvaluate", "python:tests.classifier_plugin:Missing",
                     "python:no_such_module:X", "python:tests.classifier_plugin"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                build_classifier(ClassifierConfig(provider=spec), environ={})
        exploding = build_classifier(ClassifierConfig(provider="python:tests.classifier_plugin:Exploding"), environ={})
        with self.assertLogs("seo_magus.engines.classifiers.factory", "WARNING"):
            self.assertEqual(exploding.evaluate(CANDIDATE).provider, "heuristic (fallback)")

    def test_plugin_results_are_validated(self):
        plugin = lambda name: self.build(provider=f"python:tests.classifier_plugin:{name}", fallback="none")
        self.assertEqual(plugin("JudgementClassifier").evaluate(CANDIDATE),
                         LinkJudgement(True, 0.9, 8.0, "JudgementClassifier"))
        with self.assertRaisesRegex(ClassifierError, "quota exceeded"):
            plugin("Refusing").evaluate(CANDIDATE)
        with self.assertRaisesRegex(ClassifierError, "returned {'relevant': True, 'score': 8}"):
            plugin("IncompleteDict").evaluate(CANDIDATE)
        with self.assertRaisesRegex(ClassifierError, "returned str, expected LinkJudgement or dict"):
            plugin("WrongType").evaluate(CANDIDATE)

    def test_fallback_warnings_are_rate_limited(self):
        classifier = build_classifier(ClassifierConfig(provider="python:tests.classifier_plugin:Refusing"), environ={})
        with self.assertLogs("seo_magus.engines.classifiers.factory", "DEBUG") as logs:
            for _ in range(FallbackClassifier.WARN_FIRST + 2):
                self.assertEqual(classifier.evaluate(CANDIDATE).provider, "heuristic (fallback)")
        levels = [line.split(":", 1)[0] for line in logs.output]
        self.assertEqual(levels, ["WARNING"] * FallbackClassifier.WARN_FIRST + ["DEBUG"] * 2)
        self.assertIn("further failures logged at DEBUG", logs.output[FallbackClassifier.WARN_FIRST - 1])
        self.assertEqual(classifier.fallbacks, FallbackClassifier.WARN_FIRST + 2)
        self.assertIn("falling back to heuristic on errors", classifier.describe())


class TestProviderValidation(unittest.TestCase):
    """Provider objects check their settings and answers without any HTTP."""

    def test_llm_providers_need_a_base_url_and_a_model(self):
        with self.assertRaisesRegex(ValueError, "needs a base_url"):
            OpenAICompatibleClassifier("openai", "", "m")
        with self.assertRaisesRegex(ValueError, "needs a model name"):
            AnthropicClassifier("anthropic", "https://api.example/v1", "")

    def test_malformed_anthropic_answer_is_a_classifier_error(self):
        classifier = AnthropicClassifier("anthropic", "https://api.example/v1", "claude-model")
        with mock.patch("src.engines.classifiers.llm.post_json", return_value={"content": "not a list of blocks"}) as post, \
                self.assertRaisesRegex(ClassifierError, "unexpected response shape"):
            classifier.evaluate(CANDIDATE)
        headers = post.call_args.args[2]
        self.assertNotIn("x-api-key", headers)  # no key configured: the header is omitted

    def test_unexpected_jev_response_is_a_classifier_error(self):
        client = mock.Mock(mock_mode=False, base_url="https://jev.example")
        client.evaluate_link_candidate.return_value = {"results": {"relevance_score": {"score": 8}}}
        classifier = JevClassifier(client=client)
        with self.assertRaisesRegex(ClassifierError, "unexpected Jev response"):
            classifier.evaluate(CANDIDATE)
        self.assertEqual(classifier.describe(), "jev (https://jev.example)")
        self.assertEqual(JevClassifier(base_url="https://jev.example/v1").client.base_url, "https://jev.example/v1")


class TestHttpProviders(ProviderTestCase):
    def test_openai_compatible_request_and_answer(self):
        fake = self.provider(openai_reply('{"relevant": true, "confidence": 0.91, "score": 8}'))
        classifier = OpenAICompatibleClassifier("ollama", fake.url + "/v1", "llama3.2:3b", api_key="placeholder")
        self.assertEqual(classifier.evaluate(CANDIDATE), LinkJudgement(True, 0.91, 8.0, "ollama"))
        (request,) = fake.requests
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["headers"]["authorization"], "Bearer placeholder")
        body = request["body"]
        self.assertEqual((body["model"], body["temperature"]), ("llama3.2:3b", 0.0))
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertIn(CANDIDATE.source_paragraph, body["messages"][1]["content"])
        self.assertIn("composting guide", body["messages"][1]["content"])  # page 2 query is passed on

    def test_local_servers_need_no_key(self):
        fake = self.provider(openai_reply('{"relevant": false, "confidence": 0.8, "score": 2}'))
        classifier = OpenAICompatibleClassifier("lmstudio", fake.url + "/v1", "qwen")
        self.assertFalse(classifier.evaluate(CANDIDATE).relevant)
        self.assertNotIn("authorization", fake.requests[0]["headers"])

    def test_anthropic_messages_api(self):
        fake = self.provider(lambda path, body: (200, {"content": [
            {"type": "text", "text": '{"relevant": true, "confidence": 0.88, "score": 9}'}]}))
        classifier = AnthropicClassifier("anthropic", fake.url + "/v1", "claude-model", api_key="ant-key")
        self.assertEqual(classifier.evaluate(CANDIDATE), LinkJudgement(True, 0.88, 9.0, "anthropic"))
        request = fake.requests[0]
        self.assertEqual(request["path"], "/v1/messages")
        self.assertEqual((request["headers"]["x-api-key"], request["headers"]["anthropic-version"]), ("ant-key", "2023-06-01"))
        self.assertIn("SEO internal-linking judge", request["body"]["system"])

    def test_jev_api(self):
        fake = self.provider(lambda path, body: (200, {"results": {
            "has_legitimate_contextual_reason": {"value": True, "confidence": 0.93},
            "relevance_score": {"score": 8.5}}}))
        classifier = JevClassifier(api_key="jev-key", base_url=fake.url + "/v1/systemone")
        self.assertEqual(classifier.evaluate(CANDIDATE), LinkJudgement(True, 0.93, 8.5, "jev"))
        self.assertEqual(fake.requests[0]["headers"]["authorization"], "Bearer jev-key")
        self.assertEqual(fake.requests[0]["body"]["state"]["target_queries"], ["composting guide"])

    def test_errors_raise_classifier_error(self):
        cases = {
            "http 500": lambda path, body: (500, {"error": "overloaded"}),
            "bad shape": lambda path, body: (200, {"unexpected": True}),
            "no verdict": openai_reply("I would link it."),
        }
        for name, reply in cases.items():
            fake = self.provider(reply)
            with self.subTest(case=name), self.assertRaises(ClassifierError):
                OpenAICompatibleClassifier("openai", fake.url + "/v1", "m").evaluate(CANDIDATE)
        with self.assertRaises(ClassifierError):  # nothing listening
            OpenAICompatibleClassifier("openai", "http://127.0.0.1:9/v1", "m", timeout=1).evaluate(CANDIDATE)
        with self.assertRaises(ClassifierError):
            JevClassifier(api_key="k", base_url="http://127.0.0.1:9/v1/systemone", timeout=1).evaluate(CANDIDATE)

    def test_fallback_answers_and_counts(self):
        fake = self.provider(lambda path, body: (503, {"error": "down"}))
        classifier = FallbackClassifier(OpenAICompatibleClassifier("openai", fake.url + "/v1", "m"), HeuristicClassifier())
        with self.assertLogs("seo_magus.engines.classifiers.factory", "WARNING"):
            judgement = classifier.evaluate(CANDIDATE)
        self.assertEqual(judgement.provider, "heuristic (fallback)")
        self.assertEqual(classifier.fallbacks, 1)


class TestOptimizerIntegration(ProviderTestCase):
    """The whole flow on the scrambled mock site with an LLM provider instead of Jev."""

    @classmethod
    def setUpClass(cls):
        cls.pages = mock_sites.crawl_mock_site(mock_sites.SCRAMBLED_SITE).result.pages

    def _run(self, classifier_config, environ):
        site = load_site_config("config/sites/greenleaf.yaml")
        config = SiteConfig(site.thresholds, site.taxonomy, site.link_rules, classifier_config)
        optimizer = LinkingOptimizer.from_config(config, classifier=build_classifier(classifier_config, environ=environ))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return optimizer.run_optimization(self.pages)

    def test_llm_provider_drives_the_decisions(self):
        def judge(path, body):  # a "model" that approves when the exact target title is mentioned
            prompt = body["messages"][1]["content"]
            paragraph = prompt.split("Source paragraph:\n", 1)[1].split("\n\n", 1)[0].lower()
            title = prompt.split("Target page title: ", 1)[1].split("\n", 1)[0].lower()
            verdict = title in paragraph
            return 200, {"choices": [{"message": {"content": json.dumps(
                {"relevant": verdict, "confidence": 0.95 if verdict else 0.2, "score": 9 if verdict else 2})}}]}

        fake = self.provider(judge)
        report = self._run(ClassifierConfig(provider="openai_compatible", base_url=fake.url + "/v1", model="judge",
                                            cost_per_call_usd=0.001), {})
        self.assertTrue(report.results)
        self.assertTrue(all(r.classifier == "openai_compatible" for r in report.results))
        self.assertTrue(all(r.original_sentence.lower().count(r.anchor_text.lower()) for r in report.results))
        self.assertEqual(len(fake.requests), report.candidate_pairs_checked)
        self.assertEqual(report.classifier_fallbacks, 0)
        self.assertAlmostEqual(report.estimated_cost_usd, round(0.001 * report.candidate_pairs_checked, 4))
        self.assertIn("openai_compatible (judge @", report.classifier)

    def test_provider_outage_falls_back_to_the_heuristic_result(self):
        fake = self.provider(lambda path, body: (500, {"error": "down"}))
        with self.assertLogs("seo_magus", "WARNING"):
            report = self._run(ClassifierConfig(provider="openai_compatible", base_url=fake.url + "/v1", model="m"), {})
        heuristic = self._run(ClassifierConfig(provider="heuristic"), {})
        self.assertEqual(report.classifier_fallbacks, report.candidate_pairs_checked)
        self.assertEqual([(r.source_url, r.target_url, r.anchor_text) for r in report.results],
                         [(r.source_url, r.target_url, r.anchor_text) for r in heuristic.results])
        self.assertTrue(all(r.classifier == "heuristic (fallback)" for r in report.results))


if __name__ == "__main__":
    unittest.main()
