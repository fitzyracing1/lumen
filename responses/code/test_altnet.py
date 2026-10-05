import unittest
from altnet import Node, demo, name_of


class AltNetTest(unittest.TestCase):
    def test_name_is_content_hash(self):
        self.assertEqual(name_of(b"same"), name_of(b"same"))
        self.assertNotEqual(name_of(b"same"), name_of(b"other"))

    def test_get_crosses_nodes_without_dns(self):
        a, b, c = Node("a"), Node("b"), Node("c")
        a.neighbors = [b]
        b.neighbors = [c]
        key = c.publish(b"packet")
        self.assertIsNone(a.store.get(key))
        self.assertEqual(a.get(key), b"packet")
        self.assertEqual(a.store[key], b"packet")

    def test_demo_returns_the_published_text(self):
        self.assertEqual(demo(), "hello from the other net")


if __name__ == "__main__":
    unittest.main()
