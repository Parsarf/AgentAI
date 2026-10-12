import unittest
from agentai_platform.lifecycle.netpolicy import NetPolicy, parse_counters

class NetPolicyChecks(unittest.TestCase):
    def policy(self, **kw):
        base=dict(cell_pool='10.78.0.0/16',bridge_gateway='10.77.0.1')
        base.update(kw);return NetPolicy(**base)
    def test_default_drops_host_services_and_private_ranges(self):
        text=self.policy().ruleset()
        self.assertIn('cell to host services',text)
        self.assertIn('cell to private/metadata',text)
        self.assertIn('169.254.0.0/16',text)      # cloud metadata
        self.assertNotIn('dport',text)            # no host port is opened by default
        self.assertNotIn('accept',text.replace('policy accept',''))          # only drops/returns: never widens Docker rules
    def test_model_proxy_is_the_only_host_exception(self):
        text=self.policy(model_proxy_port=4000).ruleset()
        self.assertIn('ip daddr 10.77.0.1 tcp dport 4000 return',text)
        self.assertEqual(text.count('dport'),1)
    def test_quarantine_drops_all_egress_for_listed_cells_only(self):
        text=self.policy(quarantined=('10.78.5.0/24',)).ruleset()
        self.assertIn('ip saddr @quarantined counter drop',text)
        self.assertIn('10.78.5.0/24',text)
        self.assertNotIn('quarantined',self.policy().ruleset())
    def test_invalid_inputs_fail_closed(self):
        for kw in [dict(cell_pool='8.8.0.0/16'),dict(cell_pool='10.0.0.0/4'),dict(bridge_gateway='8.8.8.8'),
                   dict(model_proxy_port=0),dict(model_proxy_port=True),dict(model_proxy_port=70000),
                   dict(quarantined=('192.168.1.0/24',)),dict(quarantined=('not-a-net',))]:
            with self.assertRaises(ValueError,msg=str(kw)):
                self.policy(**kw)
    def test_reload_form_is_one_atomic_replace(self):
        text=self.policy().ruleset()
        self.assertTrue(text.startswith('table inet agentai_cells\ndelete table inet agentai_cells\n'))
        self.assertFalse(self.policy().ruleset(atomic=False).startswith('table inet agentai_cells\ndelete'))
    def test_counters_parse(self):
        listing='counter packets 3 bytes 180 drop comment "cell to host services"\n'
        self.assertEqual(parse_counters(listing),{'cell to host services':(3,180)})

if __name__=='__main__': unittest.main()
