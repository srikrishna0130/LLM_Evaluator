import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.core.exceptions import ResourceNotFoundError, BusinessLogicError, DomainException

log = logging.getLogger(__name__)

async def resource_not_found_handler(request: Request, exc: ResourceNotFoundError):
    """Handles 404 Not Found errors originating from the domain layer."""
    log.warning(f"Resource not found: {exc.message} - Path: {request.url.path}")
    return JSONResponse(
        status_code=404,
        content={"error": "Not Found", "message": exc.message}
    )

async def business_logic_error_handler(request: Request, exc: BusinessLogicError):
    """Handles 400 Bad Request errors originating from business rule violations."""
    log.warning(f"Business rule violation [{exc.code}]: {exc.message}")
    return JSONResponse(
        status_code=400,
        content={
            "error": "Bad Request",
            "message": exc.message,
            "code": exc.code
        }
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Overrides FastAPI's default 422 handler to provide cleaner error outputs."""
    log.warning(f"Validation error on payload: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation Error",
            "details": exc.errors()
        }
    )

async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all handler for unhandled exceptions (500s).
    Ensures internal stack traces are NEVER leaked to the client.
    """
    log.error(f"Unhandled server error at {request.url.path}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error", "message": "An unexpected error occurred. Please try again later."}
    )

def register_exception_handlers(app):
    """Utility function to attach handlers to the FastAPI app instance."""
    app.add_exception_handler(ResourceNotFoundError, resource_not_found_handler)
    app.add_exception_handler(BusinessLogicError, business_logic_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)