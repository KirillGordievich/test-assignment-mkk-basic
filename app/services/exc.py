class IdempotencyKeyConflictError(Exception):
    """The idempotency key was already used with a different request body."""
