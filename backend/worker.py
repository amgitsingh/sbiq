"""
Worker entrypoint — starts both queues in a single process (dev/staging).
For production, run enrichment and matching workers separately:

    # Enrichment worker
    python worker.py --queues enrichment

    # Matching worker
    python worker.py --queues matching
"""
import sys

from app.workers.celery_app import celery_app

if __name__ == "__main__":
    queues = "enrichment,matching"
    extra_args = sys.argv[1:]

    # Allow --queues override from CLI
    if not any(a.startswith("--queues") for a in extra_args):
        extra_args = [f"--queues={queues}"] + extra_args

    celery_app.worker_main(argv=["worker", "--loglevel=info"] + extra_args)
