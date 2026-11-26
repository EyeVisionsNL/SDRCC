import unittest
from core.receiver_reliability import RecoveryBudget, lifecycle_override, restarting, stopped, transitional, readsb_samples_processed


class ReliabilityTests(unittest.TestCase):
    def test_crash_loop_is_not_stopped(self):
        state = dict(active=False, state='activating', sub_state='auto-restart', restart_count=3)
        self.assertTrue(restarting(state))
        self.assertTrue(transitional(state))
        self.assertFalse(stopped(state))
        self.assertEqual(lifecycle_override([state])[0], 'RESTARTING')

    def test_stopping_starting_failed_unknown(self):
        for state, expected in [('deactivating', 'STOPPING'), ('activating', 'STARTING'), ('failed', 'FAILED'), ('unknown', 'ATTENTION')]:
            self.assertEqual(lifecycle_override([{'state': state}])[0], expected)
        self.assertTrue(stopped({'state': 'inactive'}))
        self.assertIsNone(lifecycle_override([{'state': 'inactive'}]))

    def test_two_attempts_only(self):
        budget = RecoveryBudget()
        state = dict(active=False, state='activating', sub_state='auto-restart', restart_count=3)
        self.assertTrue(budget.observe(state, 0))
        self.assertTrue(budget.take_attempt())
        self.assertTrue(budget.observe(state, 1))
        self.assertTrue(budget.take_attempt())
        self.assertTrue(budget.observe(state, 2))
        self.assertFalse(budget.take_attempt())
        self.assertFalse(budget.observe(state, 3))

    def test_never_start_stopped_or_recover_single_failure(self):
        budget = RecoveryBudget()
        self.assertFalse(budget.observe({'state': 'inactive'}, 0))
        self.assertFalse(budget.observe({'state': 'activating', 'sub_state': 'auto-restart', 'restart_count': 1}, 1))

    def test_raw_sample_counter_not_aircraft_or_messages(self):
        self.assertIsNone(readsb_samples_processed({"total": {"messages": 0}}))
        self.assertEqual(readsb_samples_processed({"total": {"local": {"samples_processed": 0}}}), 0)
        self.assertEqual(readsb_samples_processed({"total": {"local": {"samples_processed": 1234}, "messages": 0}}), 1234)

    def test_sustained_health_rearms_budget(self):
        budget = RecoveryBudget(attempts=2, exhausted=True)
        state = dict(active=True, state='active', sub_state='running')
        budget.observe(state, 0, healthy=True)
        budget.observe(state, 119, healthy=True)
        self.assertTrue(budget.exhausted)
        budget.observe(state, 120, healthy=True)
        self.assertFalse(budget.exhausted)
        self.assertEqual(budget.attempts, 0)


if __name__ == '__main__':
    unittest.main()
