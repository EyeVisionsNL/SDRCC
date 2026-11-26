"""Read-only systemd classification and bounded restart policy for receiver services."""
from dataclasses import dataclass


def restarting(observation):
    return str(observation.get('sub_state') or '').lower().startswith('auto-restart')


def stopped(observation):
    return (not observation.get('active') and not restarting(observation)
            and observation.get('state') in {'inactive', 'failed'})


def transitional(observation):
    return observation.get('state') in {'activating', 'deactivating', 'reloading'} or restarting(observation)


def lifecycle_override(observations):
    """Never advertise a service that is restarting as stopped."""
    if any(restarting(item) for item in observations):
        return 'RESTARTING', 'systemd is automatically restarting a failed receiver service.'
    if any(item.get('state') == 'deactivating' for item in observations):
        return 'STOPPING', 'Receiver service is shutting down.'
    if any(item.get('state') == 'activating' for item in observations):
        return 'STARTING', 'Receiver service is starting.'
    if any(item.get('state') == 'failed' for item in observations):
        return 'FAILED', 'Receiver service failed; inspect the logs or use Recover Receiver.'
    if any(not item.get('active') and not stopped(item) for item in observations):
        return 'ATTENTION', 'Receiver service state could not be verified.'
    return None


def readsb_samples_processed(stats):
    """Optional raw-sample counter, not the number of aircraft or messages."""
    if not isinstance(stats, dict):
        return None
    total = stats.get("total")
    if not isinstance(total, dict):
        return None
    local = total.get("local")
    if not isinstance(local, dict):
        return None
    value = local.get("samples_processed")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if value >= 0 else None


@dataclass
class RecoveryBudget:
    attempts: int = 0
    healthy_since: float | None = None
    exhausted: bool = False

    def observe(self, observation, now, *, healthy=False):
        """Only repeated failures qualify; no recovery on an idle receiver."""
        if healthy and observation.get('active') and not restarting(observation):
            if self.healthy_since is None:
                self.healthy_since = now
            elif now - self.healthy_since >= 120:
                self.attempts = 0
                self.exhausted = False
            return False
        self.healthy_since = None
        if not restarting(observation):
            return False
        if observation.get('restart_count', 0) < 3 and not self.attempts:
            return False
        return not self.exhausted

    def take_attempt(self):
        if self.attempts >= 2:
            self.exhausted = True
            return False
        self.attempts += 1
        return True
