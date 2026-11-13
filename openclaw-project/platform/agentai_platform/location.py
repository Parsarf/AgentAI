"""One-shot customer-device geolocation, never the server browser's location.

Only the admitted tool creates requests. Authenticated customer HTTP claims and
answers them. Public events contain no coordinates. Terminal requests prevent
repeat prompts in the same task; consumed coordinates are immediately blanked.
"""
import json
import math
import time
import uuid
from . import request_states
from .lifecycle.coordinator import Coordinator, identifier
from .security import NotFound

NAME = 'lumina_request_location'
TOOL = {'name': NAME, 'description': 'Request the customer’s current device location through their open Lumina website. Call immediately when a task needs “near me” or current location and the customer has not supplied a place. Waits for browser permission and returns granted coordinates with accuracy, denied, unavailable, timeout or cancelled. Never infer location from server/IP. On denial ask the customer to allow location in Chrome or tell you their city, ZIP code or address. Do not repeat a denied request.',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}
TTL = 120
LEASE = 15


def prompt():
    return '\nFor “near me” or tasks needing the customer’s current location, call `lumina_request_location` immediately unless the customer supplied a place. Use its device coordinates and accuracy only if granted. If denied, say: “I didn’t get permission to use your location. Please allow location access in Chrome, or tell me your city, ZIP code, or address so I can continue.” For timeout/unavailable explain that location could not be obtained and ask for a place; never describe these as refusal. Do not guess from the server location or repeatedly request permission.\n'


