class IdempotencyKeyConflictError(Exception):
    """The idempotency key was already used with a different request body."""


class PaymentProcessingError(Exception):
    """Simulated transient payment processing failure."""


class PaymentNotFoundError(Exception):
    """The payment referenced by a message does not exist."""


class WebhookDeliveryError(Exception):
    """The merchant's webhook could not be delivered."""
