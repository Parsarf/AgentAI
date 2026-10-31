"""Pictures on comparison cards, served from our own origin to the account that owns them (see agentai_platform/genui/images.py).
The browser never reaches the store a picture came from. The picture is shown inline but can never run anything: it is sandboxed and not sniffed."""
import re
from django.db import connection
from django.http import HttpResponse
from agentai_platform.genui.images import ImageStore
from .lifecycle import AccountStore
from .services import Denied, rate
from .views import endpoint, customer

IMAGE_ID = re.compile(r'^[a-f0-9]{32}$')


@endpoint(['GET'])
def card_image(request, image_id):
    denied = customer(request)
    if denied:
        return denied
    if not IMAGE_ID.fullmatch(image_id):
        raise Denied()
    rate('media.read', request.account_id, 3000, 3600)
    row = ImageStore(AccountStore(connection.settings_dict['NAME'])).read(request.account_id, image_id)
    if row is None:
        raise Denied()                                                    # also what another account's picture looks like: not there
    response = HttpResponse(row['body'], content_type=row['mime'])
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cross-Origin-Resource-Policy'] = 'same-origin'
    response['Cache-Control'] = 'private, max-age=31536000, immutable'    # the id is the file's own hash, so it can never change
    return response
