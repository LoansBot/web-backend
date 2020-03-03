from fastapi import FastAPI, Response, status
from lblogging import Logger, Level
from logging import LOGGER

app = FastAPI()  # noqa
logger = LOGGER.with_iden('main.py')  # noqa


@app.get("/")
def root():
    return {"message": "Hello World"}


@app.get("/test_log")
def test_log():
    logger.print(Level.TRACE, 'test_log')
    return Response(status_code=status.HTTP_200_OK)
