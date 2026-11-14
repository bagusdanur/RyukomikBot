from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi import Request
from app import app
import sys

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print('VALIDATION ERROR:', exc.errors(), 'BODY:', exc.body, file=sys.stderr)
    return JSONResponse(status_code=422, content={'detail': exc.errors(), 'body': exc.body})
