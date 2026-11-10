import unittest
from agentai_platform.chat_driver import failure_message, MODEL_FAILURE, SELECTION_FAILURE


class FailureMessageChecks(unittest.TestCase):
    def test_model_unavailable_runtime_text_tells_the_customer_what_to_do(self):
        text = '⚠️ The configured model is unavailable from the provider — it may have been renamed, retired, or is not offered on this account.'
        self.assertEqual(failure_message(text), MODEL_FAILURE)
        self.assertIn('Settings', MODEL_FAILURE)

    def test_relay_codes_map_to_fixed_sentences(self):
        self.assertEqual(failure_message('409 model_unavailable'), MODEL_FAILURE)
        self.assertEqual(failure_message('403 admission_mismatch'), SELECTION_FAILURE)

    def test_timeout_and_unknown_keep_the_old_wording(self):
        self.assertIn('too long', failure_message('request timeout'))
        self.assertIn('could not finish', failure_message(None))
        self.assertIn('could not finish', failure_message('something else broke'))

    def test_runtime_text_is_never_echoed(self):
        for raw in ('model is unavailable api.z.ai 10.77.0.1', 'weird sk-secret host.internal'):
            self.assertNotIn('api.z.ai', failure_message(raw))
            self.assertNotIn('10.77', failure_message(raw))
            self.assertNotIn('sk-', failure_message(raw))


if __name__ == '__main__':
    unittest.main()
