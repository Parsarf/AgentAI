import os
from pathlib import Path
import stat
import tempfile
import unittest
from agentai_platform.lifecycle.secrets_custody import SecretStore, ProviderKeys, CustodyError

A='aa-'+'a1'*16;B='aa-'+'b2'*16

class CustodyChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'sec'
        self.store=SecretStore(self.root)
    def tearDown(self): self.tmp.cleanup()
    def test_token_is_stable_private_and_per_tenant(self):
        t=self.store.gateway_token(A)
        self.assertEqual(t,self.store.gateway_token(A));self.assertNotEqual(t,self.store.gateway_token(B))
        self.assertEqual(stat.S_IMODE((self.root/A/'gateway-token').stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE((self.root/A).stat().st_mode),0o700)
    def test_group_readable_custody_is_rejected(self):
        self.store.gateway_token(A);os.chmod(self.root/A/'gateway-token',0o640)
        with self.assertRaises(CustodyError): self.store.gateway_token(A)
    def test_symlinked_secret_is_rejected(self):
        self.store.gateway_token(A);(self.root/A/'gateway-token').unlink()
        (Path(self.tmp.name)/'x').write_text('x'*40+'\n');(self.root/A/'gateway-token').symlink_to(Path(self.tmp.name)/'x')
        with self.assertRaises((CustodyError,OSError)): self.store.gateway_token(A)
    def test_invalid_tenant_never_touches_the_filesystem(self):
        for bad in ['../etc','aa-short','',None,'aa-'+'g'*32]:
            with self.assertRaises(CustodyError): self.store.gateway_token(bad)
    def test_destroy_removes_only_that_tenant(self):
        self.store.gateway_token(A);self.store.gateway_token(B);self.store.destroy(A)
        self.assertFalse((self.root/A).exists());self.assertTrue((self.root/B).exists())
        self.store.destroy(A)  # idempotent
    def test_provider_key_issue_is_idempotent_and_revocable(self):
        calls=[]
        def http(method,path,body):
            calls.append((path,body))
            return (200,{'key':'sk-'+'k'*30}) if path=='/key/generate' else (200,{})
        keys=ProviderKeys(http,self.store)
        self.assertTrue(keys.issue(A,'acct1',max_budget_usd=25,duration_days=30,models=['m']))
        self.assertFalse(keys.issue(A,'acct1',max_budget_usd=25,duration_days=30,models=['m']))
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1]['max_budget'],25);self.assertEqual(calls[0][1]['models'],['m'])
        self.assertEqual((calls[0][1]['rpm_limit'],calls[0][1]['tpm_limit']),(30,200000))   # provider rate limits are always set
        self.assertTrue(keys.revoke(A));self.assertEqual(calls[-1][0],'/key/delete')
        self.assertFalse(keys.revoke(B))
    def test_unbounded_or_open_keys_are_refused(self):
        keys=ProviderKeys(lambda *a:(200,{'key':'sk-'+'k'*30}),self.store)
        for kw in [dict(max_budget_usd=0),dict(max_budget_usd=True),dict(max_budget_usd=5000),
                   dict(duration_days=0),dict(models=[]),dict(models=None),dict(rpm_limit=0),dict(tpm_limit=True)]:
            args=dict(max_budget_usd=25,duration_days=30,models=['m']);args.update(kw)
            with self.assertRaises(CustodyError): keys.issue(A,'acct1',**args)
    def test_failed_issuance_stores_nothing(self):
        keys=ProviderKeys(lambda *a:(500,{}),self.store)
        with self.assertRaises(CustodyError): keys.issue(A,'acct1',max_budget_usd=25,duration_days=30,models=['m'])
        self.assertIsNone(self.store.provider_key(A))
if __name__=='__main__': unittest.main()
