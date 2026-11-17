"""The knowledge evaluation set as a regression gate (roadmap Phase 4 exit gate 1). The same set runs live on the server with the real reader, the vision model, the
self-hosted embedding model and PostgreSQL (`deploy/phase45_live.py`); here it runs in-process with the deterministic stand-in embedder, so these floors are that
embedder's measured results (2026-11-16), not the live targets, which are in `plans/product/roadmap/phase-04.md`."""
import json
import unittest

from agentai_platform import knowledge_eval as E
from tests.test_knowledge import KnowledgeBase


class Evaluation(KnowledgeBase):
    def add(self, name, data):
        fid = self.upload(self.a, name, data)
        return self.service.add(self.a, 'upload', fid)['id']

    def test_the_evaluation_set(self):
        report = E.run(self.service, self.a, self.add, wait=lambda: [self.service.work_once(limit=50) for _ in range(3)])
        print('\nknowledge evaluation (stand-in embedder): ' + json.dumps(report))
        self.assertEqual(report['not_ready'], [])
        r = report['retrieval']
        self.assertGreaterEqual(r['recall_at_10'], FLOOR['recall_at_10'], r['misses'])
        self.assertGreaterEqual(r['recall_at_5'], FLOOR['recall_at_5'], r['misses'])
        self.assertGreaterEqual(r['top_1'], FLOOR['top_1'], r['misses'])
        self.assertGreaterEqual(r['citation_correct'], FLOOR['citation_correct'])
        self.assertGreaterEqual(report['tables']['accuracy'], FLOOR['table_cells'], report['tables'])
        self.assertEqual(report['comparison'], {'changed_number': True, 'changed_notice': True, 'moved_clause': True})
        self.assertEqual(report['conflicts']['reported'], report['conflicts']['planted'])            # a planted conflict is always reported
        self.assertEqual(report['claims']['flagged'], report['claims']['planted_unsupported'])        # every planted unsupported claim is caught
        self.assertEqual(report['claims']['wrong'], 0)


# Measured 2026-11-16 with the stand-in embedder (deterministic): recall@10 0.976, recall@5 0.952, top-1 0.738, citations 1.0, table cells 1.0 (116 of 116).
FLOOR = {'recall_at_10': 0.97, 'recall_at_5': 0.95, 'top_1': 0.73, 'citation_correct': 1.0, 'table_cells': 1.0}

if __name__ == '__main__':
    unittest.main()
