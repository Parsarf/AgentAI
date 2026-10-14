import json
import tempfile
import unittest
from pathlib import Path
from agentai_platform.routing import services as svc

MODEL = 'jev-1.13.0'


def reply(choice, p_choice=0.9, model=MODEL):
    rest = (1 - p_choice) / 2
    probs = {s: (p_choice if s == choice else rest) for s in svc.SERVICES}
    return json.dumps({'model': model, 'answers': {'service': {'type': 'choice', 'choice': choice, 'probabilities': probs, 'confidence': p_choice}}})


class Fake:
    """Stands in for JEV: records every request body and returns what it was told to."""
    def __init__(self, raw=None, exc=None): self.raw, self.exc, self.bodies = raw, exc, []
    def __call__(self, endpoint, body, credential, deadline):
        self.bodies.append((endpoint, body, credential, deadline))
        if self.exc: raise self.exc
        return self.raw


class ServiceChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name); (d / 'routing.json').write_text(json.dumps({'enabled': True})); (d / 'key').write_text('secret-key\n')
        self.paths = dict(config_path=str(d / 'routing.json'), key_path=str(d / 'key'))
        self.on = True

    def router(self, fake):
        return svc.ServiceRouter(**self.paths, switch_on=lambda: self.on, transport=fake)

    def test_jev_picks_the_browser_for_a_request_the_old_keyword_rules_missed(self):
        fake = Fake(reply('browser')); plan = self.router(fake).choose('search for the spiciest food around me')
        self.assertEqual((plan.service, plan.source), ('browser', 'jev')); self.assertGreaterEqual(plan.confidence, 0.9)
        self.assertIn('JEV', plan.note); self.assertIn('browser', plan.note)
        self.assertEqual(len(fake.bodies), 1)

    def test_jev_picks_web_or_direct_when_the_browser_is_not_needed(self):
        self.assertEqual(self.router(Fake(reply('web'))).choose('what is the latest news on python').service, 'web')
        self.assertEqual(self.router(Fake(reply('direct'))).choose('find the bug in this function for me').service, 'direct')

    def test_messages_that_cannot_need_the_web_never_reach_jev(self):
        fake = Fake(reply('browser'))
        for text in ('write me a python function that reverses a list', 'thanks!', 'explain recursion simply', 'what is 12 times 9'):
            self.assertEqual(self.router(fake).choose(text).service, 'direct')
        self.assertEqual(fake.bodies, [])                                      # no call, no data sent, no delay

    def test_a_short_follow_up_to_a_web_request_is_checked_with_the_previous_message(self):
        fake = Fake(reply('browser')); r = self.router(fake)
        self.assertEqual(r.choose('try again', 'search for the spiciest food around me').service, 'browser')
        self.assertIn('Previous user message', fake.bodies[0][1]['state'])
        self.assertEqual(self.router(Fake(reply('browser'))).choose('try again', 'write a poem').service, 'direct')   # nothing live was asked before

    def test_what_jev_sees_is_scrubbed_and_truncated(self):
        fake = Fake(reply('web')); text = 'find cheap flights, my email is jane.doe@example.com and card 4111111111111111 ' + 'x' * 5000
        self.router(fake).choose(text, 'earlier ' + 'y' * 2000 + ' me@mail.com')
        sent = json.dumps(fake.bodies[0][1])
        self.assertNotIn('jane.doe@example.com', sent); self.assertNotIn('4111111111111111', sent); self.assertNotIn('me@mail.com', sent)
        self.assertLess(len(fake.bodies[0][1]['state']), svc.REQUEST_CHARS + svc.PREVIOUS_CHARS + 200)
        self.assertEqual(fake.bodies[0][2], 'secret-key')                       # the key is used, never put in the body
        self.assertNotIn('secret-key', sent)

    def test_failures_fall_back_to_the_deterministic_rules_and_never_raise(self):
        order = 'order the spiciest food around me from any cuisine'
        for fake in (Fake(exc=TimeoutError()), Fake(raw='not json'), Fake(raw=reply('browser', model='other-model')), Fake(raw=json.dumps({'model': MODEL, 'answers': {}})),
                     Fake(raw=reply('browser', p_choice=0.4))):                  # unsure counts as unusable
            plan = self.router(fake).choose(order)
            self.assertEqual((plan.service, plan.source), ('browser', 'rules'))   # the old rules still catch this one
        self.assertEqual(self.router(Fake(exc=OSError())).choose('what is the latest news today').service, 'web')

    def test_the_browser_is_only_chosen_when_it_can_run(self):
        self.assertEqual(self.router(Fake(reply('browser'))).choose('open doordash and find tacos', browser_ok=False).service, 'web')

    def test_switch_off_missing_key_or_disabled_routing_means_direct_or_rules_with_no_call(self):
        fake = Fake(reply('browser')); self.on = False
        self.assertEqual(self.router(fake).choose('order pizza from dominos.com').service, 'direct')
        self.on = True; Path(self.paths['key_path']).unlink()
        self.assertEqual(self.router(fake).choose('order pizza from dominos.com').source, 'rules')
        Path(self.paths['config_path']).write_text(json.dumps({'enabled': False}))
        self.assertEqual(self.router(fake).choose('order pizza from dominos.com').source, 'rules')
        self.assertEqual(fake.bodies, [])

    def test_the_deadline_is_generous_but_bounded(self):
        fake = Fake(reply('web')); self.router(fake).choose('latest news')
        self.assertEqual(fake.bodies[0][3], max(svc.DEADLINE_S, 5)); self.assertGreaterEqual(fake.bodies[0][3], 8)


if __name__ == '__main__':
    unittest.main()
