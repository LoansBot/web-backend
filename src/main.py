from fastapi import FastAPI, Response, status
from lblogging import Level
from constants import LOGGER, MEMCACHED as cache
import json


app = FastAPI()  # noqa
logger = LOGGER.with_iden('main.py')  # noqa


@app.get("/")
def root():
    return {"message": "Hello World"}


@app.get("/test_log")
def test_log():
    logger.print(Level.TRACE, 'test_log')
    logger.connection.commit()
    return Response(status_code=status.HTTP_200_OK)


@app.get("/test_cache")
def test_cache():
    resp = json.dumps({'message': 'how you doing'})
    cache.set('test', resp.encode('utf-8'))
    return json.loads(cache.get('test').decode('utf-8'))
