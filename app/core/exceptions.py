class DomainException(Exception):
    """Base class for all custom domain exceptions."""
    pass

class ResourceNotFoundError(DomainException):
    """Raised when a requested resource (e.g., User, Todo) does not exist."""
    def __init__(self, message: str = "The requested resource was not found."):
        self.message = message
        super().__init__(self.message)

class BusinessLogicError(DomainException):
    """Raised when an action violates business rules (e.g., Insufficient funds)."""
    def __init__(self, message: str, code: str = "BUSINESS_RULE_VIOLATION"):
        self.message = message
        self.code = code
        super().__init__(self.message)