class Locations:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock
        self.coordinator = Coordinator(store, clock=clock)

    def cleanup(self):
        """Worker housekeeping also clears orphaned handoffs after relay restart."""
        with self.coordinator.transaction() as con:
            now = int(self.clock())
            con.execute("UPDATE location_requests SET status='timeout',position_json=NULL WHERE status='pending' AND expires_epoch<=?", (now,))
            con.execute('UPDATE location_requests SET position_json=NULL WHERE position_json IS NOT NULL AND expires_epoch<=?', (now,))
            con.execute(f"""UPDATE location_requests SET status='cancelled',position_json=NULL
                WHERE status IN ('pending','granted') AND EXISTS
                (SELECT 1 FROM customer_requests r WHERE r.account_id=location_requests.account_id
                 AND r.id=location_requests.request_id AND NOT ({request_states.live_run()}))""")
            con.execute("DELETE FROM location_requests WHERE expires_epoch<? AND status!='pending'", (now - 30 * 86400,))

    def live(self, con, account, request):
        return request_states.is_live_run(con, account, request, funded=True, active_account=True)

    def sweep(self, con, account):
        now = int(self.clock())
        con.execute("UPDATE location_requests SET status='timeout',position_json=NULL WHERE account_id=? AND status='pending' AND expires_epoch<=?", (account, now))
        rows = con.execute("SELECT request_id FROM location_requests WHERE account_id=? AND status IN ('pending','granted')", (account,)).fetchall()
        for row in rows:
            if not self.live(con, account, row['request_id']):
                con.execute("UPDATE location_requests SET status='cancelled',position_json=NULL WHERE account_id=? AND request_id=?", (account, row['request_id']))
        con.execute('UPDATE location_requests SET position_json=NULL WHERE account_id=? AND expires_epoch<=?', (account, now))

    def start(self, account, request):
        with self.coordinator.transaction() as con:
            self.sweep(con, account)
            if not self.live(con, account, request):
                raise NotFound('No admitted live task')
            con.execute("INSERT OR IGNORE INTO location_requests(account_id,request_id,id,status,expires_epoch) VALUES (?,?,?,'pending',?)",
                        (account, request, uuid.uuid4().hex, int(self.clock()) + TTL))

    def pending(self, account):
        with self.coordinator.transaction() as con:
            self.sweep(con, account)
            row = con.execute("SELECT id,expires_epoch FROM location_requests WHERE account_id=? AND status='pending' ORDER BY expires_epoch LIMIT 1", (account,)).fetchone()
            return dict(row) if row else None

    def answer(self, account, loc_id, data):
        identifier(loc_id)
        client = identifier(data.get('client_id'))
        action = data.get('action')
        if action not in ('claim', 'respond'):
            raise ValueError('invalid action')
        status = data.get('status')
        position = None
        if action == 'respond':
            if status not in ('granted', 'denied', 'unavailable', 'timeout'):
                raise ValueError('invalid status')
            if status == 'granted':
                position = data.get('position')
                bounds = {'latitude': (-90, 90), 'longitude': (-180, 180), 'accuracy': (0, 100000000)}
                if not isinstance(position, dict) or set(position) != set(bounds):
                    raise ValueError('invalid position')
                for key, (lo, hi) in bounds.items():
                    value = position[key]
                    if type(value) not in (float, int) or not lo <= value <= hi or not math.isfinite(value):
                        raise ValueError('invalid position')
            elif data.get('position') is not None:
                raise ValueError('unexpected position')
        with self.coordinator.transaction() as con:
            self.sweep(con, account)
            row = con.execute('SELECT * FROM location_requests WHERE account_id=? AND id=?', (account, loc_id)).fetchone()
            if not row:
                raise NotFound('unavailable')
            now = int(self.clock())
            if row['status'] != 'pending':
                return {'accepted': False, 'status': row['status']}
            owns = row['client_id'] == client
            if action == 'claim':
                if not owns and row['claim_until'] > now:
                    return {'accepted': False, 'status': 'pending'}
                con.execute('UPDATE location_requests SET client_id=?,claim_until=? WHERE account_id=? AND id=?', (client, now + LEASE, account, loc_id))
                return {'accepted': True, 'status': 'pending'}
            if not owns or row['claim_until'] <= now:
                return {'accepted': False, 'status': 'pending'}
            con.execute('UPDATE location_requests SET status=?,position_json=? WHERE account_id=? AND id=?', (status, json.dumps(position) if position else None, account, loc_id))
            return {'accepted': True, 'status': status}

    def take(self, account, request, cancel=False):
        with self.coordinator.transaction() as con:
            self.sweep(con, account)
            if cancel:
                con.execute("UPDATE location_requests SET status='cancelled',position_json=NULL WHERE account_id=? AND request_id=? AND status IN ('pending','granted')", (account, request))
            row = con.execute('SELECT * FROM location_requests WHERE account_id=? AND request_id=?', (account, request)).fetchone()
            if not row or row['status'] == 'pending':
                return None
            result = {'status': row['status']}
            if row['status'] == 'granted':
                if row['position_json']:
                    result['position'] = json.loads(row['position_json'])
                else:
                    result = {'status': 'unavailable', 'reason': 'Location result already consumed or expired. Ask the customer for a place.'}
                con.execute('UPDATE location_requests SET position_json=NULL WHERE account_id=? AND request_id=?', (account, request))
            return result

    def waiting(self, account, request):
        with self.coordinator.transaction() as con:
            self.sweep(con, account)
            return con.execute("SELECT 1 FROM location_requests WHERE account_id=? AND request_id=? AND status='pending'", (account, request)).fetchone() is not None


class LocationTool:
    def __init__(self, store, *, clock=time.time, sleep=time.sleep):
        self.locations, self.sleep = Locations(store, clock), sleep

    def call(self, account, arguments, closed=lambda: False, *, name=NAME, request_id=None):
        if name != NAME or arguments or not request_id:
            return json.dumps({'status': 'unavailable', 'reason': 'An admitted task is required.'}), True
        try:
            self.locations.start(account, request_id)
            while True:
                result = self.locations.take(account, request_id, cancel=closed())
                if result is not None:
                    return json.dumps(result), False
                self.sleep(.25)
        except NotFound:
            return json.dumps({'status': 'cancelled'}), False
