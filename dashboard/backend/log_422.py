from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import sys

def setup_exception_handler(app):
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        print('--- VALIDATION ERROR ---', file=sys.stderr)
        print('URL:', request.url, file=sys.stderr)
        print('BODY:', exc.body, file=sys.stderr)
        print('ERRORS:', exc.errors(), file=sys.stderr)
        print('------------------------', file=sys.stderr)
        return JSONResponse(status_code=422, content={'detail': exc.errors(), 'body': exc.body})
