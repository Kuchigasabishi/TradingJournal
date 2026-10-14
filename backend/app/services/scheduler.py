"""The threads that keep the feeds fresh (docs/BLUEPRINT.md, P2).

No scheduler library: one daemon thread per enabled feed, started with the application and stopped with it. A
worker sleeps until its feed is due (the schedule lives in the database, so a restart does not refetch early) or
until it is poked by a manual sync request, then runs one sync. The request that asked for the sync has long since
been answered: a slow or dead host can only ever hold up its own worker.
"""
import logging
import threading

from app.services.feeds import FeedService

log = logging.getLogger("app.feeds")


class FeedWorker(threading.Thread):
    def __init__(self, service: FeedService, name: str) -> None:
        super().__init__(name=f"feed-{name}", daemon=True)
        self.service = service
        self.feed = name
        self.poked = threading.Event()
        self.stopping = threading.Event()

    def run(self) -> None:
        tick = self.service.settings.feed_tick_seconds
        while not self.stopping.is_set():
            try:
                trigger, wait = self.service.next_work(self.feed)
                if trigger is not None:
                    self.service.run_sync(self.feed, trigger)
                    continue  # look again straight away: another request may have queued meanwhile
                self.poked.wait(min(wait, tick))
                self.poked.clear()
            except Exception:  # keep the worker alive whatever happens; the next tick retries
                log.exception("feed_worker_error", extra={"feed": self.feed})
                self.stopping.wait(tick)


class FeedScheduler:
    def __init__(self, service: FeedService) -> None:
        self.service = service
        self.workers = {name: FeedWorker(service, name) for name, source in service.sources.items() if source.enabled}

    def start(self) -> None:
        self.service.prepare()
        for worker in self.workers.values():
            worker.start()
        settings = self.service.settings
        log.info("feeds_started", extra={"feeds": sorted(self.workers), "mode": settings.feeds_mode, "fixture_hosts": sorted(settings.fixture_hosts)})

    def poke(self, name: str) -> None:
        worker = self.workers.get(name)
        if worker is not None:
            worker.poked.set()

    def stop(self, timeout: float = 10.0) -> None:
        for worker in self.workers.values():
            worker.stopping.set()
            worker.poked.set()
        for worker in self.workers.values():
            worker.join(timeout)
        log.info("feeds_stopped", extra={"feeds": sorted(self.workers)})
