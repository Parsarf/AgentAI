from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import unittest
from agentai_platform.capacity import slots,assess

class CapacityChecks(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.rows={k:{'total':100,'fixed':20,'reserve':10,'tenant':20} for k in ['memory','cpu','disk','pids']}
    def check(self,**kw):
        return assess(self.rows,measured_at=kw.pop('measured_at',self.now),now=self.now,isolation_verified=kw.pop('isolation_verified',True),tenant_peak_verified=kw.pop('tenant_peak_verified',True),shared_host_selected=kw.pop('shared_host_selected',True),**kw)
    def test_limits_and_existing_reservations(self):
        self.assertEqual(self.check().admitted_slots,3)
        self.rows['memory']['fixed']=60
        self.assertEqual(self.check().admitted_slots,1)
    def test_negative_headroom_is_zero(self):
        self.rows['memory']['fixed']=95
        self.assertEqual(self.check().admitted_slots,0)
        self.assertIn('memory_exhausted',self.check().blockers)
    def test_unknown_peak_is_not_zero_cost_or_a_slot(self):
        self.rows['cpu']['tenant']=None
        self.assertIsNone(self.check().cpu_slots)
        self.assertEqual(self.check().admitted_slots,0)
    def test_missing_isolation_or_unmeasured_tenant_blocks(self):
        self.assertEqual(self.check(isolation_verified=False).admitted_slots,0)
        self.assertEqual(self.check(tenant_peak_verified=False).admitted_slots,0)
    def test_stale_or_future_measurement_blocks(self):
        for t in [self.now-timedelta(minutes=16),self.now+timedelta(minutes=2)]:
            self.assertEqual(self.check(measured_at=t).admitted_slots,0)
    def test_invalid_or_boolean_units_rejected(self):
        for tenant in [0,-1,True]:
            with self.assertRaises(ValueError):slots(10,1,1,tenant)
    def test_other_resources_bound_ram_result(self):
        self.rows['disk']['total']=50
        self.assertEqual(self.check().admitted_slots,1)
        self.assertEqual(self.check(shared_host_selected=False).admitted_slots,0)
