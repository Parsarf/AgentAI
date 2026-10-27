"""Historical picture storage remains readable; automatic remote enrichment is retired."""
from tests.test_native_run import Base
from agentai_platform.genui.images import ImageStore

class HistoricalImages(Base):
    def test_pictures_remain_readable_only_by_the_owning_account(self):
        with self.store.connect() as con:
            con.execute("INSERT INTO card_images VALUES ('a','image','image/png',200,200,'historical.example',?,1)", (b'preserved picture',))
        images = ImageStore(self.store)
        self.assertEqual(images.read('a', 'image')['body'], b'preserved picture')
        self.assertIsNone(images.read('b', 'image'))
        self.assertIsNone(images.read('a', 'missing'))
