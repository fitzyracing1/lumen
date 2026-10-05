import unittest
from plan_gate import allow, score


class PlanGateTest(unittest.TestCase):
    def test_high_risk_is_refused(self):
        self.assertFalse(allow(0.9, 0.8))

    def test_clean_plan_passes(self):
        self.assertTrue(allow(0.84, 0.18))
        self.assertGreater(score(0.84, 0.18), 0.35)


if __name__ == "__main__":
    unittest.main()
