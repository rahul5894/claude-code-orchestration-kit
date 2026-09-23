import logging

logger = logging.getLogger(__name__)


class EmailNotifier:
    def __init__(self, sender="orders@shop.example"):
        self.sender = sender
        self.outbox = []

    def send(self, to, subject, body):
        self.outbox.append(
            {"from": self.sender, "to": to, "subject": subject, "body": body}
        )
        logger.info("queued email: %s", subject)
        return True
