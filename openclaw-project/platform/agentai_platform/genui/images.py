"""Read-only access to historical, account-owned card images. New documents use authorized project files."""
class ImageStore:
    def __init__(self, store):
        self.store = store

    def read(self, account_id: str, image_id: str):
        with self.store.connect() as con:
            row = con.execute('SELECT mime,body,width,height FROM card_images WHERE account_id=? AND id=?', (account_id, image_id)).fetchone()
        return dict(row) if row else None
