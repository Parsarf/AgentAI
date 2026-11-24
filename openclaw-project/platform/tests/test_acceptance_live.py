"""The deploy's live acceptance must be able to make its test chat: when it cannot, a good release is rolled back (production, 2026-11-24, twice: first because the test
account's first project was full, then because the fix looked for the wrong status and refused the chats it had just made)."""
import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'deploy' / 'acceptance_live.py'


def load(name):
    """One function of the acceptance script, without running the script (which sets the web framework up against the live settings when imported)."""
    tree = ast.parse(SOURCE.read_text())
    found = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    scope = {}
    exec(compile(ast.Module(body=[found], type_ignores=[]), str(SOURCE), 'exec'), scope)
    return scope[name]


class Answer:
    def __init__(self, status_code, body):
        self.status_code, self.body = status_code, body
    def json(self):
        if self.body is None:
            raise ValueError('not json')
        return self.body


class TestChat(unittest.TestCase):
    def setUp(self):
        self.first_chat, self.asked = load('first_chat'), []

    def create(self, answers):
        def call(project):
            self.asked.append(project)
            return answers[project]
        return call

    def test_the_endpoint_answers_201_and_that_is_a_chat(self):
        self.assertIn("return JsonResponse({'conversation': created}, status=201)", (SOURCE.parents[1] / 'accounts' / 'chat.py').read_text())      # what the real endpoint answers
        chat, refused = self.first_chat(['p1', 'p2'], self.create({'p1': Answer(201, {'conversation': {'id': 'c1', 'project_id': 'p1'}})}))
        self.assertEqual((chat, refused, self.asked), ('c1', [], ['p1']))                    # one chat, and it stops there

    def test_a_full_project_is_passed_over_for_the_next_one_with_room(self):
        answers = {'p1': Answer(409, {'error': 'conversation_conflict'}), 'p2': Answer(201, {'conversation': {'id': 'c2'}}), 'p3': Answer(201, {'conversation': {'id': 'c3'}})}
        chat, refused = self.first_chat(['p1', 'p2', 'p3'], self.create(answers))
        self.assertEqual((chat, refused, self.asked), ('c2', [409], ['p1', 'p2']))            # never a second chat

    def test_every_project_full_says_so_and_anything_else_is_not_mistaken_for_it(self):
        full = Answer(409, {'error': 'conversation_conflict'})
        self.assertEqual(self.first_chat(['p1', 'p2'], self.create({'p1': full, 'p2': full})), (None, [409, 409]))
        self.assertEqual(self.first_chat(['p1', 'p2'], self.create({'p1': full, 'p2': Answer(503, None)})), (None, [409, 503]))
        self.assertEqual(self.first_chat([], self.create({})), (None, []))


if __name__ == '__main__':
    unittest.main()
